# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the shared secret resolver (design D1/D4/D4b)."""

import logging
from typing import Any

import pytest

from docpipe.exceptions.docpipe_exceptions import ConfigurationError, ExternalServiceError
from docpipe.integrations.secrets.resolver import (
    FindingKind,
    ReferenceFinding,
    SecretErrorCategory,
    SecretPolicy,
    SecretResolutionError,
    inspect_node_references,
    resolve_node_config,
)
from docpipe.integrations.secrets.secret_provider import (
    ProviderUnreachableError,
    SecretProvider,
    clear_providers,
    register_provider,
)
from docpipe.integrations.secrets.secret_value import SecretValue
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader

PATHS = "allowed_paths"
DESTS = "allowed_destinations"


class RecordingProvider(SecretProvider):
    """Fake provider that records every call and can raise a chosen exception."""

    def __init__(self, *, secrets: dict[str, dict[str, Any]], error: Exception | None = None) -> None:
        self._secrets = secrets
        self._error = error
        self.calls: list[tuple[str, str | None]] = []

    def authenticate(self) -> None:
        pass

    def get_secret(self, *, path: str, key: str | None = None) -> str:
        self.calls.append((path, key))
        if self._error is not None:
            raise self._error
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


class FakeOperator:
    """Operator stand-in declaring a few secret-capable fields."""

    short_name = "vectordb"

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        return {
            "secret_fields": [
                "password",
                "token",
                "endpoint_url",
                "credentials.*",
                "provider_config.secret_key",
                "credentials_json",
            ],
        }


class ProviderScopedOperator:
    """Operator whose declarations depend on the selected provider."""

    short_name = "ingest_source"

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        return {
            "secret_fields": [],
            "secret_fields_by_provider": {
                "provider": {
                    "s3": ["provider_config.access_key", "provider_config.secret_key", "provider_config.endpoint_url"],
                    "box": ["provider_config.client_secret"],
                }
            },
        }


class NoDeclarationOperator:
    """Operator that overrides get_metadata() without a secret_fields key (for example merge)."""

    short_name = "merge"

    @staticmethod
    def get_metadata() -> dict[str, Any]:
        return {"description": "no declarations"}


def _set_policy(*, allowed_paths: Any = None, allowed_destinations: Any = None) -> None:
    vault: dict[str, Any] = {}
    if allowed_paths is not None:
        vault[PATHS] = allowed_paths
    if allowed_destinations is not None:
        vault[DESTS] = allowed_destinations
    DocpipeConfigLoader._config = {"secrets": {"vault": vault}}


@pytest.fixture(autouse=True)
def _isolate():
    clear_providers()
    DocpipeConfigLoader.reset()
    yield
    clear_providers()
    DocpipeConfigLoader.reset()


@pytest.fixture
def provider() -> RecordingProvider:
    fake = RecordingProvider(
        secrets={
            # pragma: allowlist nextline secret
            "opensearch/credentials": {"password": "p@ss/word", "token": "tok"},
            # pragma: allowlist nextline secret
            "opensearch/team-a/credentials": {"password": "team-pass"},
            # pragma: allowlist nextline secret
            "OpenSearch/credentials": {"password": "case-pass"},
            "prod/payments": {"key": "payments-key"},
            "single/value": {"only": "the-only-value"},
            "multi/keys": {"a": "1", "b": "2"},
            "empty/value": {"password": ""},
            "json/value": {"password": '{"a": 1}'},
            "json/array": {"password": "[1, 2]"},
            "sa/json": {"doc": '{"type": "service_account", "private_key": "abc"}'},
            "verbatim/values": {"a": "$ecret_Value", "b": "${HOME}", "c": "MY_PASSWORD", "d": "  padded  "},
            "s3/endpoint": {"url": "https://store.example.internal"},
            # pragma: allowlist nextline secret
            "s3/keys": {"secret": "s3-secret", "access": "s3-access"},
        }
    )
    register_provider(name="hashicorp", provider=fake)
    return fake


def _resolve(config: dict[str, Any], operator: Any = FakeOperator) -> dict[str, Any]:
    return resolve_node_config(node_name="node_a", operator_class=operator, config=config)


def _expect(
    config: dict[str, Any], category: SecretErrorCategory, operator: Any = FakeOperator
) -> SecretResolutionError:
    with pytest.raises(SecretResolutionError) as info:
        _resolve(config, operator)
    assert info.value.category is category
    return info.value


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


class TestResolution:
    def test_reference_becomes_secret_value(self, provider):
        _set_policy(allowed_paths=["hashicorp:opensearch/*"])
        result = _resolve({"password": "vault://hashicorp/opensearch/credentials#password", "name": "x"})
        assert isinstance(result["password"], SecretValue)
        assert result["password"].reveal() == "p@ss/word"
        assert result["name"] == "x"
        assert provider.calls == [("opensearch/credentials", "password")]

    def test_input_config_is_not_modified(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])
        config = {"credentials": {"api": "vault://hashicorp/opensearch/credentials#token"}}
        result = _resolve(config)
        assert config == {"credentials": {"api": "vault://hashicorp/opensearch/credentials#token"}}
        assert isinstance(result["credentials"]["api"], SecretValue)
        assert result["credentials"] is not config["credentials"]

    def test_nested_keys(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])
        result = _resolve(
            {
                "credentials": {"api": "vault://hashicorp/opensearch/credentials#token"},
                # pragma: allowlist nextline secret
                "provider_config": {"secret_key": "vault://hashicorp/s3/keys#secret"},
            }
        )
        assert result["credentials"]["api"].reveal() == "tok"
        assert result["provider_config"]["secret_key"].reveal() == "s3-secret"

    def test_keyless_reference_to_single_key_secret(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])
        result = _resolve({"password": "vault://hashicorp/single/value"})
        assert result["password"].reveal() == "the-only-value"
        assert provider.calls == [("single/value", None)]

    def test_provider_scoped_declarations_follow_selected_provider(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])
        config = {
            "provider": "s3",
            # pragma: allowlist nextline secret
            "provider_config": {"secret_key": "vault://hashicorp/s3/keys#secret"},
        }
        result = _resolve(config, ProviderScopedOperator)
        assert result["provider_config"]["secret_key"].reveal() == "s3-secret"

    def test_provider_scoped_field_of_another_provider_is_rejected(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])
        config = {
            "provider": "box",
            # pragma: allowlist nextline secret
            "provider_config": {"secret_key": "vault://hashicorp/s3/keys#secret"},
        }
        _expect(config, SecretErrorCategory.NOT_PERMITTED, ProviderScopedOperator)
        assert provider.calls == []

    def test_values_are_used_verbatim(self, provider, monkeypatch):
        _set_policy(allowed_paths=["hashicorp:**"])
        monkeypatch.setenv("MY_PASSWORD", "from-env")
        monkeypatch.setenv("HOME", "/home/someone")
        result = _resolve(
            {
                # pragma: allowlist nextline secret
                "password": "vault://hashicorp/verbatim/values#a",
                "token": "vault://hashicorp/verbatim/values#b",
                "credentials": {
                    "c": "vault://hashicorp/verbatim/values#c",
                    "d": "vault://hashicorp/verbatim/values#d",
                },
            }
        )
        assert result["password"].reveal() == "$ecret_Value"
        assert result["token"].reveal() == "${HOME}"
        assert result["credentials"]["c"].reveal() == "MY_PASSWORD"
        assert result["credentials"]["d"].reveal() == "  padded  "

    def test_structured_field_is_parsed_once(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])
        result = _resolve({"credentials_json": "vault://hashicorp/sa/json#doc"})
        assert result["credentials_json"].reveal() == {"type": "service_account", "private_key": "abc"}

    def test_structured_field_accepts_plain_string(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])
        result = _resolve({"credentials_json": "vault://hashicorp/opensearch/credentials#token"})
        assert result["credentials_json"].reveal() == "tok"


class TestMixedSources:
    def test_env_and_literal_values_are_left_untouched(self, provider, monkeypatch):
        _set_policy(allowed_paths=["hashicorp:**"])
        monkeypatch.setenv("OPENSEARCH_USER", "alice")
        config = {
            "username": "${OPENSEARCH_USER}",
            "token": "$OTHER_ENV",
            "region": "eu-1",
            # pragma: allowlist nextline secret
            "password": "vault://hashicorp/opensearch/credentials#password",
        }
        result = _resolve(config)
        assert result["username"] == "${OPENSEARCH_USER}"
        assert result["token"] == "$OTHER_ENV"
        assert result["region"] == "eu-1"
        assert result["password"].reveal() == "p@ss/word"
        assert provider.calls == [("opensearch/credentials", "password")]


class TestNoReference:
    def test_returns_same_object_and_makes_no_call(self, provider):
        # pragma: allowlist nextline secret
        config = {"password": "plain", "nested": {"a": ["x", 1, None]}, "count": 3}
        assert _resolve(config) is config
        assert provider.calls == []

    def test_does_not_read_declarations_or_policy(self, provider, monkeypatch):
        class Exploding:
            short_name = "x"

            @staticmethod
            def get_metadata() -> dict[str, Any]:
                raise AssertionError("get_metadata must not be called")

        def boom() -> None:
            raise AssertionError("policy must not be loaded")

        monkeypatch.setattr(SecretPolicy, "load", boom)
        # pragma: allowlist nextline secret
        config = {"password": "plain"}
        assert _resolve(config, Exploding) is config

    def test_destination_rule_does_not_apply_without_vault_credential(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])
        config = {"endpoint_url": "https://attacker.example", "password": "${PASSWORD}"}
        assert _resolve(config) is config
        assert provider.calls == []

    def test_operator_without_secret_fields_key_rejects_reference(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])
        _expect(
            # pragma: allowlist nextline secret
            {"password": "vault://hashicorp/opensearch/credentials#password"},
            SecretErrorCategory.NOT_PERMITTED,
            NoDeclarationOperator,
        )
        assert provider.calls == []


# ---------------------------------------------------------------------------
# Error categories
# ---------------------------------------------------------------------------


class TestErrorCategories:
    def test_provider_not_registered(self, provider):
        _set_policy(allowed_paths=["*:**"])
        error = _expect(
            # pragma: allowlist nextline secret
            {"password": "vault://cyberark/safe/object#Content"},
            SecretErrorCategory.PROVIDER_NOT_REGISTERED,
        )
        assert error.provider == "cyberark"
        assert provider.calls == []

    @pytest.mark.parametrize(
        "reference",
        [
            "vault://hashicorp/missing/path#password",
            "vault://hashicorp/opensearch/credentials#nokey",
            "vault://hashicorp/multi/keys",
        ],
        ids=["missing-path", "missing-key", "ambiguous-multi-key"],
    )
    def test_unavailable_covers_probing_cases(self, provider, reference):
        _set_policy(allowed_paths=["hashicorp:**"])
        error = _expect({"password": reference}, SecretErrorCategory.SECRET_UNAVAILABLE)
        assert error.category.value == "secret unavailable"

    def test_denial_is_secret_unavailable(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])
        provider._error = ExternalServiceError("Vault returned HTTP 403 permission denied")
        _expect(
            # pragma: allowlist nextline secret
            {"password": "vault://hashicorp/opensearch/credentials#password"},
            SecretErrorCategory.SECRET_UNAVAILABLE,
        )

    def test_empty_value_is_secret_unavailable(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])
        _expect(
            # pragma: allowlist nextline secret
            {"password": "vault://hashicorp/empty/value#password"},
            SecretErrorCategory.SECRET_UNAVAILABLE,
        )

    @pytest.mark.parametrize(
        "exc", [ProviderUnreachableError("down"), ConnectionError("refused"), TimeoutError("slow")]
    )
    def test_unreachable(self, provider, exc):
        _set_policy(allowed_paths=["hashicorp:**"])
        provider._error = exc
        error = _expect(
            # pragma: allowlist nextline secret
            {"password": "vault://hashicorp/opensearch/credentials#password"},
            SecretErrorCategory.VAULT_UNREACHABLE,
        )
        assert error.status_code == 502

    @pytest.mark.parametrize(
        "value",
        [
            "vault://hashicorp",
            "vault://hashicorp/",
            "vault://hashicorp/opensearch/../prod/payments#key",
            "prefix vault://hashicorp/opensearch/credentials#password",
            "vault://hashicorp/opensearch/credentials#password suffix",
            "vault://hashicorp/a vault://hashicorp/b",
            "vault://hashicorp/opensearch/credentials#",
        ],
    )
    def test_malformed_reference(self, provider, value):
        _set_policy(allowed_paths=["hashicorp:**"])
        error = _expect({"password": value}, SecretErrorCategory.MALFORMED_REFERENCE)
        assert "vault://<provider>/<path>[#<key>]" in str(error)
        assert "opensearch" not in str(error)
        assert provider.calls == []

    def test_embedded_reference_in_undeclared_field_is_malformed_not_ignored(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])
        _expect({"label": "see vault://hashicorp/x/y#z"}, SecretErrorCategory.MALFORMED_REFERENCE)

    def test_undeclared_field(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])
        error = _expect(
            {"index_name": "vault://hashicorp/opensearch/credentials#password"}, SecretErrorCategory.NOT_PERMITTED
        )
        assert error.config_key == "index_name"
        assert provider.calls == []

    @pytest.mark.parametrize(
        "reference",
        ["vault://hashicorp/json/value#password", "vault://hashicorp/json/array#password"],
    )
    def test_json_in_scalar_field(self, provider, reference):
        _set_policy(allowed_paths=["hashicorp:**"])
        _expect({"password": reference}, SecretErrorCategory.VALUE_MUST_BE_STRING)


# ---------------------------------------------------------------------------
# Path policy
# ---------------------------------------------------------------------------


class TestPathPolicy:
    def test_path_outside_policy(self, provider):
        _set_policy(allowed_paths=["hashicorp:opensearch/*"])
        error = _expect({"password": "vault://hashicorp/prod/payments#key"}, SecretErrorCategory.NOT_PERMITTED)
        assert error.config_key == "password"
        assert provider.calls == []

    def test_path_inside_policy(self, provider):
        _set_policy(allowed_paths=["hashicorp:opensearch/*"])
        result = _resolve({"password": "vault://hashicorp/opensearch/credentials#password"})
        assert result["password"].reveal() == "p@ss/word"

    def test_single_star_does_not_cross_segment(self, provider):
        _set_policy(allowed_paths=["hashicorp:opensearch/*"])
        _expect(
            # pragma: allowlist nextline secret
            {"password": "vault://hashicorp/opensearch/team-a/credentials#password"},
            SecretErrorCategory.NOT_PERMITTED,
        )
        assert provider.calls == []

    def test_double_star_crosses_segments(self, provider):
        _set_policy(allowed_paths=["hashicorp:opensearch/**"])
        result = _resolve({"password": "vault://hashicorp/opensearch/team-a/credentials#password"})
        assert result["password"].reveal() == "team-pass"

    def test_matching_is_case_sensitive(self, provider):
        _set_policy(allowed_paths=["hashicorp:opensearch/*"])
        _expect(
            # pragma: allowlist nextline secret
            {"password": "vault://hashicorp/OpenSearch/credentials#password"},
            SecretErrorCategory.NOT_PERMITTED,
        )
        assert provider.calls == []

    def test_provider_match_is_case_sensitive_and_exact(self, provider):
        _set_policy(allowed_paths=["HashiCorp:**"])
        # pragma: allowlist nextline secret
        _expect({"password": "vault://hashicorp/opensearch/credentials#password"}, SecretErrorCategory.NOT_PERMITTED)

    def test_other_provider_entry_does_not_apply(self, provider):
        _set_policy(allowed_paths=["cyberark:**"])
        # pragma: allowlist nextline secret
        _expect({"password": "vault://hashicorp/opensearch/credentials#password"}, SecretErrorCategory.NOT_PERMITTED)

    def test_field_scoped_entry(self, provider):
        _set_policy(allowed_paths=["hashicorp:opensearch/*@vectordb.password"])
        permitted = _resolve({"password": "vault://hashicorp/opensearch/credentials#password"})
        assert permitted["password"].reveal() == "p@ss/word"
        _expect({"token": "vault://hashicorp/opensearch/credentials#password"}, SecretErrorCategory.NOT_PERMITTED)
        assert provider.calls == [("opensearch/credentials", "password")]

    def test_field_scoped_entry_does_not_apply_to_other_operator(self, provider):
        _set_policy(allowed_paths=["hashicorp:opensearch/*@ingest_source.password"])
        # pragma: allowlist nextline secret
        _expect({"password": "vault://hashicorp/opensearch/credentials#password"}, SecretErrorCategory.NOT_PERMITTED)

    def test_field_scoped_entry_matches_nested_field_name(self, provider):
        _set_policy(allowed_paths=["hashicorp:s3/*@vectordb.secret_key"])
        result = _resolve({"provider_config": {"secret_key": "vault://hashicorp/s3/keys#secret"}})
        assert result["provider_config"]["secret_key"].reveal() == "s3-secret"

    @pytest.mark.parametrize("policy", [None, [], "hashicorp:**", {"a": "b"}, [""], [None, 3]])
    def test_unset_or_unusable_policy_denies_without_provider_call(self, provider, policy):
        _set_policy(allowed_paths=policy)
        # pragma: allowlist nextline secret
        _expect({"password": "vault://hashicorp/opensearch/credentials#password"}, SecretErrorCategory.NOT_PERMITTED)
        assert provider.calls == []

    def test_missing_secrets_section_denies(self, provider):
        DocpipeConfigLoader._config = {}
        # pragma: allowlist nextline secret
        _expect({"password": "vault://hashicorp/opensearch/credentials#password"}, SecretErrorCategory.NOT_PERMITTED)
        assert provider.calls == []

    def test_allow_all(self, provider):
        _set_policy(allowed_paths=["*:**"])
        result = _resolve({"password": "vault://hashicorp/prod/payments#key"})
        assert result["password"].reveal() == "payments-key"

    def test_malformed_policy_entry_grants_nothing(self, provider):
        _set_policy(allowed_paths=["no-colon", "hashicorp:", "hashicorp:x@broken"])
        # pragma: allowlist nextline secret
        _expect({"password": "vault://hashicorp/opensearch/credentials#password"}, SecretErrorCategory.NOT_PERMITTED)


# ---------------------------------------------------------------------------
# Destination binding
# ---------------------------------------------------------------------------


class TestDestinationBinding:
    def test_attacker_chosen_endpoint_is_rejected_without_vault_request(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])
        config = {
            "endpoint_url": "https://attacker.example",
            # pragma: allowlist nextline secret
            "password": "vault://hashicorp/opensearch/credentials#password",
        }
        error = _expect(config, SecretErrorCategory.NOT_PERMITTED)
        assert error.config_key == "endpoint_url"
        assert provider.calls == []

    def test_allowed_destination(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"], allowed_destinations=["*.s3.example.internal"])
        config = {
            "endpoint_url": "https://store.s3.example.internal",
            # pragma: allowlist nextline secret
            "password": "vault://hashicorp/opensearch/credentials#password",
        }
        result = _resolve(config)
        assert result["endpoint_url"] == "https://store.s3.example.internal"
        assert result["password"].reveal() == "p@ss/word"

    def test_destination_host_with_port_and_path_is_matched_on_host(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"], allowed_destinations=["store.example.internal"])
        config = {
            "endpoint_url": "https://store.example.internal:9000/base",
            # pragma: allowlist nextline secret
            "password": "vault://hashicorp/opensearch/credentials#password",
        }
        assert isinstance(_resolve(config)["password"], SecretValue)

    @pytest.mark.parametrize(
        "endpoint",
        [
            "https://store.example.internal.attacker.example",
            "https://attacker.example/store.example.internal",
            "https://store.example.internal@attacker.example",
            "https://attacker.example#store.example.internal",
            "https://STORE.example.internal\\@attacker.example",
        ],
    )
    def test_destination_lookalikes_are_rejected(self, provider, endpoint):
        _set_policy(allowed_paths=["hashicorp:**"], allowed_destinations=["store.example.internal"])
        _expect(
            # pragma: allowlist nextline secret
            {"endpoint_url": endpoint, "password": "vault://hashicorp/opensearch/credentials#password"},
            SecretErrorCategory.NOT_PERMITTED,
        )
        assert provider.calls == []

    def test_destination_host_comparison_is_case_insensitive(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"], allowed_destinations=["Store.Example.Internal"])
        config = {
            "endpoint_url": "https://STORE.example.internal",
            # pragma: allowlist nextline secret
            "password": "vault://hashicorp/opensearch/credentials#password",
        }
        assert isinstance(_resolve(config)["password"], SecretValue)

    def test_destination_from_vault(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])
        config = {
            "endpoint_url": "vault://hashicorp/s3/endpoint#url",
            # pragma: allowlist nextline secret
            "password": "vault://hashicorp/opensearch/credentials#password",
        }
        result = _resolve(config)
        assert result["endpoint_url"].reveal() == "https://store.example.internal"

    def test_unset_and_blank_destination_are_permitted(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])
        for endpoint in (None, ""):
            # pragma: allowlist nextline secret
            config = {"endpoint_url": endpoint, "password": "vault://hashicorp/opensearch/credentials#password"}
            assert isinstance(_resolve(config)["password"], SecretValue)

    def test_destination_default_hidden_in_env_form_is_checked(self, provider, monkeypatch):
        monkeypatch.delenv("S3_ENDPOINT", raising=False)
        _set_policy(allowed_paths=["hashicorp:**"])
        config = {
            "endpoint_url": "${S3_ENDPOINT:https://attacker.example}",
            # pragma: allowlist nextline secret
            "password": "vault://hashicorp/opensearch/credentials#password",
        }
        _expect(config, SecretErrorCategory.NOT_PERMITTED)
        assert provider.calls == []

    def test_destination_env_value_is_checked(self, provider, monkeypatch):
        monkeypatch.setenv("S3_ENDPOINT", "https://attacker.example")
        _set_policy(allowed_paths=["hashicorp:**"])
        # pragma: allowlist nextline secret
        config = {"endpoint_url": "$S3_ENDPOINT", "password": "vault://hashicorp/opensearch/credentials#password"}
        _expect(config, SecretErrorCategory.NOT_PERMITTED)

    def test_destination_in_provider_scoped_config(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])
        config = {
            "provider": "s3",
            "provider_config": {
                "endpoint_url": "https://attacker.example",
                # pragma: allowlist nextline secret
                "secret_key": "vault://hashicorp/s3/keys#secret",
            },
        }
        error = _expect(config, SecretErrorCategory.NOT_PERMITTED, ProviderScopedOperator)
        assert error.config_key == "provider_config.endpoint_url"
        assert provider.calls == []

    def test_non_list_destinations_setting_allows_nothing(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"], allowed_destinations="store.example.internal")
        _expect(
            {
                "endpoint_url": "https://store.example.internal",
                # pragma: allowlist nextline secret
                "password": "vault://hashicorp/opensearch/credentials#password",
            },
            SecretErrorCategory.NOT_PERMITTED,
        )


# ---------------------------------------------------------------------------
# Fail closed, messages, correlation
# ---------------------------------------------------------------------------


class TestFailClosed:
    def test_first_failure_aborts_and_later_references_are_not_fetched(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])
        config = {
            # pragma: allowlist nextline secret
            "password": "vault://hashicorp/opensearch/credentials#password",
            "token": "vault://hashicorp/missing/path#token",
            "credentials": {"api": "vault://hashicorp/opensearch/credentials#token"},
        }
        _expect(config, SecretErrorCategory.SECRET_UNAVAILABLE)
        assert provider.calls == [("opensearch/credentials", "password"), ("missing/path", "token")]

    def test_policy_denial_of_a_later_reference_prevents_all_provider_calls(self, provider):
        _set_policy(allowed_paths=["hashicorp:opensearch/*"])
        config = {
            # pragma: allowlist nextline secret
            "password": "vault://hashicorp/opensearch/credentials#password",
            "token": "vault://hashicorp/prod/payments#key",
        }
        _expect(config, SecretErrorCategory.NOT_PERMITTED)
        assert provider.calls == []


class TestErrorMessages:
    def test_message_format_and_attributes(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])
        error = _expect(
            {"credentials": {"api": "vault://hashicorp/missing/path#secretkey"}}, SecretErrorCategory.SECRET_UNAVAILABLE
        )
        assert (
            str(error)
            == f"secret reference credentials.api (provider hashicorp): secret unavailable [id {error.correlation_id}]"
        )
        assert error.config_key == "credentials.api"
        assert error.provider == "hashicorp"
        assert error.node_name == "node_a"
        assert error.__cause__ is None
        assert error.__suppress_context__ is True

    def test_message_contains_no_path_key_or_exception_text(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])
        provider._error = ExternalServiceError(
            "boom https://vault.internal:8200/v1/secret/data/opensearch/credentials leaked-token-123"
        )
        error = _expect(
            # pragma: allowlist nextline secret
            {"password": "vault://hashicorp/opensearch/credentials#password"},
            SecretErrorCategory.SECRET_UNAVAILABLE,
        )
        text = str(error)
        for fragment in ("opensearch", "credentials#", "leaked-token-123", "vault.internal", "8200"):
            assert fragment not in text

    def test_correlation_id_matches_server_side_log(self, provider, caplog):
        _set_policy(allowed_paths=["hashicorp:**"])
        provider._error = ExternalServiceError("detail-for-the-log")
        with caplog.at_level(logging.WARNING, logger="docpipe"):
            error = _expect(
                # pragma: allowlist nextline secret
                {"password": "vault://hashicorp/opensearch/credentials#password"},
                SecretErrorCategory.SECRET_UNAVAILABLE,
            )
        records = [r for r in caplog.records if error.correlation_id in r.getMessage()]
        assert records
        message = records[0].getMessage()
        assert "node=node_a" in message
        assert "operator=vectordb" in message
        assert "key=password" in message
        assert "secret unavailable" in message

    def test_log_does_not_contain_secret_values(self, provider, caplog):
        _set_policy(allowed_paths=["hashicorp:**"])
        with caplog.at_level(logging.DEBUG, logger="docpipe"):
            # pragma: allowlist nextline secret
            _resolve({"password": "vault://hashicorp/opensearch/credentials#password"})
            _expect({"token": "vault://hashicorp/missing/x#y"}, SecretErrorCategory.SECRET_UNAVAILABLE)
        assert "p@ss/word" not in caplog.text

    def test_hostile_provider_name_is_neutralised(self, provider):
        _set_policy(allowed_paths=["*:**"])
        error = _expect({"password": "vault://evil%0Aprovider/path#key"}, SecretErrorCategory.PROVIDER_NOT_REGISTERED)
        assert "\n" not in str(error)

    def test_hostile_config_key_is_neutralised(self, provider):
        _set_policy(allowed_paths=["*:**"])
        error = _expect({"cred\nentials": {"x y": "vault://hashicorp/a/b#c"}}, SecretErrorCategory.NOT_PERMITTED)
        assert "\n" not in str(error)
        assert " y" not in error.config_key

    def test_unreachable_message_has_no_url(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])
        provider._error = ProviderUnreachableError("connection to https://vault.internal:8200 refused")
        error = _expect(
            # pragma: allowlist nextline secret
            {"password": "vault://hashicorp/opensearch/credentials#password"},
            SecretErrorCategory.VAULT_UNREACHABLE,
        )
        assert "vault.internal" not in str(error)

    def test_all_categories_are_the_fixed_set(self):
        assert {c.value for c in SecretErrorCategory} == {
            "provider not registered",
            "secret unavailable",
            "vault unreachable",
            "malformed reference",
            "not permitted",
            "value must be a string",
        }


# ---------------------------------------------------------------------------
# Startup diagnostics
# ---------------------------------------------------------------------------


class TestStartupDiagnostics:
    def test_error_when_provider_registered_and_policy_unset(self, provider, caplog):
        DocpipeConfigLoader._config = {}
        with caplog.at_level(logging.WARNING, logger="docpipe"):
            SecretPolicy.log_startup_diagnostics()
        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(errors) == 1
        assert "secrets.vault.allowed_paths" in errors[0].getMessage()

    def test_error_when_policy_empty(self, provider, caplog):
        _set_policy(allowed_paths=[])
        with caplog.at_level(logging.WARNING, logger="docpipe"):
            SecretPolicy.log_startup_diagnostics()
        assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 1

    def test_warning_for_allow_all(self, provider, caplog):
        _set_policy(allowed_paths=["*:**"])
        with caplog.at_level(logging.WARNING, logger="docpipe"):
            SecretPolicy.log_startup_diagnostics()
        assert [r for r in caplog.records if r.levelno == logging.ERROR] == []
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "any Vault path readable by the platform" in warnings[0].getMessage()

    def test_quiet_for_scoped_policy(self, provider, caplog):
        _set_policy(allowed_paths=["hashicorp:opensearch/*"])
        with caplog.at_level(logging.WARNING, logger="docpipe"):
            SecretPolicy.log_startup_diagnostics()
        assert caplog.records == []

    def test_error_for_unparseable_entry(self, provider, caplog):
        _set_policy(allowed_paths=["hashicorp:opensearch/*", "garbage"])
        with caplog.at_level(logging.WARNING, logger="docpipe"):
            SecretPolicy.log_startup_diagnostics()
        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(errors) == 1
        assert "garbage" not in errors[0].getMessage()

    def test_silent_without_registered_provider(self, caplog):
        DocpipeConfigLoader._config = {}
        with caplog.at_level(logging.WARNING, logger="docpipe"):
            SecretPolicy.log_startup_diagnostics()
        assert caplog.records == []


# ---------------------------------------------------------------------------
# Inspection without a provider call (flow validation)
# ---------------------------------------------------------------------------


def _inspect(config: dict[str, Any], operator: Any = FakeOperator) -> list[ReferenceFinding]:
    return inspect_node_references(operator_class=operator, config=config)


class TestInspectNodeReferences:
    def test_valid_references_have_no_findings_and_no_provider_call(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])

        # pragma: allowlist nextline secret
        assert _inspect({"password": "vault://hashicorp/opensearch/credentials#password"}) == []
        assert provider.calls == []

    def test_config_without_references_has_no_findings(self):
        # pragma: allowlist nextline secret
        assert _inspect({"password": "plain", "n": 1}) == []

    def test_malformed_and_embedded_values_are_reported_by_key(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])

        findings = _inspect({"password": "vault://", "endpoint_url": "https://h/?k=vault://hashicorp/a#b"})

        assert findings == [
            ReferenceFinding(config_key="password", kind=FindingKind.MALFORMED, provider=None),
            ReferenceFinding(config_key="endpoint_url", kind=FindingKind.MALFORMED, provider=None),
        ]

    def test_every_problem_is_reported_not_only_the_first(self, provider):
        _set_policy(allowed_paths=["hashicorp:opensearch/*"])

        findings = _inspect(
            {
                "name": "vault://hashicorp/opensearch/a#b",
                # pragma: allowlist nextline secret
                "password": "vault://hashicorp/other/a#b",
                "token": "vault://nowhere/opensearch/a#b",
                "model": "vault://hashicorp/opensearch/a#b",
            }
        )

        assert {(f.config_key, f.kind) for f in findings} == {
            ("name", FindingKind.FIELD_NOT_SECRET_CAPABLE),
            ("password", FindingKind.PATH_NOT_PERMITTED),
            ("token", FindingKind.PROVIDER_NOT_REGISTERED),
            ("model", FindingKind.FIELD_NOT_SECRET_CAPABLE),
        }

    def test_findings_carry_the_provider_but_never_the_path(self, provider):
        _set_policy(allowed_paths=["hashicorp:opensearch/*"])

        (finding,) = _inspect({"password": "vault://hashicorp/CANARY-path/a#CANARY-key"})

        assert finding.provider == "hashicorp"
        assert "CANARY" not in repr(finding)

    def test_provider_scoped_declaration_follows_the_selected_provider(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])
        # pragma: allowlist nextline secret
        config = {"provider": "box", "provider_config": {"secret_key": "vault://hashicorp/a#b"}}

        findings = _inspect(config, ProviderScopedOperator)

        assert findings == [
            ReferenceFinding(
                config_key="provider_config.secret_key", kind=FindingKind.FIELD_NOT_SECRET_CAPABLE, provider="hashicorp"
            )
        ]

    def test_operator_without_declarations_reports_every_reference(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"])

        findings = _inspect({"x": "vault://hashicorp/a#b"}, NoDeclarationOperator)

        assert [f.kind for f in findings] == [FindingKind.FIELD_NOT_SECRET_CAPABLE]

    def test_literal_destination_outside_the_policy_is_reported_when_a_reference_passes(self, provider):
        _set_policy(allowed_paths=["hashicorp:**"], allowed_destinations=["store.example.internal"])

        findings = _inspect({"password": "vault://hashicorp/a#b", "endpoint_url": "https://other.example.net"})

        assert findings == [
            ReferenceFinding(config_key="endpoint_url", kind=FindingKind.DESTINATION_NOT_PERMITTED, provider=None)
        ]
        assert provider.calls == []

    def test_literal_destination_alone_is_not_reported_without_a_reference(self):
        _set_policy(allowed_paths=["hashicorp:**"], allowed_destinations=["store.example.internal"])

        assert _inspect({"endpoint_url": "https://other.example.net"}) == []

    def test_inspection_logs_nothing_and_raises_nothing(self, provider, caplog):
        _set_policy(allowed_paths=["hashicorp:opensearch/*"])

        with caplog.at_level(logging.DEBUG):
            # pragma: allowlist nextline secret
            _inspect({"password": "vault://hashicorp/other/a#b"})

        assert caplog.records == []
