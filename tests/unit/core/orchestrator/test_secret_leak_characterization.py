# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Regression tests: a downstream node never sees, or resolves, the ingest node's secret.

The A0 characterization pinned the leak (the ingest ``provider_config`` was copied unresolved
into ``global_config['ingest_source']`` and every node resolved it). Task B.4 closes it:
1. ``global_config['ingest_source']`` carries naming facts only, no credential field.
2. A downstream node resolves only its own declared fields, so it makes no provider request.
3. The canary secret appears nowhere in the downstream node's configuration.
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
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader


class FakeOrchestratorSecretProvider(SecretProvider):
    """Test SecretProvider for orchestrator characterization tests."""

    def __init__(self, *, secrets: dict[str, dict[str, str]]) -> None:
        self._secrets = secrets
        self.calls: list[tuple[str, str | None]] = []

    def authenticate(self) -> None:
        pass

    def get_secret(self, *, path: str, key: str | None = None) -> str:
        self.calls.append((path, key))
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
    """Ensure providers and the deployment policy are cleared before and after tests."""
    clear_providers()
    DocpipeConfigLoader.reset()
    yield
    clear_providers()
    DocpipeConfigLoader.reset()


class TestDownstreamNodeSecretIsolation:
    """A downstream node neither receives nor resolves the ingest node's reference."""

    CANARY = "CANARY_S3_SECRET_KEY_99999"  # pragma: allowlist secret
    REFERENCE = "vault://fake/s3/creds#secret_key"  # pragma: allowlist secret

    def _ingest_op_def(self) -> dict:
        return {
            "id": "ingest_node",
            "name": "ingest_source_node",
            "operator": "ingest_source",
            "config": {
                "provider": "s3",
                "provider_config": {
                    "bucket": "my-bucket",
                    "access_key": "my-access-key",
                    "secret_key": self.REFERENCE,
                },
            },
        }

    def _downstream_op_def(self) -> dict:
        return {"id": "downstream_node", "name": "noop_node", "operator": "noop", "config": {}}

    def _global_config(self) -> dict:
        return {
            DocpipeConstants.JOB_ID: "job-1",
            DocpipeConstants.JOB_RUN_ID: "run-1",
            DocpipeConstants.FLOW_DEFINITION: {
                DocpipeConstants.DAG: [self._ingest_op_def(), self._downstream_op_def()],
            },
        }

    def _provider(self) -> FakeOrchestratorSecretProvider:
        provider = FakeOrchestratorSecretProvider(secrets={"s3/creds": {"secret_key": self.CANARY}})
        register_provider(name="fake", provider=provider)
        return provider

    def test_global_config_carries_no_credential_field(self) -> None:
        orchestrator = PythonOrchestrator()
        global_config = self._global_config()
        orchestrator._populate_ingest_source_config(ingest_operator=self._ingest_op_def(), global_config=global_config)

        ingest_source = global_config["ingest_source"]
        assert ingest_source["provider"] == "s3"
        assert "secret_key" not in ingest_source["provider_config"]
        assert "access_key" not in ingest_source["provider_config"]
        assert self.REFERENCE not in repr(ingest_source)

    def test_downstream_node_makes_no_provider_request(self) -> None:
        DocpipeConfigLoader._config = {"secrets": {"vault": {"allowed_paths": ["*:**"]}}}
        provider = self._provider()
        orchestrator = PythonOrchestrator()
        global_config = self._global_config()
        orchestrator._populate_ingest_source_config(ingest_operator=self._ingest_op_def(), global_config=global_config)

        executor = orchestrator.create_executor(op_def=self._downstream_op_def(), global_config=global_config)
        executor.get_operator()

        assert provider.calls == []
        assert self.CANARY not in repr(executor._params)

    def test_downstream_node_survives_a_vault_outage(self) -> None:
        """No provider is registered at all: a node without its own references still builds."""
        orchestrator = PythonOrchestrator()
        global_config = self._global_config()
        orchestrator._populate_ingest_source_config(ingest_operator=self._ingest_op_def(), global_config=global_config)

        executor = orchestrator.create_executor(op_def=self._downstream_op_def(), global_config=global_config)

        assert executor.get_operator() is not None
