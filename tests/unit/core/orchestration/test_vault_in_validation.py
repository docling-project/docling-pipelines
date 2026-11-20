# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for vault reference handling during flow validation."""

import pytest

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.orchestration.flow_validator import FlowValidator, ValidateStepResults
from docpipe.integrations.secrets.secret_provider import (
    SecretProvider,
    clear_providers,
    parse_vault_reference,
    register_provider,
)


class DummyMockSecretProvider(SecretProvider):
    """Mock secret provider for tests."""

    def authenticate(self) -> None:
        """Mock authenticate."""

    def is_available(self) -> bool:
        """Mock is_available."""
        return True

    def get_secret(self, *, path: str, key: str | None = None) -> str:
        """Return dummy secret."""
        return "resolved_secret_val"


def test_parse_vault_reference_success() -> None:
    """Test parse_vault_reference parses valid URIs."""
    provider, path, key = parse_vault_reference("vault://hashicorp/secret/data/db#password")
    assert provider == "hashicorp"
    assert path == "secret/data/db"
    assert key == "password"

    provider2, path2, key2 = parse_vault_reference("vault://custom-provider/keys/api")
    assert provider2 == "custom-provider"
    assert path2 == "keys/api"
    assert key2 is None


def test_parse_vault_reference_invalid() -> None:
    """Test parse_vault_reference raises ValueError on invalid URIs."""
    with pytest.raises(ValueError, match="Invalid vault reference"):
        parse_vault_reference("http://localhost:8080/secret")


def test_sanitize_vault_refs_for_validation() -> None:
    """Every reference becomes the one validation sentinel, whatever the key; other values are kept."""
    config = {
        "api_key": "vault://hashicorp/llm/openai#key",  # pragma: allowlist secret
        "credentials": "vault://hashicorp/s3/creds#json",
        "nested": {
            "token": "vault://hashicorp/milvus#token",
            "normal_val": "hello",
        },
        "list_val": ["vault://hashicorp/item1#k", "plain"],
    }
    sentinel = DocpipeConstants.VALIDATION_SECRET_SENTINEL

    sanitized = FlowValidator._sanitize_vault_refs_for_validation(config)

    assert sanitized["api_key"] == sentinel  # type: ignore[index]
    assert sanitized["credentials"] == sentinel  # type: ignore[index]
    assert sanitized["nested"]["token"] == sentinel  # type: ignore[index]
    assert sanitized["nested"]["normal_val"] == "hello"  # type: ignore[index]
    assert sanitized["list_val"] == [sentinel, "plain"]  # type: ignore[index]
    assert str(config["api_key"]).startswith("vault://")


def test_validate_vault_references_alert() -> None:
    """Test _validate_vault_references warns when provider is unregistered and errors on malformed URI."""
    clear_providers()
    validator = FlowValidator.__new__(FlowValidator)
    validate_results = ValidateStepResults(available_features={}, errors=[], warnings=[])

    dag = [
        {
            OperatorConstants.Columns.NAME: "ingest",
            OperatorConstants.Misc.OPERATOR: "ingest_source",
            OperatorConstants.Config.CONFIG: {
                "credentials": "vault://unregistered_prov/creds#json",
            },
        }
    ]

    validator._validate_vault_references(dag=dag, validate_results=validate_results)
    assert len(validate_results.warnings) == 1
    assert "references vault provider 'unregistered_prov'" in validate_results.warnings[0].message

    # Register provider and test no warnings
    register_provider(name="unregistered_prov", provider=DummyMockSecretProvider())
    validate_results_clean = ValidateStepResults(available_features={}, errors=[], warnings=[])
    validator._validate_vault_references(dag=dag, validate_results=validate_results_clean)
    assert len(validate_results_clean.warnings) == 0
    clear_providers()


def test_collect_vault_refs() -> None:
    """Test _collect_vault_refs extracts all vault reference URIs with their object paths."""
    config = {
        "api_key": "vault://hashicorp/llm/openai#key",  # pragma: allowlist secret
        "nested": {
            "token": "vault://provider1/auth#tok",  # pragma: allowlist secret
            "plain": "value",
        },
        "list_items": [
            "plain_entry",
            "vault://provider2/list#item",
        ],
        "plain_number": 42,
    }
    refs = FlowValidator._collect_vault_refs(config)
    assert ("api_key", "vault://hashicorp/llm/openai#key") in refs  # pragma: allowlist secret
    assert ("nested.token", "vault://provider1/auth#tok") in refs  # pragma: allowlist secret
    assert ("list_items[1]", "vault://provider2/list#item") in refs
    assert len(refs) == 3


def test_validate_single_vault_ref_malformed() -> None:
    """Test _validate_single_vault_ref produces error alert on malformed URI."""
    validate_results = ValidateStepResults(available_features={}, errors=[], warnings=[])
    op_def = {OperatorConstants.Columns.NAME: "node_1"}

    FlowValidator._validate_single_vault_ref(
        path="credentials",
        ref="vault://",
        op_def=op_def,
        validate_results=validate_results,
    )
    assert len(validate_results.errors) == 1
    assert "malformed vault URI" in validate_results.errors[0].message
    assert len(validate_results.warnings) == 0


@pytest.mark.parametrize(
    "ref",
    [
        "vault://",
        "vault://hashicorp",
        "Bearer vault://hashicorp/api#token",
        "vault://hashicorp/team-a/../team-b/db#password",
        "vault://hashicorp/db creds#password",
    ],
)
def test_validate_single_vault_ref_malformed_does_not_echo_value(ref: str) -> None:
    """Malformed and embedded references are errors that name the config key only."""
    canary_ref = f"{ref}-CANARY-typo-3c9f"  # pragma: allowlist secret
    validate_results = ValidateStepResults(available_features={}, errors=[], warnings=[])

    FlowValidator._validate_single_vault_ref(
        path="provider_config.secret_key",
        ref=canary_ref,
        op_def={OperatorConstants.Columns.NAME: "node_1"},
        validate_results=validate_results,
    )

    assert len(validate_results.errors) == 1
    assert len(validate_results.warnings) == 0
    message = validate_results.errors[0].message
    assert "provider_config.secret_key" in message
    assert "CANARY-typo-3c9f" not in message
    assert "hashicorp" not in message
    assert validate_results.errors[0].message_code == "VAULT_URI_MALFORMED"


def test_validate_vault_references_flags_embedded_reference_in_dag() -> None:
    """An embedded reference (not at the start of the value) is reported, not skipped."""
    clear_providers()
    validator = FlowValidator.__new__(FlowValidator)
    validate_results = ValidateStepResults(available_features={}, errors=[], warnings=[])
    dag = [
        {
            OperatorConstants.Columns.NAME: "ingest",
            OperatorConstants.Misc.OPERATOR: "ingest_source",
            OperatorConstants.Config.CONFIG: {"endpoint_url": "https://host/?k=vault://hashicorp/api#token"},
        }
    ]

    validator._validate_vault_references(dag=dag, validate_results=validate_results)

    assert len(validate_results.errors) == 1
    assert "endpoint_url" in validate_results.errors[0].message
    assert "hashicorp" not in validate_results.errors[0].message


def test_validate_single_vault_ref_valid_and_unregistered_warns_without_error() -> None:
    clear_providers()
    validate_results = ValidateStepResults(available_features={}, errors=[], warnings=[])

    FlowValidator._validate_single_vault_ref(
        path="api_key",
        ref="vault://unknown-prov/path#key",
        op_def={OperatorConstants.Columns.NAME: "node_1"},
        validate_results=validate_results,
    )

    assert validate_results.errors == []
    assert len(validate_results.warnings) == 1
