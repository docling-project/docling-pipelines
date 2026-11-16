# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Secret provider abstraction and reference resolver.

This module provides:
- SecretProvider: Abstract base class for vault/secret manager integrations.
- SecretReference: Parsed representation of a vault:// URI.
- resolve_value(): Recursively resolves vault references in config dicts/lists.
- register_provider(): Registers a provider instance by name.
- parse_reference(): Parses a vault:// URI string (fails closed on malformed input).

Vault reference format:
    vault://<provider>/<path>#<key>

A value is a reference only when the entire string is exactly one valid
reference. A string that contains ``vault://`` but is not exactly one valid
reference is rejected with ``MalformedSecretReferenceError`` and is never used
as a literal value.

Examples:
    vault://hashicorp/database/postgres#password
    vault://hashicorp/opensearch/credentials#username
"""

import json
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from docpipe.exceptions.docpipe_exceptions import ConfigurationError, ExternalServiceError
from docpipe.utils.infrastructure import DocpipeConfigLoader
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

_REFERENCE_SCHEME = "vault://"

# Syntax limit: a reference must not exceed this many characters.
_MAX_REFERENCE_LENGTH = 1024

# Global registry of providers
_providers: dict[str, "SecretProvider"] = {}


class MalformedSecretReferenceError(ConfigurationError):
    """A value containing ``vault://`` is not exactly one valid reference.

    The message is fixed and never includes the offending value, so a
    mistyped or partially pasted credential is not echoed into logs, API
    responses, or job messages.
    """

    def __init__(self) -> None:
        super().__init__(
            "malformed reference: a value containing 'vault://' must be exactly one "
            "valid vault://<provider>/<path>[#<key>] reference"
        )


class ProviderUnreachableError(ExternalServiceError):
    """The secret backend could not be reached or authenticated against.

    Raised for network, TLS, timeout, platform-login, rate-limit, and server-side
    failures, so the shared resolver can report ``vault unreachable`` and keep
    it apart from a missing path or key, a denial, or an ambiguous secret, which
    are all reported as ``secret unavailable``. The message must not carry the
    backend address, a path, or a response body.
    """


@dataclass(frozen=True)
class SecretReference:
    """Parsed vault reference URI.

    Attributes:
        provider: Name of the registered secret provider (e.g., "hashicorp").
        path: Path to the secret within the vault (e.g., "database/postgres").
        key: Optional key within a multi-value secret (e.g., "password").
    """

    provider: str
    path: str
    key: str | None = None


class SecretProvider(ABC):
    """Abstract base class for secret/vault providers.

    Implementations must handle:
    - Authentication (with automatic re-auth on token expiry)
    - Secret retrieval by path and optional key
    - Availability check
    """

    @abstractmethod
    def authenticate(self) -> None:
        """Authenticate with the vault backend.

        Raises:
            ConfigurationError: If credentials or configuration are invalid.
            ExternalServiceError: If the vault backend is unreachable or rejects the request.
        """

    @abstractmethod
    def get_secret(self, *, path: str, key: str | None = None) -> str:
        """Retrieve a secret value from the vault.

        Args:
            path: Path to the secret within the vault.
            key: Optional specific key within a multi-value secret.

        Returns:
            The secret value as a string.

        Raises:
            ProviderUnreachableError: If the backend cannot be reached or authenticated against
                (network, TLS, timeout, login, rate limit, server error). The shared resolver
                reports this as ``vault unreachable``.
            ExternalServiceError: If the key does not exist at the path or the secret cannot be retrieved.
            ConfigurationError: If no key is specified and the secret has multiple keys.
        """

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the vault provider is reachable and properly configured.

        Returns:
            True if the provider is available, False otherwise.
        """


def register_provider(*, name: str, provider: SecretProvider) -> None:
    """Register a secret provider instance by name.

    Args:
        name: Provider name used in vault:// URIs (e.g., "hashicorp").
        provider: An instance implementing SecretProvider.
    """
    _providers[name] = provider
    logger.info("Registered secret provider: %s", name)


def get_provider(*, name: str) -> SecretProvider | None:
    """Get a registered provider by name.

    Args:
        name: Provider name.

    Returns:
        The provider instance, or None if not registered.
    """
    return _providers.get(name)


def registered_provider_names() -> tuple[str, ...]:
    """Return the names of all registered providers."""
    return tuple(_providers)


def _is_unsafe_reference_char(char: str) -> bool:
    """Return True for whitespace and control characters, which a reference may not contain."""
    return char.isspace() or unicodedata.category(char) == "Cc"


def parse_reference(*, value: str) -> SecretReference | None:
    """Parse a vault:// reference string, failing closed on malformed input.

    The whole string must be exactly one ``vault://<provider>/<path>[#<key>]``
    with a non-empty provider, a non-empty path, and a non-empty key when ``#``
    is present. The reference must not contain whitespace or control
    characters, ``.`` / ``..`` / empty path segments, or exceed 1024 characters,
    and must not be embedded in a larger string.

    Args:
        value: A string that may be a vault reference.

    Returns:
        SecretReference if the string is exactly one valid reference, or None
        if the string does not contain ``vault://`` at all (an ordinary literal).

    Raises:
        MalformedSecretReferenceError: If the string contains ``vault://`` but is
            not exactly one valid reference. The error never echoes the value.
    """
    if _REFERENCE_SCHEME not in value:
        return None

    if (
        not value.startswith(_REFERENCE_SCHEME)
        or len(value) > _MAX_REFERENCE_LENGTH
        or value.count(_REFERENCE_SCHEME) != 1
        or any(_is_unsafe_reference_char(char) for char in value)
    ):
        raise MalformedSecretReferenceError

    body, has_key, key = value[len(_REFERENCE_SCHEME) :].partition("#")
    if has_key and (not key or "#" in key):
        raise MalformedSecretReferenceError

    provider, has_path, path = body.partition("/")
    if not provider or not has_path or any(segment in ("", ".", "..") for segment in path.split("/")):
        raise MalformedSecretReferenceError

    return SecretReference(provider=provider, path=path, key=key if has_key else None)


def parse_vault_reference(ref: str) -> tuple[str, str, str | None]:
    """Parse a vault:// URI into (provider_name, secret_path, secret_key).

    Args:
        ref: The vault reference string.

    Returns:
        Tuple of (provider_name, path, optional_key).

    Raises:
        ValueError: If the string is not a valid vault reference. The message
            never includes the input.
    """
    try:
        parsed = parse_reference(value=ref)
    except MalformedSecretReferenceError:
        raise ValueError("Invalid vault reference") from None
    if parsed is None:
        raise ValueError("Invalid vault reference")
    return parsed.provider, parsed.path, parsed.key


def is_vault_reference(value: Any) -> bool:
    """Check if a value is, or attempts to be, a vault:// reference string.

    Detection is by substring so that embedded and malformed references reach
    the parser (and are rejected) instead of being treated as literals.

    Args:
        value: Any value to check.

    Returns:
        True if the value is a string containing 'vault://'.
    """
    return isinstance(value, str) and _REFERENCE_SCHEME in value


def has_vault_references(value: Any) -> bool:
    """Return True if *value* contains any vault:// reference, anywhere in its structure.

    This is a fast detection pass — it returns as soon as it finds one reference
    without rebuilding any data.  Used to short-circuit ``resolve_value`` when the
    config contains no vault references at all, which is the common case.

    Args:
        value: A string, dict, list, or any other value.

    Returns:
        True if any string in the structure contains ``vault://``.
    """
    if isinstance(value, str):
        return _REFERENCE_SCHEME in value
    if isinstance(value, dict):
        return any(has_vault_references(v) for v in value.values())
    if isinstance(value, list):
        return any(has_vault_references(item) for item in value)
    return False


def _parse_secret_json_if_applicable(secret: Any) -> Any:
    """Parse JSON string back to native Python object if secret is JSON-formatted."""
    if isinstance(secret, str):
        stripped = secret.strip()
        if stripped.startswith(("{", "[")):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                pass
    return secret


def _resolve_string_vault_ref(*, ref_string: str) -> Any:
    """Resolve a single vault reference string, or return a non-reference string unchanged.

    Raises:
        MalformedSecretReferenceError: If the string contains ``vault://`` but is
            not exactly one valid reference. It is never returned as a literal.
    """
    ref = parse_reference(value=ref_string)
    if ref is None:
        return ref_string

    provider = _providers.get(ref.provider)
    if provider is None:
        raise ConfigurationError(
            f"Secret provider '{ref.provider}' not registered. "
            "Vault initialization failed at startup — check logs for details. "
            "Common causes: VAULT_ROLE_ID/VAULT_SECRET_ID not set, "
            "or Vault unreachable at VAULT_ADDR. "
            "Enable debug logging with DS_LOG_LEVEL=DEBUG for full detail."
        )

    logger.debug("Resolving vault reference: provider=%s, path=%s, key=%s", ref.provider, ref.path, ref.key)
    secret = provider.get_secret(path=ref.path, key=ref.key)
    return _parse_secret_json_if_applicable(secret)


def resolve_value(value: Any) -> Any:
    """Resolve vault references in a value, recursively.

    If the value is a vault:// reference string, fetches the secret from
    the registered provider. Works recursively on dicts and lists.
    Non-reference values are returned unchanged.

    Args:
        value: A string, dict, list, or any other value.

    Returns:
        The resolved value (secret fetched from vault, or original value).

    Raises:
        MalformedSecretReferenceError: If a string contains ``vault://`` but is not exactly
            one valid reference (truncated, embedded, traversal, over-length, ...).
        ConfigurationError: If the provider referenced in the URI is not registered, or the
            secret path has multiple keys and none is specified.
        ExternalServiceError: If the key does not exist at the vault path or the secret
            cannot be retrieved from the backend.
    """
    if isinstance(value, str):
        return _resolve_string_vault_ref(ref_string=value)

    if isinstance(value, dict):
        return {k: resolve_value(v) for k, v in value.items()}

    if isinstance(value, list):
        return [resolve_value(item) for item in value]

    return value


def clear_providers() -> None:
    """Remove all registered providers. Primarily for testing."""
    _providers.clear()
    DocpipeConfigLoader.reset()
