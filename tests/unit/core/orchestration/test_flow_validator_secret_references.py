# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Flow validation of ``vault://`` references (task B.6).

Validation accepts a reference in a secret-capable field without contacting Vault, reports
problems with references as key-only errors, and reports an unregistered provider as a warning.
Every test registers a provider that fails the test if it is asked for a secret.
"""

from collections.abc import Iterator
from typing import Any

import pytest

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator
from docpipe.integrations.secrets.secret_provider import SecretProvider, clear_providers, register_provider
from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader

CANARY = "CANARY-9d41"


class _CountingProvider(SecretProvider):
    """Counts every secret request; validation must make none."""

    def __init__(self) -> None:
        self.requests = 0

    def authenticate(self) -> None:
        """Not used."""

    def is_available(self) -> bool:
        """Always available."""
        return True

    def get_secret(self, *, path: str, key: str | None = None) -> str:
        """Record the request and fail the calling test."""
        self.requests += 1
        raise AssertionError("validation contacted the secret provider")


def _ref(name: str) -> str:
    return f"vault://hashicorp/{name}#value"


def _set_policy(*, allowed_paths: list[str] | None = None, allowed_destinations: list[str] | None = None) -> None:
    vault: dict[str, Any] = {"allowed_paths": allowed_paths if allowed_paths is not None else ["hashicorp:**"]}
    if allowed_destinations is not None:
        vault["allowed_destinations"] = allowed_destinations
    DocpipeConfigLoader._config = {"secrets": {"vault": vault}}


@pytest.fixture
def provider() -> Iterator[_CountingProvider]:
    clear_providers()
    fake = _CountingProvider()
    register_provider(name="hashicorp", provider=fake)
    _set_policy()
    yield fake
    clear_providers()
    DocpipeConfigLoader.reset()


def _validate(*, node_type: str, config: dict[str, Any]) -> dict[str, Any]:
    flow = {
        "flow_name": "secret-reference-validation",
        "global_config": {"storage": "in-memory"},
        "flow": [{"type": node_type, "name": "node_a", "config": config}],
    }
    return DocpipeFlowManager(flow_def=flow, configure_logging=False).validate()


def _codes(result: dict[str, Any], *, kind: str) -> list[str]:
    """Return the message codes of the errors or warnings, ignoring the single-node structure alerts."""
    structural = {"DISJOINT_OPERATORS_DETECTED", "GENERATE_OUTPUT_MISSING", "INGEST_OPERATOR_MISPLACED"}
    return [code for alert in result[kind] for code in [_message_code(alert)] if code not in structural]


def _message_code(alert: Any) -> str:
    text = str(alert)
    marker = "'message_code': '"
    start = text.index(marker) + len(marker)
    return text[start : text.index("'", start)]


def _text(result: dict[str, Any]) -> str:
    return " ".join(str(alert) for alert in result["errors"] + result["warnings"])


def _s3(**overrides: str) -> dict[str, Any]:
    # pragma: allowlist nextline secret
    provider_config = {"access_key": "AKIA", "secret_key": "plain", "bucket": "bk"}
    provider_config.update(overrides)
    return {"provider": "s3", "provider_config": provider_config}


class TestReferencesInDeclaredFields:
    def test_s3_endpoint_url_reference_has_no_format_error(self, provider: _CountingProvider) -> None:
        result = _validate(node_type="ingest_source", config=_s3(endpoint_url=_ref("s3/endpoint")))

        assert _codes(result, kind="errors") == []
        assert "http://" not in _text(result)
        assert provider.requests == 0

    def test_s3_secret_key_reference_has_no_missing_field_error(self, provider: _CountingProvider) -> None:
        result = _validate(node_type="ingest_source", config=_s3(secret_key=_ref("s3/secret")))

        assert _codes(result, kind="errors") == []
        assert "secret_key" not in _text(result)
        assert provider.requests == 0

    def test_s3_bucket_reference_is_accepted(self, provider: _CountingProvider) -> None:
        result = _validate(node_type="ingest_source", config=_s3(bucket=_ref("s3/bucket")))

        assert _codes(result, kind="errors") == []
        assert provider.requests == 0

    def test_milvus_uri_reference_has_no_error_and_does_not_connect(self, provider: _CountingProvider) -> None:
        config = {
            "provider": "milvus",
            "provider_config": {"auth_type": "uri", "collection_name": "docs", "uri": _ref("milvus/uri")},
        }

        result = _validate(node_type="vectordb", config=config)

        assert _codes(result, kind="errors") == []
        assert provider.requests == 0

    def test_milvus_token_reference_is_accepted(self, provider: _CountingProvider) -> None:
        _set_policy(allowed_destinations=["milvus.example.com"])
        config = {
            "provider": "milvus",
            "provider_config": {
                "auth_type": "token",
                "collection_name": "docs",
                "host": "milvus.example.com",
                "token": _ref("milvus/token"),
            },
        }

        result = _validate(node_type="vectordb", config=config)

        assert _codes(result, kind="errors") == []
        assert provider.requests == 0


class TestReferencesInFieldsThatAreNotSecretCapable:
    def test_filesystem_paths_reference_is_a_key_only_error(self, provider: _CountingProvider) -> None:
        config = {"provider": "filesystem", "provider_config": {"paths": [f"vault://hashicorp/{CANARY}#paths"]}}

        result = _validate(node_type="ingest_source", config=config)

        assert _codes(result, kind="errors") == ["VAULT_FIELD_NOT_SECRET_CAPABLE"]
        text = _text(result)
        assert "provider_config.paths.0" in text
        assert CANARY not in text
        assert "does not exist" not in text
        assert provider.requests == 0

    def test_web_urls_reference_is_a_key_only_error(self, provider: _CountingProvider) -> None:
        config = {"provider": "web", "provider_config": {"urls": [f"vault://hashicorp/{CANARY}#url"]}}

        result = _validate(node_type="ingest_source", config=config)

        assert _codes(result, kind="errors") == ["VAULT_FIELD_NOT_SECRET_CAPABLE"]
        text = _text(result)
        assert "provider_config.urls.0" in text
        assert CANARY not in text
        assert "must start with" not in text
        assert provider.requests == 0


class TestReferenceProblems:
    def test_malformed_reference_is_reported_once_without_its_value(self, provider: _CountingProvider) -> None:
        result = _validate(node_type="ingest_source", config=_s3(secret_key=f"vault://{CANARY}"))

        assert _codes(result, kind="errors") == ["VAULT_URI_MALFORMED"]
        assert CANARY not in _text(result)
        assert "provider_config.secret_key" in _text(result)
        assert provider.requests == 0

    def test_embedded_reference_is_an_error_without_its_value(self, provider: _CountingProvider) -> None:
        endpoint = f"https://host/?k=vault://hashicorp/{CANARY}#token"

        result = _validate(node_type="ingest_source", config=_s3(endpoint_url=endpoint))

        assert _codes(result, kind="errors") == ["VAULT_URI_MALFORMED"]
        assert CANARY not in _text(result)
        assert provider.requests == 0

    def test_reference_outside_the_path_policy_is_an_error(self, provider: _CountingProvider) -> None:
        _set_policy(allowed_paths=["hashicorp:opensearch/*"])

        result = _validate(node_type="ingest_source", config=_s3(secret_key=f"vault://hashicorp/{CANARY}#key"))

        assert _codes(result, kind="errors") == ["VAULT_PATH_NOT_PERMITTED"]
        assert CANARY not in _text(result)
        assert provider.requests == 0

    def test_literal_destination_outside_the_policy_is_an_error(self, provider: _CountingProvider) -> None:
        _set_policy(allowed_destinations=["store.example.internal"])

        result = _validate(
            node_type="ingest_source",
            config=_s3(secret_key=_ref("s3/secret"), endpoint_url="https://attacker.example.net"),
        )

        assert _codes(result, kind="errors") == ["VAULT_DESTINATION_NOT_PERMITTED"]
        assert "provider_config.endpoint_url" in _text(result)
        assert "attacker.example.net" not in _text(result)
        assert provider.requests == 0

    def test_unregistered_provider_is_a_warning_and_not_an_error(self, provider: _CountingProvider) -> None:
        clear_providers()
        _set_policy()

        result = _validate(node_type="ingest_source", config=_s3(secret_key="vault://elsewhere/s3/secret#key"))

        assert _codes(result, kind="errors") == []
        assert _codes(result, kind="warnings") == ["VAULT_PROVIDER_NOT_REGISTERED"]
        assert "elsewhere" in _text(result)
        assert "provider_config.secret_key" in _text(result)
        assert provider.requests == 0


def test_the_validation_sentinel_is_a_plain_string_that_satisfies_url_checks() -> None:
    sentinel = DocpipeConstants.VALIDATION_SECRET_SENTINEL

    assert type(sentinel) is str
    assert sentinel.startswith("https://")


def test_ingest_validation_runs_adapter_checks_for_a_sentinel_filled_config() -> None:
    """The old guard skipped adapter validation whenever a reference was present; it is gone."""
    sentinel = DocpipeConstants.VALIDATION_SECRET_SENTINEL
    operator = IngestSourceOperator(
        config={
            "provider": "s3",
            "provider_config": {"access_key": sentinel, "bucket": sentinel},
            DocpipeConstants.VALIDATING_FLOW: True,
        }
    )
    errors: list[str] = []

    operator.validate(errors=errors, warnings=[], available_features=[])

    assert any("secret_key" in error for error in errors)


class TestUntrustedCustomOperatorFinding:
    """An untrusted custom operator is held to ``custom_operator_allowed_paths`` and the error names that setting."""

    def test_path_finding_names_the_custom_operator_setting(self, provider: _CountingProvider) -> None:
        from docpipe.core.operators.abstract_operator import OperatorCategory
        from docpipe.core.orchestration.flow_validator import FlowValidator, ValidateStepResults
        from docpipe.core.orchestration.operator_loader.ports.operator_source import OperatorInfo, TrustClass
        from docpipe.core.orchestration.operator_loader.untrusted_descriptor import build_untrusted_descriptor

        _set_policy(allowed_paths=["hashicorp:**"])
        info = OperatorInfo(
            name="Cust",
            short_name="cust",
            module_path="cust",
            category=OperatorCategory.Functional.value,
            source_location="x",
            trust_class=TrustClass.UNTRUSTED,
            source_file="/nonexistent/cust.py",
            static_metadata={"secret_fields": ["api_key"]},
        )
        descriptor = build_untrusted_descriptor(operator_info=info)
        results = ValidateStepResults(available_features={}, errors=[], warnings=[])

        blocking = FlowValidator._report_reference_findings(
            operator_class=descriptor,
            config={"api_key": _ref("custom/svc")},
            op_def={"id": "n1", "name": "n1", "operator": "cust"},
            validate_results=results,
        )

        assert blocking is True
        assert "secrets.vault.custom_operator_allowed_paths" in _text({"errors": results.errors, "warnings": []})
        assert provider.requests == 0
