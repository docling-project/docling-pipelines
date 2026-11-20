# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Characterization tests for secret resolution edge cases and leaks on current main.

These tests document and pin existing behavior/gaps that subsequent tasks close:
1. Malformed vault:// strings fail closed (flipped by A.5; previously returned as literals).
2. resolve_env_var on resolved secrets starting with '$' leaks the secret minus '$' in ValueError.
3. resolve_env_var on uppercase resolved secrets containing '_' overwrites the secret if an env var exists.
"""

import pytest

from docpipe.core.operators.operator_utils import resolve_env_var
from docpipe.exceptions.docpipe_exceptions import ConfigurationError, ExternalServiceError
from docpipe.integrations.secrets.secret_provider import (
    MalformedSecretReferenceError,
    SecretProvider,
    clear_providers,
    register_provider,
    resolve_value,
)


class FakeCharacterizationProvider(SecretProvider):
    """Test SecretProvider for characterization tests."""

    def __init__(self, *, secrets: dict[str, dict[str, str]]) -> None:
        self._secrets = secrets

    def authenticate(self) -> None:
        pass

    def get_secret(self, *, path: str, key: str | None = None) -> str:
        data = self._secrets.get(path)
        if data is None:
            raise ExternalServiceError(f"Secret not found: {path}")
        if key:
            if key not in data:
                raise ExternalServiceError(f"Key '{key}' not found at path '{path}'")
            return data[key]
        if len(data) == 1:
            return next(iter(data.values()))
        raise ConfigurationError("Multiple keys, specify one")

    def is_available(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _cleanup_providers():
    """Ensure providers are cleared before and after tests."""
    clear_providers()
    yield
    clear_providers()


class TestSecretResolutionCharacterization:
    """Characterization tests documenting existing secret resolution behaviors."""

    def test_malformed_vault_reference_is_rejected_not_returned_as_literal(self) -> None:
        """Flipped by A.5: malformed vault:// strings fail closed instead of being used as literals."""
        provider = FakeCharacterizationProvider(secrets={"path/to": {"key": "secret123"}})
        register_provider(name="fake", provider=provider)

        malformed_refs = [
            "vault://",
            "vault://fake",
            "vault://fake/",
            "vault://invalid",
            "Bearer vault://fake/path/to#key",
            "vault://fake/path/../to#key",
        ]
        for ref in malformed_refs:
            with pytest.raises(MalformedSecretReferenceError) as exc_info:
                resolve_value(ref)
            # Fixed message: nothing from the offending value is echoed.
            assert str(exc_info.value) == str(MalformedSecretReferenceError())

    def test_resolve_env_var_leaks_dollar_prefixed_secret(self) -> None:
        """On current main, resolve_env_var on a secret starting with '$' raises ValueError leaking the secret."""
        canary_secret = "$ecret_Value_98765"
        provider = FakeCharacterizationProvider(secrets={"test/path": {"password": canary_secret}})
        register_provider(name="fake", provider=provider)

        resolved_secret = resolve_value("vault://fake/test/path#password")
        assert resolved_secret == canary_secret

        # If resolve_env_var is called on the resolved value (as done in multiple adapters)
        # It treats the secret as an env var name and leaks it in the ValueError message:
        with pytest.raises(ValueError) as exc_info:
            resolve_env_var(resolved_secret)

        assert "Environment variable ecret_Value_98765 is not set" in str(exc_info.value)
        assert "ecret_Value_98765" in str(exc_info.value)

    def test_resolve_env_var_overwrites_uppercase_secret_with_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """On current main, resolve_env_var overwrites uppercase secret with underscore if env var exists."""
        canary_secret = "DATABASE_PASSWORD"  # pragma: allowlist secret
        provider = FakeCharacterizationProvider(secrets={"test/path": {"key": canary_secret}})
        register_provider(name="fake", provider=provider)

        resolved_secret = resolve_value("vault://fake/test/path#key")
        assert resolved_secret == canary_secret

        # Set environment variable with the same name as the secret value
        monkeypatch.setenv("DATABASE_PASSWORD", "ENV_OVERWRITE_VALUE")

        # Calling resolve_env_var on resolved secret replaces the secret with the env var value
        overwritten = resolve_env_var(resolved_secret)
        assert overwritten == "ENV_OVERWRITE_VALUE"
