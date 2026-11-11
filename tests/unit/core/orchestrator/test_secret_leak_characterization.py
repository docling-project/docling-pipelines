# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Characterization tests for secret resolution leak to downstream nodes on current main.

These tests document and pin existing behavior:
1. Ingest source operator config with vault:// reference is copied into global_config['ingest_source'].
2. Downstream node executor resolves all vault references in its merged params (including global_config).
3. The downstream node receives the resolved canary secret in its executor params / global_config.
"""

import pytest

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.orchestration.python.python_orchestrator import PythonOrchestrator
from docpipe.exceptions.docpipe_exceptions import ConfigurationError, ExternalServiceError
from docpipe.integrations.secrets.secret_provider import (
    SecretProvider,
    clear_providers,
    register_provider,
)


class FakeOrchestratorSecretProvider(SecretProvider):
    """Test SecretProvider for orchestrator characterization tests."""

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


class TestDownstreamNodeSecretLeakCharacterization:
    """Characterization tests documenting that downstream nodes receive resolved ingest secrets."""

    def test_downstream_executor_resolves_ingest_vault_secret_in_global_config(self) -> None:
        """On current main, downstream PythonOperatorExecutor resolves vault secret in global_config['ingest_source']."""
        canary_secret = "CANARY_S3_SECRET_KEY_99999"  # pragma: allowlist secret
        provider = FakeOrchestratorSecretProvider(secrets={"s3/creds": {"secret_key": canary_secret}})
        register_provider(name="fake", provider=provider)

        # Ingest operator definition with vault reference
        ingest_op_def = {
            "id": "ingest_node",
            "name": "ingest_source_node",
            "operator": "ingest_source",
            "config": {
                "provider": "s3",
                "provider_config": {
                    "bucket": "my-bucket",
                    "access_key": "my-access-key",
                    "secret_key": "vault://fake/s3/creds#secret_key",  # pragma: allowlist secret
                },
            },
        }

        # 1. Orchestrator populates global_config with unresolved provider_config
        orchestrator = PythonOrchestrator()
        global_config: dict = {
            DocpipeConstants.JOB_ID: "job-1",
            DocpipeConstants.JOB_RUN_ID: "run-1",
        }
        orchestrator._populate_ingest_source_config(
            ingest_operator=ingest_op_def,
            global_config=global_config,
        )

        # Assert global_config now contains the unresolved vault reference
        ingest_source_config = global_config.get("ingest_source", {})
        assert ingest_source_config.get("provider_config", {}).get("secret_key") == "vault://fake/s3/creds#secret_key"

        # 2. Downstream node (e.g. noop) executor is created with global_config merged into params
        downstream_op_def = {
            "id": "downstream_node",
            "name": "noop_node",
            "operator": "noop",
            "config": {},
        }
        executor = orchestrator.create_executor(
            op_def=downstream_op_def,
            global_config=global_config,
        )

        # 3. When executor resolves operator params, it resolves vault references across all params
        # including global_config['ingest_source']!
        resolved_params = executor._resolve_operator_params()

        # On current main, this exposes the resolved canary secret to the downstream node
        resolved_ingest_secret = resolved_params.get("ingest_source", {}).get("provider_config", {}).get("secret_key")
        assert resolved_ingest_secret == canary_secret
