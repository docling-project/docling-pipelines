# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Secret-capable field declarations for operators (design D2).

An operator declares which of its configuration keys may hold a ``vault://``
reference through ``get_metadata()``:

* ``secret_fields``: dotted key paths (from the node ``config`` root) that are
  secret-capable for every provider. A trailing ``.*`` covers every key of a
  dict-valued config such as ``credentials``.
* ``secret_fields_by_provider``: ``{selector_key: {provider: [paths]}}``, the
  same full dotted paths scoped to one provider, for operators whose providers
  use the same key name for different things (ingest, storage, vectordb).
  ``selector_key`` is the config key that selects the provider, for example
  ``provider``, ``pii_provider`` or ``destination_config.provider``.
* ``no_references``: credential-looking keys that deliberately do not accept
  references.

Provider-specific declarations live on each adapter config class as the
``SECRET_FIELDS`` and ``NO_REFERENCES`` class variables, so a new provider
cannot declare a field for a different provider's adapter.
``SECRET_FIELD_ALIASES`` lists legacy key names the adapter still reads that
are not model fields (for example Box ``credentials_json_path``).

The ``sensitive`` schema flag is a floor: a key tagged ``sensitive`` is
secret-capable without a separate declaration (see
:func:`effective_secret_fields`).

Naming fields (index and collection names, destination paths, key prefixes,
filters, file names) are never declarable. They locate something written at an
external system, so resolving a secret into one would write the secret to a
place the flow author can read.
"""

import re
from collections.abc import Mapping
from typing import Any

DECLARED_FIELDS_KEY = "secret_fields"
DECLARED_BY_PROVIDER_KEY = "secret_fields_by_provider"
NO_REFERENCES_KEY = "no_references"

SENSITIVE_FLAG = "sensitive"

# Field names (last path segment) that name or locate a write target. Declaring
# one of these as secret-capable is a programming error.
NAMING_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "index_name",
        "collection_name",
        "path",
        "paths",
        "root_path",
        "folder_path",
        "file_path",
        "folder_id",
        "file_id",
        "prefix",
        "key_prefix",
        "file_name",
        "file_extensions",
        "include_filter",
        "exclude_filter",
        "exclude_patterns",
    }
)

# Field names (last path segment) that choose where a credential is sent. When
# any field of a node resolves from a secret provider, the shared resolver binds
# these to ``secrets.vault.allowed_destinations`` (design D4b).
DESTINATION_FIELD_NAMES: frozenset[str] = frozenset({"endpoint_url", "host", "uri", "api_base", "url", "base_url"})

# Field names (last path segment) that hold a JSON document. A resolved value
# for one of these is parsed once by the resolver instead of being rejected as
# "not a string".
STRUCTURED_FIELD_NAMES: frozenset[str] = frozenset({"credentials_json", "service_account_json"})

# Credential-looking names from the spec: password, *_key, *_secret, *_token,
# credentials*, plus the bare names key, secret, and token.
_CREDENTIAL_NAME = re.compile(r"(^|_)(password|key|secret|token)$|^credentials")


def is_credential_looking(*, name: str) -> bool:
    """Return True when a config key is named like a credential."""
    return _CREDENTIAL_NAME.search(name) is not None


def _class_names(*, config_cls: type, attribute: str) -> list[str]:
    """Return and validate the names a config class declares under ``attribute``."""
    declared: tuple[str, ...] = getattr(config_cls, attribute, ())
    known = set(getattr(config_cls, "model_fields", {})) | set(getattr(config_cls, "SECRET_FIELD_ALIASES", ()))
    for name in declared:
        if attribute == "SECRET_FIELDS" and name in NAMING_FIELD_NAMES:
            msg = f"{config_cls.__name__}.{attribute}: naming field '{name}' cannot be secret-capable"
            raise ValueError(msg)
        if name.split(".", 1)[0] not in known:
            msg = f"{config_cls.__name__}.{attribute}: '{name}' is not a field or documented alias of the configuration class"
            raise ValueError(msg)
    return list(declared)


def _join(*, prefix: str, name: str) -> str:
    """Join a dotted prefix and a key name."""
    return f"{prefix}.{name}" if prefix else name


def provider_secret_fields(*, config_cls: type, provider_schema: Mapping[str, Any], prefix: str) -> list[str]:
    """Return the dotted secret-capable paths for one provider configuration class.

    The result is the class's ``SECRET_FIELDS`` plus every property the schema
    tags ``sensitive`` (the floor), minus the class's ``NO_REFERENCES``.

    Args:
        config_cls: Pydantic configuration class carrying ``SECRET_FIELDS`` and
            optionally ``NO_REFERENCES``.
        provider_schema: The class's schema in docpipe vocabulary, as produced
            by ``OperatorUtils.model_schema_to_docpipe``.
        prefix: Dotted path of the config key holding this class's fields,
            for example ``provider_config``.

    Raises:
        ValueError: A declared name is not a field of the class, or is a
            naming field.
    """
    names = set(_class_names(config_cls=config_cls, attribute="SECRET_FIELDS"))
    for name, spec in (provider_schema.get("properties") or {}).items():
        if isinstance(spec, Mapping) and spec.get(SENSITIVE_FLAG) is True:
            names.add(name)
    names -= set(_class_names(config_cls=config_cls, attribute="NO_REFERENCES"))
    return sorted(_join(prefix=prefix, name=name) for name in names)


def build_provider_secret_fields(
    *,
    selector: str,
    prefix: str,
    classes: Mapping[str, type],
) -> dict[str, dict[str, list[str]]]:
    """Build a ``secret_fields_by_provider`` entry for one provider selector.

    Args:
        selector: Dotted config key that selects the provider, for example
            ``provider`` or ``destination_config.provider``.
        prefix: Dotted config key holding the provider's fields, for example
            ``provider_config``.
        classes: Provider name to configuration class. The ``sensitive`` floor
            is derived from each class's schema.
    """
    from docpipe.core.operators.operator_utils import OperatorUtils

    return {
        selector: {
            name: provider_secret_fields(
                config_cls=cls,
                provider_schema=OperatorUtils.model_schema_to_docpipe(schema=cls.model_json_schema()),  # type: ignore[attr-defined]
                prefix=prefix,
            )
            for name, cls in classes.items()
        }
    }


def provider_no_references(*, config_cls: type, prefix: str) -> list[str]:
    """Return the dotted paths a provider configuration class marks as taking no references."""
    names = _class_names(config_cls=config_cls, attribute="NO_REFERENCES")
    return sorted(_join(prefix=prefix, name=name) for name in names)


def _sensitive_paths(*, attributes: Mapping[str, Any], prefix: str = "") -> list[str]:
    """Return the dotted paths of every attribute tagged ``sensitive``, recursing into ``properties``."""
    paths: list[str] = []
    for key, spec in attributes.items():
        if not isinstance(spec, Mapping):
            continue
        path = _join(prefix=prefix, name=key)
        if spec.get(SENSITIVE_FLAG) is True:
            paths.append(path)
        nested = spec.get("properties")
        if isinstance(nested, Mapping):
            paths.extend(_sensitive_paths(attributes=nested, prefix=path))
    return paths


def effective_secret_fields(*, metadata: Mapping[str, Any], providers: Mapping[str, str] | None = None) -> list[str]:
    """Return every config path that may hold a reference for this operator.

    The result is the union of the operator-wide ``secret_fields``, the
    ``secret_fields_by_provider`` entries for the selected providers, and the
    ``sensitive`` floor derived from ``attributes``. Paths in ``no_references``
    are removed from the floor.

    Args:
        metadata: The operator's ``get_metadata()`` result.
        providers: Selected provider per selector key, for example
            ``{"provider": "s3"}``.
    """
    result: set[str] = set(metadata.get(DECLARED_FIELDS_KEY, []))
    by_provider: Mapping[str, Mapping[str, list[str]]] = metadata.get(DECLARED_BY_PROVIDER_KEY, {})
    for selector, provider in (providers or {}).items():
        result.update(by_provider.get(selector, {}).get(provider, []))
    blocked = set(metadata.get(NO_REFERENCES_KEY, []))
    result.update(p for p in _sensitive_paths(attributes=metadata.get("attributes", {})) if p not in blocked)
    return sorted(result)


def is_covered(*, path: str, fields: list[str]) -> bool:
    """Return True when a dotted config path is covered by a declaration.

    A declaration ending in ``.*`` covers every key below that object.
    """
    for field in fields:
        if field == path:
            return True
        if field.endswith(".*") and path.startswith(field[:-1]):
            return True
    return False
