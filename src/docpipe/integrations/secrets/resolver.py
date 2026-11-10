# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Shared resolver for ``vault://`` references in a node configuration (design D1).

``resolve_node_config`` is the single place that turns the references in one
node's configuration into :class:`~docpipe.integrations.secrets.SecretValue`
objects. It is a pure function of the node configuration, the operator's
declarations, and the deployment policy:

1. Only secret-capable fields (``get_metadata()`` declarations, design D2) may
   hold a reference. A reference anywhere else is rejected as ``not permitted``.
2. Every reference is parsed with the strict grammar (``parse_reference``), the
   provider must be registered, and the reference must match
   ``secrets.vault.allowed_paths`` (deny by default, design D4/D4b).
3. When any field of the node resolves from a provider, destination fields
   (``endpoint_url``, ``host``, ``uri``, ``api_base``, ``url``, ``base_url``)
   must be references or match ``secrets.vault.allowed_destinations``.
4. Only after all of the above passed for every reference is the provider
   called, so a denial never costs a Vault request. The first failure aborts the
   node and no later reference is resolved.
5. The type rule applies to the stored value: scalar fields must hold a string,
   structured fields (``credentials_json``) are parsed once.

Failures raise :class:`SecretResolutionError`. Its message holds only a fixed
category, the config key path, the provider name and a correlation identifier.
The detail goes to the server-side log under the same identifier.

:func:`inspect_node_references` applies the same checks that need no provider
call (grammar, declaration, registration, path policy, destination binding) to a
whole node without raising and without reading a secret. Flow validation uses it.

The resolver does not expand ``$ENV`` forms and writes nothing to the
``docpipe.audit`` logger yet.
"""

import fnmatch
import json
import re
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit

from docpipe.core.operators.secret_fields import (
    DECLARED_BY_PROVIDER_KEY,
    DESTINATION_FIELD_NAMES,
    STRUCTURED_FIELD_NAMES,
    effective_secret_fields,
)
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.integrations.secrets.registry import register_secret
from docpipe.integrations.secrets.secret_provider import (
    MalformedSecretReferenceError,
    ProviderUnreachableError,
    SecretReference,
    get_provider,
    has_vault_references,
    is_vault_reference,
    parse_reference,
    registered_provider_names,
)
from docpipe.integrations.secrets.secret_value import SecretValue
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader
from docpipe.utils.infrastructure.exception_sanitizer import sanitize_exception
from docpipe.utils.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from docpipe.core.operators.abstract_operator import AbstractOperator

logger = get_logger()

ALLOW_ALL_ENTRY: Final[str] = "*:**"
_WILDCARD_PROVIDER: Final[str] = "*"
_MAX_DISPLAY_LENGTH: Final[int] = 64
_UNSAFE_DISPLAY_CHARS: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9_.*\-]")

ConfigPath = tuple[str | int, ...]


class SecretErrorCategory(StrEnum):
    """The fixed set of user-visible failure categories."""

    PROVIDER_NOT_REGISTERED = "provider not registered"
    SECRET_UNAVAILABLE = "secret unavailable"  # nosec B105  # pragma: allowlist secret
    VAULT_UNREACHABLE = "vault unreachable"
    MALFORMED_REFERENCE = "malformed reference"
    NOT_PERMITTED = "not permitted"
    VALUE_MUST_BE_STRING = "value must be a string"


class FindingKind(StrEnum):
    """Why :func:`inspect_node_references` reports a reference."""

    MALFORMED = "malformed"
    FIELD_NOT_SECRET_CAPABLE = "field not secret-capable"  # nosec B105  # pragma: allowlist secret
    PROVIDER_NOT_REGISTERED = "provider not registered"
    PATH_NOT_PERMITTED = "path not permitted"
    DESTINATION_NOT_PERMITTED = "destination not permitted"


@dataclass(frozen=True)
class ReferenceFinding:
    """One problem found with a reference by :func:`inspect_node_references`.

    Attributes:
        config_key: Dotted config key path of the field (display-safe).
        kind: What is wrong.
        provider: Provider name from the reference, or None when it did not parse
            or the finding concerns a destination field.
    """

    config_key: str
    kind: FindingKind
    provider: str | None


def _display(*, text: str) -> str:
    """Return ``text`` restricted to a conservative character set, for messages and logs."""
    return _UNSAFE_DISPLAY_CHARS.sub("_", text)[:_MAX_DISPLAY_LENGTH]


def _display_path(*, path: ConfigPath) -> str:
    """Return the dotted config key path of ``path`` in display form."""
    return ".".join(_display(text=str(segment)) for segment in path)


class SecretResolutionError(DocpipeException):
    """A reference in a node configuration could not be resolved.

    The message never contains a secret value, reference text beyond the
    provider and config key path, a Vault path or key name, a response body, or
    underlying exception text. The chained exception is not attached: the detail
    is in the server-side log under ``correlation_id``.

    Attributes:
        category: One of the fixed :class:`SecretErrorCategory` values.
        config_key: Dotted config key path of the field holding the reference.
        provider: Provider name from the reference, or None when it did not parse.
        correlation_id: Identifier that also appears in the server-side log entry.
        node_name: Flow node the reference belongs to.
    """

    def __init__(
        self,
        *,
        category: SecretErrorCategory,
        config_key: str,
        provider: str | None,
        correlation_id: str,
        node_name: str | None = None,
    ) -> None:
        subject = f"secret reference {config_key}"
        if provider:
            subject = f"{subject} (provider {provider})"
        message = f"{subject}: {category.value} [id {correlation_id}]"
        if category is SecretErrorCategory.MALFORMED_REFERENCE:
            message = f"{message}; expected vault://<provider>/<path>[#<key>]"
        unreachable = category is SecretErrorCategory.VAULT_UNREACHABLE
        super().__init__(
            message,
            status_code=502 if unreachable else 400,
            error_code=ErrorCode.EXTERNAL_SERVICE_ERROR if unreachable else ErrorCode.INVALID_CONFIGURATION,
        )
        self.category = category
        self.config_key = config_key
        self.provider = provider
        self.correlation_id = correlation_id
        self.node_name = node_name


# ---------------------------------------------------------------------------
# Deployment policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PathRule:
    """One parsed ``provider:glob[@operator.field]`` entry of ``secrets.vault.allowed_paths``."""

    provider: str
    pattern: re.Pattern[str]
    operator: str | None
    field: str | None


@dataclass(frozen=True)
class SecretPolicy:
    """The deployment policy: which Vault paths and destinations a flow may use.

    Attributes:
        rules: Parsed ``secrets.vault.allowed_paths`` entries. Empty means deny every reference.
        destinations: Lower-case host globs from ``secrets.vault.allowed_destinations``.
    """

    rules: tuple[_PathRule, ...]
    destinations: tuple[str, ...]

    @staticmethod
    def _read_settings() -> tuple[Any, Any]:
        """Return the raw ``allowed_paths`` and ``allowed_destinations`` values.

        Reads through ``DocpipeConfigLoader.get_config()`` rather than ``get()``:
        ``get()`` substitutes its default for any falsy value and logs on every call.
        """
        secrets_section = DocpipeConfigLoader.get_config().get("secrets")
        vault_section = secrets_section.get("vault") if isinstance(secrets_section, dict) else None
        if not isinstance(vault_section, dict):
            return None, None
        return vault_section.get("allowed_paths"), vault_section.get("allowed_destinations")

    @staticmethod
    def _glob_to_regex(*, glob: str) -> re.Pattern[str]:
        """Compile a path glob: ``*`` stays within one segment, ``**`` crosses segments."""
        parts: list[str] = []
        index = 0
        while index < len(glob):
            if glob.startswith("**", index):
                parts.append(".*")
                index += 2
            elif glob[index] == "*":
                parts.append("[^/]*")
                index += 1
            else:
                parts.append(re.escape(glob[index]))
                index += 1
        return re.compile("".join(parts), re.DOTALL)

    @staticmethod
    def _parse_rule(*, entry: str) -> _PathRule | None:
        """Parse one policy entry, or return None when it is malformed (and so denies nothing)."""
        provider, separator, rest = entry.strip().partition(":")
        if not separator or not provider or not rest:
            return None
        operator: str | None = None
        field: str | None = None
        if "@" in rest:
            rest, _, scope = rest.rpartition("@")
            operator, dot, field = scope.partition(".")
            if not rest or not operator or not dot or not field:
                return None
        return _PathRule(
            provider=provider,
            pattern=SecretPolicy._glob_to_regex(glob=rest),
            operator=operator,
            field=field,
        )

    @staticmethod
    @lru_cache(maxsize=64)
    def _compile_rules(*, entries: tuple[str, ...]) -> tuple[_PathRule, ...]:
        rules = (SecretPolicy._parse_rule(entry=entry) for entry in entries)
        return tuple(rule for rule in rules if rule is not None)

    @classmethod
    def from_settings(cls, *, allowed_paths: Any, allowed_destinations: Any) -> "SecretPolicy":
        """Build a policy from raw settings. A value of the wrong type contributes nothing (deny)."""
        paths = (
            tuple(item for item in allowed_paths if isinstance(item, str)) if isinstance(allowed_paths, list) else ()
        )
        hosts = (
            tuple(item.strip().lower() for item in allowed_destinations if isinstance(item, str) and item.strip())
            if isinstance(allowed_destinations, list)
            else ()
        )
        return cls(rules=cls._compile_rules(entries=paths), destinations=hosts)

    @classmethod
    def load(cls) -> "SecretPolicy":
        """Load the policy from ``docling-pipelines-config.yaml`` through ``DocpipeConfigLoader``."""
        allowed_paths, allowed_destinations = cls._read_settings()
        return cls.from_settings(allowed_paths=allowed_paths, allowed_destinations=allowed_destinations)

    def permits(self, *, reference: SecretReference, operator: str, config_key: str) -> bool:
        """Return True when an entry allows ``reference`` for ``operator`` at ``config_key``.

        The provider is an exact, case-sensitive match (``*`` matches any provider),
        and the glob is matched case-sensitively against the normalized path. A
        scoped entry (``@operator.field``) applies only to that operator, and to a
        config key equal to ``field`` or ending in ``.field``.
        """
        for rule in self.rules:
            if rule.provider not in (_WILDCARD_PROVIDER, reference.provider):
                continue
            if rule.operator is not None and not (
                rule.operator == operator
                and rule.field is not None
                and (config_key == rule.field or config_key.endswith(f".{rule.field}"))
            ):
                continue
            if rule.pattern.fullmatch(reference.path):
                return True
        return False

    @staticmethod
    def _host_of(*, value: str) -> str | None:
        """Return the lower-case host of a URL or ``host[:port]`` value, or None if it is unusable."""
        if any(char == "\\" or char.isspace() or ord(char) < 32 for char in value):
            return None
        try:
            host = urlsplit(value if "://" in value else f"//{value}").hostname
        except ValueError:
            return None
        return host or None

    def destination_allowed(self, *, value: str) -> bool:
        """Return True when the host of a literal destination matches ``allowed_destinations``."""
        host = self._host_of(value=value)
        return host is not None and any(fnmatch.fnmatchcase(host, pattern) for pattern in self.destinations)

    @classmethod
    def log_startup_diagnostics(cls) -> None:
        """Log the startup messages the deployment policy requires.

        Call once after providers are registered. Logs one ERROR naming
        ``secrets.vault.allowed_paths`` when a provider is registered and the
        setting is unset or empty (every reference will be ``not permitted``), one
        ERROR per entry that cannot be parsed, and one WARNING for ``*:**``.
        """
        providers = registered_provider_names()
        if not providers:
            return
        allowed_paths, _ = cls._read_settings()
        entries = [item for item in allowed_paths if isinstance(item, str)] if isinstance(allowed_paths, list) else []
        if not entries:
            logger.error(
                "Secret provider(s) registered (%s) but 'secrets.vault.allowed_paths' is not set: every vault:// "
                "reference will be rejected as 'not permitted'. Set it to the Vault paths flows may read, for "
                "example 'hashicorp:opensearch/**', or to '%s' to allow every path.",
                ", ".join(providers),
                ALLOW_ALL_ENTRY,
            )
            return
        for position, entry in enumerate(entries):
            if cls._parse_rule(entry=entry) is None:
                logger.error(
                    "Entry %d of 'secrets.vault.allowed_paths' is not of the form provider:glob[@operator.field] "
                    "and is ignored",
                    position,
                )
        if any(entry.strip() == ALLOW_ALL_ENTRY for entry in entries):
            logger.warning(
                "'secrets.vault.allowed_paths' contains '%s': any Vault path readable by the platform can be "
                "referenced by a flow",
                ALLOW_ALL_ENTRY,
            )


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class _Rejection(Exception):
    """A resolved value failed the type rule (internal)."""

    def __init__(self, *, category: SecretErrorCategory, reason: str) -> None:
        super().__init__(reason)
        self.category = category
        self.reason = reason


@dataclass(frozen=True)
class _Site:
    """One reference found in the configuration."""

    path: ConfigPath
    reference: SecretReference
    structured: bool


class SecretResolver:
    """Resolves the references in one node configuration. All methods are stateless."""

    @staticmethod
    def _new_correlation_id() -> str:
        return uuid.uuid4().hex[:12]

    # -- configuration walking ---------------------------------------------

    @staticmethod
    def _iter_strings(*, node: Any, path: ConfigPath = ()) -> Iterator[tuple[ConfigPath, str]]:
        """Yield ``(path, text)`` for every string leaf, in configuration order."""
        if isinstance(node, str):
            yield path, node
        elif isinstance(node, dict):
            for key, child in node.items():
                yield from SecretResolver._iter_strings(node=child, path=(*path, str(key)))
        elif isinstance(node, list):
            for index, child in enumerate(node):
                yield from SecretResolver._iter_strings(node=child, path=(*path, index))

    @staticmethod
    def _get_path(*, config: Mapping[str, Any], path: tuple[str, ...]) -> Any:
        """Return the value at a dict-only path, or None when any segment is absent."""
        current: Any = config
        for segment in path:
            if not isinstance(current, dict) or segment not in current:
                return None
            current = current[segment]
        return current

    @staticmethod
    def _copy_containers(*, node: Any) -> Any:
        """Copy dicts and lists recursively; leaves are shared (they are immutable)."""
        if isinstance(node, dict):
            return {key: SecretResolver._copy_containers(node=child) for key, child in node.items()}
        if isinstance(node, list):
            return [SecretResolver._copy_containers(node=child) for child in node]
        return node

    @staticmethod
    def _set_path(*, root: Any, path: ConfigPath, value: SecretValue) -> None:
        current = root
        for segment in path[:-1]:
            current = current[segment]
        current[path[-1]] = value

    # -- declarations --------------------------------------------------------

    @staticmethod
    def _declared_paths(*, metadata: Mapping[str, Any], config: Mapping[str, Any]) -> list[tuple[str, ...]]:
        """Return the secret-capable paths for this node, as segment tuples.

        Provider-scoped declarations apply only for the provider the node selects.
        A missing ``secret_fields`` key counts as no declaration.
        """
        providers: dict[str, str] = {}
        for selector in metadata.get(DECLARED_BY_PROVIDER_KEY, {}):
            selected = SecretResolver._get_path(config=config, path=tuple(selector.split(".")))
            if isinstance(selected, str):
                providers[selector] = selected
        return [tuple(field.split(".")) for field in effective_secret_fields(metadata=metadata, providers=providers)]

    @staticmethod
    def _is_declared(*, path: ConfigPath, declared: list[tuple[str, ...]]) -> bool:
        """Return True when ``path`` is covered by a declaration; a trailing ``*`` covers everything below."""
        text_path = tuple(str(segment) for segment in path)
        for field in declared:
            if field[-1] == "*":
                prefix = field[:-1]
                if len(text_path) > len(prefix) and text_path[: len(prefix)] == prefix:
                    return True
            elif text_path == field:
                return True
        return False

    # -- failure and outcome reporting --------------------------------------------

    @staticmethod
    def _report_outcome(
        *,
        node_name: str,
        operator: str,
        config_key: str,
        provider: str | None,
        outcome: str,
        correlation_id: str,
    ) -> None:
        """Seam for the resolution audit trail (task C.3).

        Called exactly once per reference that was attempted, with ``outcome`` set
        to ``resolved`` or to the failure category. Task C.3 emits the
        ``docpipe.audit`` record here; nothing is emitted yet, so adding it does
        not change any signature in this module.
        """
        from docpipe.utils.infrastructure.audit import emit_resolution_audit_record

        emit_resolution_audit_record(
            node_name=node_name,
            config_key=config_key,
            provider=provider,
            outcome=outcome,
            correlation_id=correlation_id,
        )

    @staticmethod
    def _fail(
        *,
        category: SecretErrorCategory,
        node_name: str,
        operator: str,
        path: ConfigPath,
        provider: str | None,
        correlation_id: str,
        reason: str,
        detail: str | None = None,
    ) -> SecretResolutionError:
        """Log the detail server-side and return the user-visible error. The caller raises it."""
        config_key = _display_path(path=path)
        safe_provider = _display(text=provider) if provider else None
        logger.warning(
            "Secret resolution failed [id %s]: node=%s operator=%s key=%s provider=%s category=%s reason=%s%s",
            correlation_id,
            node_name,
            operator,
            config_key,
            safe_provider or "-",
            category.value,
            reason,
            f" detail={detail}" if detail else "",
        )
        SecretResolver._report_outcome(
            node_name=node_name,
            operator=operator,
            config_key=config_key,
            provider=safe_provider,
            outcome=category.value,
            correlation_id=correlation_id,
        )
        return SecretResolutionError(
            category=category,
            config_key=config_key,
            provider=safe_provider,
            correlation_id=correlation_id,
            node_name=node_name,
        )

    # -- phase 1: checks that need no provider call --------------------------------

    @staticmethod
    def _classify(
        *,
        path: ConfigPath,
        text: str,
        operator: str,
        declared: list[tuple[str, ...]],
        policy: SecretPolicy,
    ) -> tuple[FindingKind | None, SecretReference | None]:
        """Apply grammar, declaration, registration, and path policy to one reference-looking string.

        Returns ``(None, None)`` when the text is not a reference at all, ``(None, reference)``
        when it passed every check, and ``(kind, reference_or_None)`` for the first failing
        check. No provider is called.
        """
        try:
            reference = parse_reference(value=text)
        except MalformedSecretReferenceError:
            return FindingKind.MALFORMED, None
        if reference is None:
            return None, None
        if not SecretResolver._is_declared(path=path, declared=declared):
            return FindingKind.FIELD_NOT_SECRET_CAPABLE, reference
        if get_provider(name=reference.provider) is None:
            return FindingKind.PROVIDER_NOT_REGISTERED, reference
        if not policy.permits(
            reference=reference, operator=operator, config_key=".".join(str(segment) for segment in path)
        ):
            return FindingKind.PATH_NOT_PERMITTED, reference
        return None, reference

    _FAILURES: Final[dict[FindingKind, tuple[SecretErrorCategory, str]]] = {
        FindingKind.MALFORMED: (SecretErrorCategory.MALFORMED_REFERENCE, "value is not exactly one valid reference"),
        FindingKind.FIELD_NOT_SECRET_CAPABLE: (
            SecretErrorCategory.NOT_PERMITTED,
            "field is not secret-capable for this operator",
        ),
        FindingKind.PROVIDER_NOT_REGISTERED: (
            SecretErrorCategory.PROVIDER_NOT_REGISTERED,
            "provider is not registered",
        ),
        FindingKind.PATH_NOT_PERMITTED: (
            SecretErrorCategory.NOT_PERMITTED,
            "reference is outside secrets.vault.allowed_paths",
        ),
        FindingKind.DESTINATION_NOT_PERMITTED: (
            SecretErrorCategory.NOT_PERMITTED,
            "destination is not a reference and its host is not in secrets.vault.allowed_destinations",
        ),
    }

    @staticmethod
    def _plan(
        *,
        node_name: str,
        operator: str,
        config: Mapping[str, Any],
        declared: list[tuple[str, ...]],
        policy: SecretPolicy,
        correlation_id: str,
    ) -> list[_Site]:
        """Find every reference and apply grammar, declaration, registration, and path policy to it."""
        sites: list[_Site] = []
        for path, text in SecretResolver._iter_strings(node=config):
            if not is_vault_reference(text):
                continue
            kind, reference = SecretResolver._classify(
                path=path, text=text, operator=operator, declared=declared, policy=policy
            )
            if kind is not None:
                category, reason = SecretResolver._FAILURES[kind]
                raise SecretResolver._fail(
                    category=category,
                    node_name=node_name,
                    operator=operator,
                    path=path,
                    provider=reference.provider if reference is not None else None,
                    correlation_id=correlation_id,
                    reason=reason,
                )
            if reference is None:
                continue
            sites.append(
                _Site(
                    path=path,
                    reference=reference,
                    structured=str(path[-1]) in STRUCTURED_FIELD_NAMES,
                )
            )
        return sites

    @staticmethod
    def _expand_environment(*, value: str) -> str | None:
        """Expand ``$VAR`` forms the way adapters do, so a ``${VAR:default}`` default cannot hide a host.

        Returns None when the variable is unset: the adapter fails on its own before connecting.
        """
        from docpipe.core.operators.operator_utils import resolve_env_var

        try:
            expanded = resolve_env_var(value)
        except ValueError:
            return None
        return expanded if isinstance(expanded, str) else None

    @staticmethod
    def _destination_violations(
        *,
        config: Mapping[str, Any],
        declared: list[tuple[str, ...]],
        policy: SecretPolicy,
    ) -> list[tuple[str, ...]]:
        """Return the declared destination fields whose literal host is not in ``allowed_destinations`` (D4b)."""
        violations: list[tuple[str, ...]] = []
        for field in declared:
            if field[-1] not in DESTINATION_FIELD_NAMES:
                continue
            value = SecretResolver._get_path(config=config, path=field)
            if not isinstance(value, str) or not value.strip() or is_vault_reference(value):
                continue
            literal = SecretResolver._expand_environment(value=value)
            if literal is None or not literal.strip() or policy.destination_allowed(value=literal):
                continue
            violations.append(field)
        return violations

    @staticmethod
    def _check_destinations(
        *,
        node_name: str,
        operator: str,
        config: Mapping[str, Any],
        declared: list[tuple[str, ...]],
        policy: SecretPolicy,
        provider: str,
        correlation_id: str,
    ) -> None:
        """Reject a literal destination that is not in ``allowed_destinations`` (design D4b)."""
        violations = SecretResolver._destination_violations(config=config, declared=declared, policy=policy)
        if violations:
            category, reason = SecretResolver._FAILURES[FindingKind.DESTINATION_NOT_PERMITTED]
            raise SecretResolver._fail(
                category=category,
                node_name=node_name,
                operator=operator,
                path=violations[0],
                provider=provider,
                correlation_id=correlation_id,
                reason=reason,
            )

    @staticmethod
    def inspect(*, operator_class: "type[AbstractOperator]", config: dict[str, Any]) -> list[ReferenceFinding]:
        """Report every reference problem in ``config`` without raising and without a provider call.

        Applies the phase-1 checks of :meth:`resolve` to all references (not only the first
        failure) and the destination rule when at least one reference passed them.
        Nothing is logged or audited: this is validation, not a resolution attempt.
        """
        if not has_vault_references(config):
            return []
        operator = str(getattr(operator_class, "short_name", "") or "")
        declared = SecretResolver._declared_paths(metadata=operator_class.get_metadata(), config=config)
        policy = SecretPolicy.load()
        findings: list[ReferenceFinding] = []
        passed = False
        for path, text in SecretResolver._iter_strings(node=config):
            if not is_vault_reference(text):
                continue
            kind, reference = SecretResolver._classify(
                path=path, text=text, operator=operator, declared=declared, policy=policy
            )
            if kind is not None:
                findings.append(
                    ReferenceFinding(
                        config_key=_display_path(path=path),
                        kind=kind,
                        provider=_display(text=reference.provider) if reference is not None else None,
                    )
                )
            elif reference is not None:
                passed = True
        if passed:
            findings.extend(
                ReferenceFinding(
                    config_key=_display_path(path=field), kind=FindingKind.DESTINATION_NOT_PERMITTED, provider=None
                )
                for field in SecretResolver._destination_violations(config=config, declared=declared, policy=policy)
            )
        return findings

    # -- phase 2: provider calls -----------------------------------------------------

    @staticmethod
    def _parse_json_container(*, text: str) -> dict[str, Any] | list[Any] | None:
        """Return the parsed object when ``text`` is a JSON object or array, otherwise None."""
        if not text.lstrip().startswith(("{", "[")):
            return None
        try:
            parsed = json.loads(text)
        except (ValueError, RecursionError):
            return None
        return parsed if isinstance(parsed, dict | list) else None

    @staticmethod
    def _to_secret_value(*, secret: Any, structured: bool) -> SecretValue:
        """Apply the type rule to a stored value and wrap it. Used exactly as stored, never trimmed."""
        if not isinstance(secret, str):
            raise _Rejection(category=SecretErrorCategory.VALUE_MUST_BE_STRING, reason="provider returned a non-string")
        if secret == "":  # nosec B105
            raise _Rejection(category=SecretErrorCategory.SECRET_UNAVAILABLE, reason="stored value is empty")
        container = SecretResolver._parse_json_container(text=secret)
        if container is None:
            return SecretValue(value=secret)
        if structured:
            return SecretValue(value=container)
        raise _Rejection(
            category=SecretErrorCategory.VALUE_MUST_BE_STRING,
            reason="stored value is a JSON object or array in a scalar field",
        )

    @staticmethod
    def _provider_failure(*, exc: Exception) -> tuple[SecretErrorCategory, str]:
        """Map a provider exception to a category and an internal reason.

        Missing path, missing key, permission denial, and an ambiguous multi-key secret
        all become ``secret unavailable`` so a flow author cannot probe which paths exist.
        """
        if isinstance(exc, ProviderUnreachableError | ConnectionError | TimeoutError):
            return SecretErrorCategory.VAULT_UNREACHABLE, "provider could not be reached"
        return SecretErrorCategory.SECRET_UNAVAILABLE, "provider could not return the secret"

    @staticmethod
    def resolve(*, node_name: str, operator_class: "type[AbstractOperator]", config: dict[str, Any]) -> dict[str, Any]:
        """Resolve the references in ``config`` for one node. See :func:`resolve_node_config`."""
        if not has_vault_references(config):
            return config

        correlation_id = SecretResolver._new_correlation_id()
        operator = str(getattr(operator_class, "short_name", "") or "")
        declared = SecretResolver._declared_paths(metadata=operator_class.get_metadata(), config=config)
        policy = SecretPolicy.load()

        sites = SecretResolver._plan(
            node_name=node_name,
            operator=operator,
            config=config,
            declared=declared,
            policy=policy,
            correlation_id=correlation_id,
        )
        if sites:
            SecretResolver._check_destinations(
                node_name=node_name,
                operator=operator,
                config=config,
                declared=declared,
                policy=policy,
                provider=sites[0].reference.provider,
                correlation_id=correlation_id,
            )

        resolved: list[tuple[_Site, SecretValue]] = []
        for site in sites:
            reference = site.reference
            fail: dict[str, Any] = {
                "node_name": node_name,
                "operator": operator,
                "path": site.path,
                "provider": reference.provider,
                "correlation_id": correlation_id,
            }
            provider = get_provider(name=reference.provider)
            if provider is None:
                raise SecretResolver._fail(
                    category=SecretErrorCategory.PROVIDER_NOT_REGISTERED,
                    reason="provider is not registered",
                    **fail,
                )
            try:
                secret = provider.get_secret(path=reference.path, key=reference.key)
            except Exception as exc:
                category, reason = SecretResolver._provider_failure(exc=exc)
                raise SecretResolver._fail(
                    category=category,
                    reason=reason,
                    detail=sanitize_exception(exc=exc, config_key=_display_path(path=site.path)),
                    **fail,
                ) from None
            try:
                value = SecretResolver._to_secret_value(secret=secret, structured=site.structured)
            except _Rejection as rejection:
                raise SecretResolver._fail(category=rejection.category, reason=rejection.reason, **fail) from None
            resolved.append((site, value))
            register_secret(value=value.reveal())
            SecretResolver._report_outcome(
                node_name=node_name,
                operator=operator,
                config_key=_display_path(path=site.path),
                provider=_display(text=reference.provider),
                outcome="resolved",
                correlation_id=correlation_id,
            )

        result: dict[str, Any] = SecretResolver._copy_containers(node=config)
        for site, value in resolved:
            SecretResolver._set_path(root=result, path=site.path, value=value)
        logger.debug("Resolved %d secret reference(s) for node %s (operator %s)", len(resolved), node_name, operator)
        return result


def resolve_node_config(
    *, node_name: str, operator_class: "type[AbstractOperator]", config: dict[str, Any]
) -> dict[str, Any]:
    """Resolve the ``vault://`` references in one node's configuration.

    Only the fields the operator declares secret-capable (``get_metadata()``) may
    hold a reference. The provider is called only after every reference in the
    node passed the grammar, declaration, registration, path-policy, and
    destination checks, and the first failure aborts the node.

    Args:
        node_name: Flow node name, for the server-side log.
        operator_class: Operator class whose ``get_metadata()`` carries the declarations.
        config: The node's own configuration. It is not modified.

    Returns:
        ``config`` itself when it contains no ``vault://`` text (no provider is called
        and no declaration is read). Otherwise a new configuration in which each
        reference is replaced by a :class:`SecretValue`; other values are shared as is.
        Environment forms (``$VAR``) are not expanded here.

    Raises:
        SecretResolutionError: With a fixed category, the config key, the provider, and a
            correlation identifier. The detail is in the server-side log.
    """
    return SecretResolver.resolve(node_name=node_name, operator_class=operator_class, config=config)


def inspect_node_references(
    *, operator_class: "type[AbstractOperator]", config: dict[str, Any]
) -> list[ReferenceFinding]:
    """List the problems with the ``vault://`` references in one node's configuration.

    Used by flow validation. It checks grammar (malformed and embedded values), declaration,
    provider registration, ``secrets.vault.allowed_paths``, and destination binding. It never
    contacts a provider, never raises for a bad reference, and returns key paths only.
    """
    return SecretResolver.inspect(operator_class=operator_class, config=config)
