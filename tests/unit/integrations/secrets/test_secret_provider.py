# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for SecretProvider base, reference parsing, and resolve_value."""

import pytest

from docpipe.exceptions.docpipe_exceptions import ConfigurationError, ExternalServiceError
from docpipe.integrations.secrets.secret_provider import (
    MalformedSecretReferenceError,
    SecretProvider,
    SecretReference,
    clear_providers,
    has_vault_references,
    is_vault_reference,
    parse_reference,
    parse_vault_reference,
    register_provider,
    resolve_value,
)


class FakeProvider(SecretProvider):
    """Test implementation of SecretProvider."""

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
    """Ensure providers are cleared between tests."""
    clear_providers()
    yield
    clear_providers()


class TestParseReference:
    """Tests for parse_reference() - strict grammar, fail closed."""

    def test_valid_reference_with_key(self):
        ref = parse_reference(value="vault://hashicorp/database/postgres#password")
        assert ref == SecretReference(provider="hashicorp", path="database/postgres", key="password")

    def test_valid_reference_without_key(self):
        ref = parse_reference(value="vault://hashicorp/api/token")
        assert ref == SecretReference(provider="hashicorp", path="api/token", key=None)

    def test_valid_reference_deep_path(self):
        ref = parse_reference(value="vault://hashicorp/a/b/c/d#mykey")
        assert ref == SecretReference(provider="hashicorp", path="a/b/c/d", key="mykey")

    def test_non_vault_value_returns_none(self):
        assert parse_reference(value="just-a-string") is None
        assert parse_reference(value="") is None
        assert parse_reference(value="http://example.com") is None
        assert parse_reference(value="vault:/hashicorp/x") is None

    def test_different_provider(self):
        ref = parse_reference(value="vault://cyberark/safe/object#Content")
        assert ref == SecretReference(provider="cyberark", path="safe/object", key="Content")

    @pytest.mark.parametrize(
        "value",
        [
            "vault://",
            "vault://hashicorp",
            "vault://hashicorp/",
            "vault:///path/only",
            "vault://hashicorp/path#",
            "vault://invalid",
        ],
    )
    def test_truncated_reference_rejected(self, value):
        with pytest.raises(MalformedSecretReferenceError):
            parse_reference(value=value)

    @pytest.mark.parametrize(
        "value",
        [
            "Bearer vault://hashicorp/api#token",
            "https://host/?k=vault://hashicorp/api#token",
            " vault://hashicorp/api#token",
            "vault://hashicorp/api#token vault://hashicorp/other#token",
            "vault://hashicorp/api#tokenvault://hashicorp/other#token",
            "xvault://hashicorp/api#token",
        ],
    )
    def test_embedded_reference_rejected(self, value):
        with pytest.raises(MalformedSecretReferenceError):
            parse_reference(value=value)

    @pytest.mark.parametrize(
        "value",
        [
            "vault://hashicorp/team-a/../team-b/db#password",
            "vault://hashicorp/../db#password",
            "vault://hashicorp/./db#password",
            "vault://hashicorp/db/..#password",
            "vault://hashicorp/db//creds#password",
            "vault://hashicorp//db#password",
            "vault://hashicorp/db/#password",
        ],
    )
    def test_traversal_and_empty_segments_rejected(self, value):
        with pytest.raises(MalformedSecretReferenceError):
            parse_reference(value=value)

    @pytest.mark.parametrize(
        "value",
        [
            "vault://hashicorp/db creds#password",
            "vault://hashicorp/db\t#password",
            "vault://hashicorp/db\n#password",
            "vault://hashicorp/db\r\n",
            "vault://hashicorp/db\x00#password",
            "vault://hashicorp/db\x7f#password",
            "vault://hashicorp/db#pass word",
            "vault://hashicorp/db\u00a0x#password",
            "vault://hashicorp/db#password ",
        ],
    )
    def test_whitespace_and_control_characters_rejected(self, value):
        with pytest.raises(MalformedSecretReferenceError):
            parse_reference(value=value)

    def test_second_key_separator_rejected(self):
        with pytest.raises(MalformedSecretReferenceError):
            parse_reference(value="vault://hashicorp/db#a#b")

    def test_length_limit(self):
        prefix = "vault://hashicorp/"
        at_limit = prefix + "a" * (1024 - len(prefix))
        assert parse_reference(value=at_limit) is not None
        with pytest.raises(MalformedSecretReferenceError):
            parse_reference(value=at_limit + "a")

    def test_error_never_echoes_value(self):
        canary = "CANARY-typo-secret-91d2"  # pragma: allowlist secret
        with pytest.raises(MalformedSecretReferenceError) as exc_info:
            parse_reference(value=f"vault://hashicorp/../{canary}")
        assert canary not in str(exc_info.value)
        assert "hashicorp" not in str(exc_info.value)
        assert exc_info.value.__cause__ is None

    def test_malformed_error_is_a_configuration_error(self):
        assert issubclass(MalformedSecretReferenceError, ConfigurationError)

    def test_positional_value_is_not_accepted(self):
        with pytest.raises(TypeError):
            parse_reference("vault://hashicorp/api/token")  # type: ignore[misc]


class TestParseVaultReference:
    """Tests for the tuple-returning wrapper."""

    def test_valid(self):
        assert parse_vault_reference("vault://hashicorp/a/b#k") == ("hashicorp", "a/b", "k")

    @pytest.mark.parametrize("value", ["plain", "vault://", "vault://hashicorp/../x", "Bearer vault://h/p#k"])
    def test_invalid_raises_value_error_without_echo(self, value):
        with pytest.raises(ValueError, match="Invalid vault reference") as exc_info:
            parse_vault_reference(value)
        assert str(exc_info.value) == "Invalid vault reference"
        assert exc_info.value.__cause__ is None


class TestIsVaultReference:
    """Tests for is_vault_reference()."""

    def test_vault_reference(self):
        assert is_vault_reference("vault://hashicorp/path#key") is True

    def test_embedded_or_malformed_values_are_detected_so_the_parser_rejects_them(self):
        assert is_vault_reference("Bearer vault://hashicorp/api#token") is True
        assert is_vault_reference("vault://") is True

    def test_not_vault_reference(self):
        assert is_vault_reference("plain-value") is False
        assert is_vault_reference(123) is False
        assert is_vault_reference(None) is False
        assert is_vault_reference({"key": "value"}) is False


class TestRegisterProvider:
    """Tests for register_provider()."""

    def test_register_and_use(self):
        provider = FakeProvider(secrets={"test/path": {"key": "secret_value"}})
        register_provider(name="fake", provider=provider)

        result = resolve_value("vault://fake/test/path#key")
        assert result == "secret_value"


class TestResolveValue:
    """Tests for resolve_value()."""

    def test_non_vault_string_unchanged(self):
        assert resolve_value("hello") == "hello"
        assert resolve_value("") == ""

    def test_non_string_types_unchanged(self):
        assert resolve_value(42) == 42
        assert resolve_value(3.14) == 3.14
        assert resolve_value(True) is True
        assert resolve_value(None) is None

    def test_vault_reference_resolved(self):
        provider = FakeProvider(secrets={"db/creds": {"user": "admin", "pass": "s3cret"}})
        register_provider(name="hashicorp", provider=provider)

        assert resolve_value("vault://hashicorp/db/creds#user") == "admin"
        assert resolve_value("vault://hashicorp/db/creds#pass") == "s3cret"

    def test_dict_with_mixed_values(self):
        provider = FakeProvider(secrets={"db/creds": {"password": "vault_pass"}})
        register_provider(name="hashicorp", provider=provider)

        config = {
            "host": "localhost",
            "port": 5432,
            "password": "vault://hashicorp/db/creds#password",  # pragma: allowlist secret
            "ssl": True,
        }

        resolved = resolve_value(config)
        assert resolved == {
            "host": "localhost",
            "port": 5432,
            "password": "vault_pass",  # pragma: allowlist secret
            "ssl": True,
        }

    def test_list_with_vault_references(self):
        provider = FakeProvider(
            secrets={
                "keys/api1": {"value": "key1"},
                "keys/api2": {"value": "key2"},
            }
        )
        register_provider(name="hashicorp", provider=provider)

        values = [
            "vault://hashicorp/keys/api1#value",
            "plain_value",
            "vault://hashicorp/keys/api2#value",
        ]

        resolved = resolve_value(values)
        assert resolved == ["key1", "plain_value", "key2"]

    def test_nested_dict_resolution(self):
        provider = FakeProvider(secrets={"opensearch/auth": {"password": "os_pass"}})
        register_provider(name="hashicorp", provider=provider)

        config = {
            "provider_config": {
                "host": "localhost",
                "password": "vault://hashicorp/opensearch/auth#password",  # pragma: allowlist secret
            }
        }

        resolved = resolve_value(config)
        assert resolved["provider_config"]["password"] == "os_pass"  # pragma: allowlist secret
        assert resolved["provider_config"]["host"] == "localhost"

    def test_unregistered_provider_raises_configuration_error(self):
        with pytest.raises(ConfigurationError, match="not registered"):
            resolve_value("vault://unknown/path#key")

    def test_missing_key_raises_external_service_error(self):
        provider = FakeProvider(secrets={"db/creds": {"user": "admin"}})
        register_provider(name="hashicorp", provider=provider)

        with pytest.raises(ExternalServiceError):
            resolve_value("vault://hashicorp/db/creds#nonexistent")

    def test_missing_path_raises_external_service_error(self):
        provider = FakeProvider(secrets={})
        register_provider(name="hashicorp", provider=provider)

        with pytest.raises(ExternalServiceError):
            resolve_value("vault://hashicorp/no/such/path#key")

    def test_json_string_secret_parsed_to_dict(self):
        provider = FakeProvider(secrets={"app/creds": {"data": '{"access_key": "abc", "secret_key": "xyz"}'}})
        register_provider(name="hashicorp", provider=provider)

        resolved = resolve_value("vault://hashicorp/app/creds#data")
        assert resolved == {"access_key": "abc", "secret_key": "xyz"}

    def test_invalid_json_string_secret_returned_as_raw_string(self):
        provider = FakeProvider(secrets={"app/raw": {"data": "{invalid-json"}})
        register_provider(name="hashicorp", provider=provider)

        resolved = resolve_value("vault://hashicorp/app/raw#data")
        assert resolved == "{invalid-json"

    @pytest.mark.parametrize(
        "value",
        [
            "vault://",
            "vault://hashicorp",
            "vault://hashicorp/",
            "Bearer vault://hashicorp/db/creds#user",
            "https://host/?k=vault://hashicorp/db/creds#user",
            "vault://hashicorp/team-a/../db/creds#user",
            "vault://hashicorp/db/creds#",
        ],
    )
    def test_malformed_reference_rejected_never_returned_as_literal(self, value):
        provider = FakeProvider(secrets={"db/creds": {"user": "admin"}})
        register_provider(name="hashicorp", provider=provider)

        with pytest.raises(MalformedSecretReferenceError):
            resolve_value(value)

    def test_malformed_reference_makes_no_provider_call(self):
        class CountingProvider(FakeProvider):
            calls = 0

            def get_secret(self, *, path, key=None):
                type(self).calls += 1
                return super().get_secret(path=path, key=key)

        register_provider(name="hashicorp", provider=CountingProvider(secrets={"db/creds": {"user": "admin"}}))

        with pytest.raises(MalformedSecretReferenceError):
            resolve_value("vault://hashicorp/team-a/../db/creds#user")
        assert CountingProvider.calls == 0

    def test_malformed_reference_nested_in_config_rejected_without_echo(self):
        canary = "CANARY-partial-paste-5b1e"  # pragma: allowlist secret
        config = {"provider_config": {"secret_key": f"prefix-vault://hashicorp/{canary}"}}  # pragma: allowlist secret

        with pytest.raises(MalformedSecretReferenceError) as exc_info:
            resolve_value(config)
        assert canary not in str(exc_info.value)

    def test_malformed_reference_in_list_rejected(self):
        with pytest.raises(MalformedSecretReferenceError):
            resolve_value(["ok", "vault://"])


class TestHasVaultReferences:
    def test_detects_malformed_and_embedded_values(self):
        assert has_vault_references({"a": ["x", {"b": "vault://"}]}) is True
        assert has_vault_references("Bearer vault://hashicorp/x#y") is True

    def test_plain_config_has_none(self):
        assert has_vault_references({"a": ["x", {"b": 1}]}) is False
