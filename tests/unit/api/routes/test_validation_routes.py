# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for Validation API routes."""

from typing import Any
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from docpipe.api.auth.dependencies import get_current_user
from docpipe.api.routes.validation import (
    get_flow_enrichment_service,
    get_validation_service,
    validation_router,
)
from docpipe.core.assets.flows.application.services.flow_enrichment_service import FlowEnrichmentService
from docpipe.core.assets.flows.application.services.validation_service import ValidationService
from docpipe.exceptions.docpipe_exceptions import TROUBLESHOOTING_DOCS_URL, FlowValidationException
from tests.unit.api.routes.conftest import mock_current_user


@pytest.fixture
def app():
    """Create FastAPI app with validation router and error handlers.

    Registers the same exception handlers as main.py to ensure tests
    match runtime behavior.
    """
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from docpipe.api.middleware.error_handler import (
        docpipe_exception_handler,
        generic_exception_handler,
        http_exception_handler,
        validation_exception_handler,
    )
    from docpipe.exceptions.docpipe_exceptions import DocpipeException

    app = FastAPI()
    app.include_router(validation_router)
    app.dependency_overrides[get_current_user] = mock_current_user

    # Register exception handlers in same order as main.py
    app.add_exception_handler(DocpipeException, docpipe_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    return app


@pytest.fixture
def client(app):
    """Create FastAPI test client."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def mock_service():
    """Create mock ValidationService."""
    return Mock(spec=ValidationService)


@pytest.fixture
def override_service(app, mock_service):
    """Override the get_validation_service dependency."""
    app.dependency_overrides[get_validation_service] = lambda: mock_service
    yield mock_service
    app.dependency_overrides.clear()


class TestValidateFlowEndpoint:
    """Tests for POST /validation/validate_flow endpoint."""

    def test_validate_valid_flow_returns_200_with_succeeded_status(self, client, override_service, sample_flow_data):
        """Test validating a valid flow returns 200 with SUCCEEDED status."""
        # Arrange
        override_service.validate_flow.return_value = {
            "status": "SUCCEEDED",
            "message": "Flow validation succeeded.",
            "errors": [],
            "warnings": [],
        }

        # Act
        response = client.post("/validation/validate_flow", json=sample_flow_data)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "SUCCEEDED"
        assert data["message"] == "Flow validation succeeded."
        assert data["errors"] == []
        assert data["warnings"] == []
        override_service.validate_flow.assert_called_once()

    def test_validate_invalid_flow_returns_200_with_failed_status(self, client, override_service, sample_flow_data):
        """Test validating an invalid flow returns 200 with FAILED status."""
        # Arrange
        override_service.validate_flow.return_value = {
            "status": "FAILED",
            "message": "Flow validation failed.",
            "errors": [
                {
                    "code": "OPERATOR_NOT_FOUND",
                    "message": "Operator not found: docpipe.operators.NonExistentOperator",
                    "node_id": "550e8400-e29b-41d4-a716-446655440001",
                }
            ],
            "warnings": [],
        }

        # Act
        response = client.post("/validation/validate_flow", json=sample_flow_data)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "FAILED"
        assert data["message"] == "Flow validation failed."
        assert len(data["errors"]) == 1
        assert data["errors"][0]["code"] == "OPERATOR_NOT_FOUND"
        assert data["warnings"] == []

    def test_validate_flow_with_warnings_returns_200_with_warnings_status(
        self, client, override_service, sample_flow_data
    ):
        """Test validating a flow with warnings returns SUCCEEDED_WITH_WARNINGS status."""
        # Arrange
        override_service.validate_flow.return_value = {
            "status": "SUCCEEDED_WITH_WARNINGS",
            "message": "Flow validation succeeded with warnings.",
            "errors": [],
            "warnings": [
                {
                    "code": "MISSING_FEATURE",
                    "message": "Node is missing recommended feature: content",
                    "node_id": "550e8400-e29b-41d4-a716-446655440001",
                }
            ],
        }

        # Act
        response = client.post("/validation/validate_flow", json=sample_flow_data)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "SUCCEEDED_WITH_WARNINGS"
        assert len(data["warnings"]) == 1
        assert data["warnings"][0]["code"] == "MISSING_FEATURE"
        assert data["errors"] == []

    def test_validate_flow_returns_correct_response_structure(self, client, override_service, sample_flow_data):
        """Test that response has correct FlowValidationResponse structure."""
        # Arrange
        override_service.validate_flow.return_value = {
            "status": "SUCCEEDED",
            "message": "Flow validation succeeded.",
            "errors": [],
            "warnings": [],
        }

        # Act
        response = client.post("/validation/validate_flow", json=sample_flow_data)

        # Assert
        assert response.status_code == 200
        data = response.json()

        # Verify structure
        assert "status" in data
        assert "message" in data
        assert "errors" in data
        assert "warnings" in data
        assert isinstance(data["errors"], list)
        assert isinstance(data["warnings"], list)

    def test_validate_flow_with_multiple_errors_returns_all_errors(self, client, override_service, sample_flow_data):
        """Test that multiple validation errors are all returned."""
        # Arrange
        override_service.validate_flow.return_value = {
            "status": "FAILED",
            "message": "Flow validation failed.",
            "errors": [
                {
                    "code": "OPERATOR_NOT_FOUND",
                    "message": "Operator not found",
                    "node_id": "550e8400-e29b-41d4-a716-446655440001",
                },
                {
                    "code": "MISSING_REQUIRED_PARAM",
                    "message": "Missing required parameter",
                    "node_id": "550e8400-e29b-41d4-a716-446655440002",
                },
                {
                    "code": "CIRCULAR_DEPENDENCY",
                    "message": "Circular dependency detected",
                    "node_id": "550e8400-e29b-41d4-a716-446655440003",
                },
            ],
            "warnings": [],
        }

        # Act
        response = client.post("/validation/validate_flow", json=sample_flow_data)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "FAILED"
        assert len(data["errors"]) == 3
        assert all("code" in error for error in data["errors"])
        assert all("message" in error for error in data["errors"])

    def test_validate_flow_with_elyra_format_parameter(self, client, override_service):
        """Test validating flow with is_elyra query parameter."""
        # Arrange - Use Elyra format for this test
        elyra_flow_data = {
            "name": "Test Flow",
            "description": "A test flow for unit testing",
            "definition": {
                "doc_type": "pipeline",
                "version": "3.0",
                "id": "test-pipeline-id",
                "primary_pipeline": "test-pipeline-id",
                "pipelines": [
                    {
                        "id": "test-pipeline-id",
                        "nodes": [
                            {
                                "id": "node1",
                                "type": "execution_node",
                                "op": "execute-notebook-node",
                            }
                        ],
                        "app_data": {"ds_flow": {}, "ui_data": {}},
                    }
                ],
                "schemas": [],
            },
            "tags": ["test", "unit-test"],
            "container_kind": "project",
            "container_id": "550e8400-e29b-41d4-a716-446655440000",
            "is_hidden": False,
            "flow_version": "2.0",
            "job_id": "660e8400-e29b-41d4-a716-446655440000",
            "created_by": "test_user",
        }
        override_service.validate_flow.return_value = {
            "status": "SUCCEEDED",
            "message": "Flow validation succeeded.",
            "errors": [],
            "warnings": [],
        }

        # Act
        response = client.post("/validation/validate_flow?is_elyra=true", json=elyra_flow_data)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "SUCCEEDED"
        # Verify is_elyra was passed to service
        call_kwargs = override_service.validate_flow.call_args[1]
        assert call_kwargs.get("is_elyra") is True

    def test_validate_flow_with_authoring_format_parameter(self, client, override_service, sample_flow_data):
        """Test validating flow with is_elyra=false (authoring format)."""
        # Arrange
        override_service.validate_flow.return_value = {
            "status": "SUCCEEDED",
            "message": "Flow validation succeeded.",
            "errors": [],
            "warnings": [],
        }

        # Act
        response = client.post("/validation/validate_flow?is_elyra=false", json=sample_flow_data)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "SUCCEEDED"
        # Verify is_elyra was passed to service as False
        call_kwargs = override_service.validate_flow.call_args[1]
        assert call_kwargs.get("is_elyra") is False

    def test_validate_flow_response_content_type(self, client, override_service, sample_flow_data):
        """Test that response has correct content type."""
        # Arrange
        override_service.validate_flow.return_value = {
            "status": "SUCCEEDED",
            "message": "Flow validation succeeded.",
            "errors": [],
            "warnings": [],
        }

        # Act
        response = client.post("/validation/validate_flow", json=sample_flow_data)

        # Assert
        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]

    def test_validate_flow_handles_service_exception(self, client, override_service, sample_flow_data):
        """Test that service exceptions are handled properly."""
        # Arrange
        override_service.validate_flow.return_value = {
            "status": "FAILED",
            "message": "Internal validation error",
            "errors": [{"code": "INTERNAL_ERROR", "message": "Unexpected error during validation"}],
            "warnings": [],
        }

        # Act
        response = client.post("/validation/validate_flow", json=sample_flow_data)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "FAILED"
        assert len(data["errors"]) > 0


class TestValidationAlertDTOStructure:
    """Tests for ValidationAlertDTO structure and validation."""

    def test_validation_alert_dto_accepts_all_fields(self, client, override_service, sample_flow_data):
        """Test that ValidationAlertDTO accepts all expected fields."""
        # Arrange
        override_service.validate_flow.return_value = {
            "status": "FAILED",
            "message": "Flow validation failed.",
            "errors": [
                {
                    "code": "OPERATOR_NOT_FOUND",
                    "message": "Operator not found",
                    "message_code": "operator.not_found",
                    "node_id": "550e8400-e29b-41d4-a716-446655440001",
                    "node_name": "Ingest Node",
                    "operator": "IngestSourceOperator",
                }
            ],
            "warnings": [],
        }

        # Act
        response = client.post("/validation/validate_flow", json=sample_flow_data)

        # Assert
        assert response.status_code == 200
        data = response.json()
        error = data["errors"][0]
        assert error["code"] == "OPERATOR_NOT_FOUND"
        assert error["message"] == "Operator not found"
        assert error["message_code"] == "operator.not_found"
        assert error["node_id"] == "550e8400-e29b-41d4-a716-446655440001"
        assert error["node_name"] == "Ingest Node"
        assert error["operator"] == "IngestSourceOperator"

    def test_validation_alert_dto_accepts_minimal_fields(self, client, override_service, sample_flow_data):
        """Test that ValidationAlertDTO works with minimal fields."""
        # Arrange
        override_service.validate_flow.return_value = {
            "status": "FAILED",
            "message": "Flow validation failed.",
            "errors": [{"code": "ERROR", "message": "Validation error"}],
            "warnings": [],
        }

        # Act
        response = client.post("/validation/validate_flow", json=sample_flow_data)

        # Assert
        assert response.status_code == 200
        data = response.json()
        error = data["errors"][0]
        assert error["code"] == "ERROR"
        assert error["message"] == "Validation error"

    def test_validation_alert_dto_accepts_extra_fields(self, client, override_service, sample_flow_data):
        """Test that ValidationAlertDTO accepts extra fields via model_config.

        Note: Pydantic's extra="allow" allows extra fields during validation,
        but they are not included in the serialized output by default.
        This test verifies that the DTO doesn't reject extra fields during validation.
        """
        # Arrange
        override_service.validate_flow.return_value = {
            "status": "FAILED",
            "message": "Flow validation failed.",
            "errors": [
                {
                    "code": "ERROR",
                    "message": "Validation error",
                    "extra_field": "extra_value",
                    "another_field": 123,
                }
            ],
            "warnings": [],
        }

        # Act
        response = client.post("/validation/validate_flow", json=sample_flow_data)

        # Assert
        assert response.status_code == 200
        data = response.json()
        error = data["errors"][0]
        assert error["code"] == "ERROR"
        assert error["message"] == "Validation error"
        # Extra fields are accepted during validation but not serialized by default
        # The important thing is that the request doesn't fail


class TestFlowValidationResponseStructure:
    """Tests for FlowValidationResponse structure and validation."""

    def test_flow_validation_response_requires_status(self, client, override_service, sample_flow_data):
        """Test that status field is required in response."""
        # Arrange
        override_service.validate_flow.return_value = {
            "status": "SUCCEEDED",
            "message": None,
            "errors": [],
            "warnings": [],
        }

        # Act
        response = client.post("/validation/validate_flow", json=sample_flow_data)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "SUCCEEDED"

    def test_flow_validation_response_accepts_null_message(self, client, override_service, sample_flow_data):
        """Test that message field can be null."""
        # Arrange
        override_service.validate_flow.return_value = {
            "status": "SUCCEEDED",
            "message": None,
            "errors": [],
            "warnings": [],
        }

        # Act
        response = client.post("/validation/validate_flow", json=sample_flow_data)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["message"] is None

    def test_flow_validation_response_includes_empty_arrays(self, client, override_service, sample_flow_data):
        """Test that errors and warnings are empty arrays when no issues."""
        # Arrange
        override_service.validate_flow.return_value = {
            "status": "SUCCEEDED",
            "message": "Flow validation succeeded.",
            "errors": [],
            "warnings": [],
        }

        # Act
        response = client.post("/validation/validate_flow", json=sample_flow_data)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["errors"] == []
        assert data["warnings"] == []
        assert isinstance(data["errors"], list)
        assert isinstance(data["warnings"], list)


# ---------------------------------------------------------------------------
# Fixtures — enrich_flow_features
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_enrichment_service():
    """Create mock FlowEnrichmentService."""
    return Mock(spec=FlowEnrichmentService)


@pytest.fixture
def override_enrichment_service(app, mock_enrichment_service):
    """Override the get_flow_enrichment_service dependency."""
    app.dependency_overrides[get_flow_enrichment_service] = lambda: mock_enrichment_service
    yield mock_enrichment_service
    app.dependency_overrides.clear()


def _minimal_elyra_flow(**extra: Any) -> dict[str, Any]:
    """Return a minimal valid Elyra pipeline body."""
    return {
        "doc_type": "pipeline",
        "version": "3.0",
        "pipelines": [
            {
                "nodes": [
                    {"id": "node-1", "op": "ingest_source", "parameters": {}},
                    {"id": "node-2", "op": "chunker", "parameters": {}},
                ],
                "app_data": {"ds_flow": {"name": "Test Flow", "global_config": {}}},
            }
        ],
        **extra,
    }


def _enriched_flow() -> dict[str, Any]:
    """Return a mock enriched Elyra flow as the service would return it."""
    return {
        "doc_type": "pipeline",
        "version": "3.0",
        "pipelines": [
            {
                "nodes": [
                    {
                        "id": "node-1",
                        "op": "ingest_source",
                        "parameters": {
                            "available_features": {},
                            "input_features": {},
                            "output_features": {
                                "id": {
                                    "name": "id",
                                    "type": "string",
                                    "node_id": "node-1",
                                    "description": "",
                                    "available_for_filter": True,
                                    "available_for_vector_db": False,
                                    "tags": [],
                                },
                                "content": {
                                    "name": "content",
                                    "type": "string",
                                    "node_id": "node-1",
                                    "description": "",
                                    "available_for_filter": True,
                                    "available_for_vector_db": False,
                                    "tags": [],
                                },
                            },
                        },
                    },
                    {
                        "id": "node-2",
                        "op": "chunker",
                        "parameters": {
                            "available_features": {},
                            "input_features": {
                                "content": {
                                    "name": "content",
                                    "type": "string",
                                    "node_id": "node-1",
                                    "description": "",
                                    "available_for_filter": True,
                                    "available_for_vector_db": False,
                                    "tags": [],
                                },
                            },
                            "output_features": {
                                "chunk": {
                                    "name": "chunk",
                                    "type": "string",
                                    "node_id": "node-2",
                                    "description": "",
                                    "available_for_filter": True,
                                    "available_for_vector_db": False,
                                    "tags": [],
                                },
                            },
                        },
                    },
                ],
                "app_data": {"ds_flow": {"name": "Test Flow", "global_config": {}}},
            }
        ],
    }


# ---------------------------------------------------------------------------
# Tests: happy path
# ---------------------------------------------------------------------------


class TestEnrichFlowFeaturesEndpoint:
    """Tests for POST /validation/enrich_flow_features."""

    def test_returns_200_with_enriched_flow(self, client, override_enrichment_service):
        """Valid Elyra flow returns 200 with enriched flow body."""
        override_enrichment_service.enrich_flow_with_features.return_value = _enriched_flow()

        response = client.post("/validation/enrich_flow_features", json=_minimal_elyra_flow())

        assert response.status_code == 200
        assert "pipelines" in response.json()

    def test_response_nodes_contain_feature_metadata_keys(self, client, override_enrichment_service):
        """Each node in the response has input/output/available_features in parameters."""
        override_enrichment_service.enrich_flow_with_features.return_value = _enriched_flow()

        response = client.post("/validation/enrich_flow_features", json=_minimal_elyra_flow())

        for node in response.json()["pipelines"][0]["nodes"]:
            assert "input_features" in node["parameters"]
            assert "output_features" in node["parameters"]
            assert "available_features" in node["parameters"]

    def test_passes_full_request_body_to_service(self, client, override_enrichment_service):
        """The entire request body is forwarded to enrich_flow_with_features."""
        flow = _minimal_elyra_flow()
        override_enrichment_service.enrich_flow_with_features.return_value = _enriched_flow()

        client.post("/validation/enrich_flow_features", json=flow)

        call_kwargs = override_enrichment_service.enrich_flow_with_features.call_args[1]
        assert call_kwargs["flow_definition"]["doc_type"] == "pipeline"
        assert call_kwargs["flow_definition"]["pipelines"] == flow["pipelines"]

    def test_service_called_exactly_once(self, client, override_enrichment_service):
        """Service is called exactly once per request."""
        override_enrichment_service.enrich_flow_with_features.return_value = _enriched_flow()

        client.post("/validation/enrich_flow_features", json=_minimal_elyra_flow())

        override_enrichment_service.enrich_flow_with_features.assert_called_once()

    def test_response_content_type_is_json(self, client, override_enrichment_service):
        """Response Content-Type is application/json."""
        override_enrichment_service.enrich_flow_with_features.return_value = _enriched_flow()

        response = client.post("/validation/enrich_flow_features", json=_minimal_elyra_flow())

        assert "application/json" in response.headers["content-type"]

    def test_response_preserves_top_level_elyra_keys(self, client, override_enrichment_service):
        """Keys outside pipelines (doc_type, version) are preserved in the response."""
        override_enrichment_service.enrich_flow_with_features.return_value = _enriched_flow()

        response = client.post("/validation/enrich_flow_features", json=_minimal_elyra_flow())

        data = response.json()
        assert data["doc_type"] == "pipeline"
        assert data["version"] == "3.0"


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------


class TestEnrichFlowFeaturesErrorHandling:
    """Tests for error responses from enrich_flow_features.

    Both ValueError and FlowValidationException bubble up to the middleware.
    ValueError → generic_exception_handler → 400 invalid_parameter.
    FlowValidationException(status_code=400) → docpipe_exception_handler → 400.
    """

    def test_value_error_returns_400(self, client, override_enrichment_service):
        """Service raising ValueError → 400."""
        override_enrichment_service.enrich_flow_with_features.side_effect = ValueError("flow_definition is required")

        response = client.post("/validation/enrich_flow_features", json={})

        assert response.status_code == 400

    def test_value_error_code_is_invalid_parameter(self, client, override_enrichment_service):
        """ValueError is handled by generic_exception_handler with code 'invalid_parameter'."""
        override_enrichment_service.enrich_flow_with_features.side_effect = ValueError("flow_definition is required")

        response = client.post("/validation/enrich_flow_features", json={})

        errors = response.json()["errors"]
        assert errors[0]["code"] == "invalid_parameter"
        assert "flow_definition is required" in errors[0]["message"]

    def test_value_error_custom_message_surfaced(self, client, override_enrichment_service):
        """ValueError message is preserved in the 400 response."""
        override_enrichment_service.enrich_flow_with_features.side_effect = ValueError("Missing pipelines key")

        response = client.post("/validation/enrich_flow_features", json={"doc_type": "pipeline"})

        assert response.status_code == 400
        assert "Missing pipelines key" in response.json()["errors"][0]["message"]

    def test_flow_validation_exception_returns_400(self, client, override_enrichment_service):
        """FlowValidationException(status_code=400) → docpipe_exception_handler → 400."""
        override_enrichment_service.enrich_flow_with_features.side_effect = FlowValidationException(
            errors=[{"code": "CYCLE_DETECTED", "message": "Dependency cycle in DAG"}]
        )

        response = client.post("/validation/enrich_flow_features", json=_minimal_elyra_flow())

        assert response.status_code == 400

    def test_flow_validation_exception_error_code(self, client, override_enrichment_service):
        """FlowValidationException is handled by docpipe_exception_handler."""
        override_enrichment_service.enrich_flow_with_features.side_effect = FlowValidationException(
            errors=[{"code": "CYCLE_DETECTED", "message": "Dependency cycle in DAG"}]
        )

        response = client.post("/validation/enrich_flow_features", json=_minimal_elyra_flow())

        data = response.json()
        assert "errors" in data
        assert response.status_code == 400
        assert "more_info" not in data["errors"][0]

    def test_flow_validation_exception_with_empty_errors_returns_400(self, client, override_enrichment_service):
        """FlowValidationException with no errors still returns 400."""
        override_enrichment_service.enrich_flow_with_features.side_effect = FlowValidationException(errors=[])

        response = client.post("/validation/enrich_flow_features", json=_minimal_elyra_flow())

        assert response.status_code == 400
        assert response.json()["errors"][0]["more_info"] == f"{TROUBLESHOOTING_DOCS_URL}#issue-flow-validation-failed"


class TestValidateFlowRejectedConfigBoundary:
    """Rejected operator configuration must not be echoed by the validate_flow boundary."""

    SENTINEL = "SENTINEL_ROUTE_CONFIG_7a2f"

    def test_rejected_input_event_value_is_omitted(self, client, sample_flow_data, fixtures_customer_support_dir):
        """Use the real validation service so the alert exercises operator configuration rendering."""
        ingest_config = sample_flow_data["flow"][0]["config"]
        ingest_config["connection_params"]["paths"] = [str(fixtures_customer_support_dir)]
        ingest_config["input_event"] = {
            "event_id": "6f1d2c3b-4a5e-4f60-8b7c-9d0e1f2a3b4c",
            "event_timestamp": "2024-05-01T12:00:00Z",
            "routing_key": "invoices_created",
            "operation": self.SENTINEL,
            "file_reference": "invoices/2024/invoice-001.pdf",
        }
        sample_flow_data["flow"][1]["type"] = "noop"

        response = client.post("/validation/validate_flow", json=sample_flow_data)

        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "FAILED"
        assert any(
            error["message_code"] == "OPERATOR_VALIDATION_FAILED" and "operation" in error["message"]
            for error in result["errors"]
        )
        assert self.SENTINEL not in response.text
        assert "input_value" not in response.text
