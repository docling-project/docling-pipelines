"""Secret provider abstraction and reference resolver.

This module provides:
- SecretProvider: Abstract base class for vault/secret manager integrations.
- SecretReference: Parsed representation of a vault:// URI.
- resolve_value(): Recursively resolves vault references in config dicts/lists.
- register_provider(): Registers a provider instance by name.
- parse_reference(): Parses a vault:// URI string.

Vault reference format:
    vault://<provider>/<path>#<key>

Examples:
    vault://hashicorp/database/postgres#password
    vault://hashicorp/opensearch/credentials#username
"""

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from docpipe.exceptions.docpipe_exceptions import ConfigurationError
from docpipe.utils.infrastructure import DocpipeConfigLoader
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

# Pattern: vault://provider/path/to/secret#key
_VAULT_REF_PATTERN = re.compile(r"^vault://([^/]+)/(.+?)(?:#(.+))?$")

# Global registry of providers
_providers: dict[str, "SecretProvider"] = {}


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


def parse_reference(value: str) -> SecretReference | None:
    """Parse a vault:// reference string.

    Args:
        value: A string that may be a vault reference.

    Returns:
        SecretReference if the string matches vault:// format, None otherwise.
    """
    match = _VAULT_REF_PATTERN.match(value)
    if not match:
        return None
    return SecretReference(
        provider=match.group(1),
        path=match.group(2),
        key=match.group(3),
    )


def parse_vault_reference(ref: str) -> tuple[str, str, str | None]:
    """Parse a vault:// URI into (provider_name, secret_path, secret_key).

    Args:
        ref: The vault reference string.

    Returns:
        Tuple of (provider_name, path, optional_key).

    Raises:
        ValueError: If the string is not a valid vault reference.
    """
    parsed = parse_reference(ref)
    if parsed is None:
        raise ValueError(f"Invalid vault reference: '{ref}'")
    return parsed.provider, parsed.path, parsed.key


def is_vault_reference(value: Any) -> bool:
    """Check if a value is a vault:// reference string.

    Args:
        value: Any value to check.

    Returns:
        True if the value is a string starting with 'vault://'.
    """
    return isinstance(value, str) and value.startswith("vault://")


def has_vault_references(value: Any) -> bool:
    """Return True if *value* contains any vault:// reference, anywhere in its structure.

    This is a fast detection pass — it returns as soon as it finds one reference
    without rebuilding any data.  Used to short-circuit ``resolve_value`` when the
    config contains no vault references at all, which is the common case.

    Args:
        value: A string, dict, list, or any other value.

    Returns:
        True if any string in the structure starts with ``vault://``.
    """
    if isinstance(value, str):
        return value.startswith("vault://")
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
    """Resolve a single vault reference string if applicable, or return it unchanged."""
    ref = parse_reference(ref_string)
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
