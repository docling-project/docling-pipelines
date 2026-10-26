"""Missing ingest providers produce actionable errors through public entry points."""

import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from docpipe.api.routes.validation import validation_router
from docpipe.cli.docpipe_cli import validate_flow_definition
from docpipe.core.assets.flows.application.services.validation_service import ValidationService
from docpipe.core.orchestration.flow_executor import FlowExecutor
from docpipe.core.orchestration.orchestrator_factory import OrchestratorFactory
from docpipe.exceptions.docpipe_exceptions import FlowValidationException
from docpipe.exceptions.error_messages import ValidationCodeMessages
from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager


@pytest.fixture(params=[{}, {"provider": None}, {"provider": ""}, {"provider": " \t\n "}])
def incomplete_flow(request):
    """A connected flow isolates provider errors from unrelated structural failures."""
    return {
        "flow_name": "missing-provider",
        "flow": [
            {"type": "ingest_source", "name": "ingest", "config": request.param},
            {"type": "noop", "name": "end", "config": {}, "depends_on": ["ingest"]},
        ],
    }


@pytest.mark.parametrize("is_elyra", [False, True])
def test_rest_validation_identifies_missing_provider_node(*, incomplete_flow, is_elyra):
    """Canvas post-save and direct API validation share the real operator validator."""
    app = FastAPI()
    app.include_router(validation_router)
    body = incomplete_flow
    if is_elyra:
        ingest_id, end_id, pipeline_id = (str(uuid4()) for _ in range(3))
        body = {
            "name": "missing-provider",
            "definition": {
                "doc_type": "pipeline",
                "version": "3.0",
                "id": str(uuid4()),
                "primary_pipeline": pipeline_id,
                "pipelines": [
                    {
                        "id": pipeline_id,
                        "nodes": [
                            {
                                "id": ingest_id,
                                "type": "execution_node",
                                "op": "ingest_source",
                                "app_data": {"ui_data": {"label": "ingest"}},
                                "parameters": incomplete_flow["flow"][0]["config"],
                                "inputs": [],
                                "outputs": [{"id": "out"}],
                            },
                            {
                                "id": end_id,
                                "type": "execution_node",
                                "op": "noop",
                                "app_data": {"ui_data": {"label": "end"}},
                                "parameters": {},
                                "inputs": [{"id": "in", "links": [{"node_id_ref": ingest_id, "port_id_ref": "out"}]}],
                                "outputs": [],
                            },
                        ],
                    }
                ],
                "schemas": [],
            },
        }

    with TestClient(app) as client:
        response = client.post("/validation/validate_flow", params={"is_elyra": is_elyra}, json=body)

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "FAILED"
    assert len(result["errors"]) == 1
    error = result["errors"][0]
    assert error["message_code"] == "INGEST_PROVIDER_MISSING"
    assert error["message"] == ValidationCodeMessages.INGEST_PROVIDER_MISSING.value
    assert error["operator"] == "ingest_source"
    assert error["node_name"] == "ingest"
    assert error["node_id"]
    if is_elyra:
        assert error["node_id"] == ingest_id


def test_library_validation_reports_missing_provider(incomplete_flow):
    """The library returns an invalid result containing the provider-selection error."""
    # Preserve pytest's logging setup for subsequent caplog assertions.
    result = DocpipeFlowManager(flow_def=incomplete_flow, configure_logging=False).validate()

    assert result["valid"] is False
    assert len(result["errors"]) == 1
    assert "INGEST_PROVIDER_MISSING" in result["errors"][0]
    assert ValidationCodeMessages.INGEST_PROVIDER_MISSING.value in result["errors"][0]


def test_cli_validation_reports_missing_provider(*, incomplete_flow, tmp_path: Path):
    """Both CLI validation commands delegate to this validation function."""
    path = tmp_path / "flow.json"
    path.write_text(json.dumps(incomplete_flow))

    with patch("docpipe.cli.docpipe_cli.logger") as logger:
        assert validate_flow_definition(flow_file=str(path)) is False

    assert ValidationCodeMessages.INGEST_PROVIDER_MISSING.value in str(logger.error.call_args_list)
    logger.exception.assert_not_called()


def test_execution_validation_rejects_missing_provider(incomplete_flow):
    """API job runs, CLI execution, and library execution use the same executor."""
    internal = ValidationService()._convert_to_dag_flow(flow_definition=incomplete_flow, is_elyra=False)
    executor = FlowExecutor(flow_def=internal, orchestrator=OrchestratorFactory.create_orchestrator())

    with pytest.raises(FlowValidationException) as exc_info:
        executor._validate_flow(params={})

    assert len(exc_info.value.errors) == 1
    error = exc_info.value.errors[0]
    assert error["message_code"] == "INGEST_PROVIDER_MISSING"
    assert error["message"] == ValidationCodeMessages.INGEST_PROVIDER_MISSING.value
    assert error["node_name"] == "ingest"
