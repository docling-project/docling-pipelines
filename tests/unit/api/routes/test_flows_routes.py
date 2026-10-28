"""Unit tests for Flow API routes."""

from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from docpipe.api.auth.dependencies import get_current_user
from docpipe.api.routes.flows import flows_router, get_flow_service
from docpipe.core.assets.flows.application.services.flow_service import FlowService
from docpipe.exceptions.docpipe_exceptions import (
    FlowAlreadyExistsException,
    FlowNotFoundException,
    FlowStorageException,
)
from tests.unit.api.routes.conftest import mock_current_user


@pytest.fixture
def app():
    """Create FastAPI app with flows router and error handlers.

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
    app.include_router(flows_router)
    app.dependency_overrides[get_current_user] = mock_current_user

    # Register exception handlers in same order as main.py
    app.add_exception_handler(DocpipeException, docpipe_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    return app


@pytest.fixture
def client(app):
    """Create FastAPI test client.

    Uses raise_server_exceptions=False to ensure validation errors are handled
    by the registered exception handlers and converted to proper HTTP responses,
    rather than being raised directly to the test.
    """
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def mock_service():
    """Create mock FlowService."""
    return Mock(spec=FlowService)


@pytest.fixture
def override_service(app, mock_service):
    """Override the get_flow_service dependency."""
    app.dependency_overrides[get_flow_service] = lambda: mock_service
    yield mock_service
    app.dependency_overrides.clear()


class TestCreateFlowEndpoint:
    """Tests for POST /flows endpoint."""

    def test_create_flow_with_valid_data_returns_201(self, client, override_service, sample_flow_with_id):
        """Test creating a flow with valid data returns 201."""
        # Arrange
        override_service.create_flow.return_value = sample_flow_with_id
        request_data = {
            "name": "Test Flow",
            "description": "Test description",
            "definition": None,  # Use None to trigger auto-generation of Elyra format
            "tags": ["test"],
        }

        # Act
        response = client.post("/flows?is_elyra=true", json=request_data)

        # Assert
        assert response.status_code == 201
        assert response.json()["name"] == "Test Flow"
        assert response.json()["flow_id"] == "12345678-1234-1234-1234-123456789abc"
        override_service.create_flow.assert_called_once()

    def test_create_flow_with_minimal_data_returns_201(self, client, override_service, sample_flow_with_id):
        """Test creating a flow with only required fields returns 201."""
        # Arrange
        override_service.create_flow.return_value = sample_flow_with_id
        request_data = {"name": "Minimal Flow"}

        # Act
        response = client.post("/flows?is_elyra=true", json=request_data)

        # Assert
        assert response.status_code == 201
        assert response.json()["name"] == "Test Flow"  # From sample_flow_with_id

    def test_create_flow_with_invalid_name_returns_400(self, client, override_service):
        """Test creating a flow with invalid name returns 400."""
        # Arrange - Elyra format with empty name
        request_data = {
            "name": "",
            "definition": {
                "doc_type": "pipeline",
                "version": "3.0",
                "pipelines": [{"id": "pipeline1", "nodes": []}],
                "parameters": {},
            },
        }

        # Act
        response = client.post("/flows?is_elyra=true", json=request_data)

        # Assert - Pydantic validation errors return 400 with invalid_parameter code
        assert response.status_code == 400
        data = response.json()
        assert data["errors"][0]["code"] == "invalid_parameter"
        assert "name" in data["errors"][0]["message"].lower()

    def test_create_flow_with_invalid_container_kind_returns_400(self, client):
        """Test creating a flow with invalid container_kind returns 400."""
        # Arrange - Elyra format with invalid container_kind
        request_data = {
            "name": "Test Flow",
            "container_kind": "invalid",
            "definition": {
                "doc_type": "pipeline",
                "version": "3.0",
                "pipelines": [{"id": "pipeline1", "nodes": []}],
                "parameters": {},
            },
        }

        # Act
        response = client.post("/flows?is_elyra=true", json=request_data)

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["errors"][0]["code"] == "invalid_parameter"

    def test_create_flow_with_invalid_uuid_returns_400(self, client):
        """Test creating a flow with invalid UUID format returns 400."""
        # Arrange - Elyra format with invalid container_id
        request_data = {
            "name": "Test Flow",
            "container_id": "not-a-uuid",
            "definition": {
                "doc_type": "pipeline",
                "version": "3.0",
                "pipelines": [{"id": "pipeline1", "nodes": []}],
                "parameters": {},
            },
        }

        # Act
        response = client.post("/flows?is_elyra=true", json=request_data)

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["errors"][0]["code"] == "invalid_parameter"

    def test_create_flow_with_filesystem_error_returns_500(self, client, override_service):
        """Test creating a flow with filesystem error returns 500."""
        # Arrange
        override_service.create_flow.side_effect = FlowStorageException(
            "Failed to store flow due to file system error: Disk full",
            operation="create",
        )
        request_data = {"name": "Test Flow"}

        # Act
        response = client.post("/flows?is_elyra=true", json=request_data)

        # Assert
        assert response.status_code == 500
        data = response.json()
        assert data["errors"][0]["code"] == "flow_storage_error"
        assert "file system" in data["errors"][0]["message"].lower()

    def test_create_duplicate_flow_returns_409(self, client, override_service):
        """Test creating a duplicate flow returns 409."""
        # Arrange
        override_service.create_flow.side_effect = FlowAlreadyExistsException(
            "Flow with name 'Test Flow' already exists", flow_name="Test Flow"
        )
        request_data = {"name": "Test Flow"}

        # Act
        response = client.post("/flows?is_elyra=true", json=request_data)

        # Assert
        assert response.status_code == 409
        data = response.json()
        assert data["errors"][0]["code"] == "flow_already_exists"
        assert "Test Flow" in data["errors"][0]["message"]

    def test_create_flow_with_is_elyra_false_returns_201(self, client, override_service, sample_authoring_flow_with_id):
        """Test creating a flow with is_elyra=false query parameter returns 201."""
        # Arrange
        override_service.create_flow.return_value = sample_authoring_flow_with_id
        request_data = {
            "flow_name": "Test Flow",
            "flow": [
                {
                    "type": "ingest_source",
                    "name": "ingest_node",
                    "config": {"paths": "./data"},
                },
                {
                    "type": "extract_operator",
                    "name": "extract_node",
                    "config": {},
                    "depends_on": ["ingest_node"],
                },
            ],
        }

        # Act
        response = client.post("/flows?is_elyra=false", json=request_data)

        # Assert
        assert response.status_code == 201
        assert response.json()["flow_name"] == "Test Flow"
        # Verify service was called with is_elyra=False
        call_args = override_service.create_flow.call_args
        assert not call_args.kwargs.get("is_elyra")

    def test_create_flow_with_is_elyra_true_returns_201(self, client, override_service, sample_flow_with_id):
        """Test creating a flow with is_elyra=true query parameter returns 201."""
        # Arrange
        override_service.create_flow.return_value = sample_flow_with_id
        request_data = {
            "name": "Test Flow",
            "definition": {
                "doc_type": "pipeline",
                "version": "3.0",
                "pipelines": [{"id": "pipeline1", "nodes": [{"id": "node1", "type": "execution_node"}]}],
            },
        }

        # Act
        response = client.post("/flows?is_elyra=true", json=request_data)

        # Assert
        assert response.status_code == 201
        assert response.json()["name"] == "Test Flow"
        # Verify service was called with is_elyra=True
        call_args = override_service.create_flow.call_args
        assert call_args.kwargs.get("is_elyra")

    def test_create_flow_without_is_elyra_defaults_to_false(
        self, client, override_service, sample_authoring_flow_with_id
    ):
        """Test creating a flow without is_elyra parameter defaults to false (Authoring format)."""
        # Arrange
        override_service.create_flow.return_value = sample_authoring_flow_with_id
        request_data = {
            "flow_name": "Test Flow",
            "flow": [
                {
                    "type": "ingest_source",
                    "name": "ingest_node",
                    "config": {"paths": "./data"},
                },
                {
                    "type": "extract_operator",
                    "name": "extract_node",
                    "config": {},
                    "depends_on": ["ingest_node"],
                },
            ],
        }

        # Act
        response = client.post("/flows", json=request_data)

        # Assert
        assert response.status_code == 201
        # Verify service was called with is_elyra=False (default)
        call_args = override_service.create_flow.call_args
        assert not call_args.kwargs.get("is_elyra")

    def test_create_flow_with_authoring_format_complete_pipeline(
        self, client, override_service, sample_authoring_flow_with_id
    ):
        """Test creating a complete pipeline flow using authoring format."""
        # Arrange
        override_service.create_flow.return_value = sample_authoring_flow_with_id
        request_data = {
            "flow_name": "complete-document-pipeline",
            "description": "Complete RAG pipeline",
            "flow": [
                {"type": "ingest_source", "name": "ingest", "config": {"paths": "./docs"}},
                {"type": "extract_operator", "name": "extract", "depends_on": ["ingest"]},
                {"type": "chunker", "name": "chunk", "depends_on": ["extract"], "config": {"chunk_size": 512}},
                {"type": "embeddings", "name": "embed", "depends_on": ["chunk"]},
                {"type": "vectordb", "name": "store", "depends_on": ["embed"]},
            ],
            "global_config": {"doc_column": "content"},
            "tags": ["rag", "production"],
        }

        # Act
        response = client.post("/flows", json=request_data)

        # Assert
        assert response.status_code == 201
        assert response.json()["flow_name"] == "Test Flow"
        call_args = override_service.create_flow.call_args
        assert not call_args.kwargs.get("is_elyra")

    def test_create_flow_with_authoring_format_branching(self, client, override_service, sample_authoring_flow_with_id):
        """Test creating a branching flow using authoring format."""
        # Arrange
        override_service.create_flow.return_value = sample_authoring_flow_with_id
        request_data = {
            "flow_name": "branching-pipeline",
            "flow": [
                {"type": "ingest_source", "name": "ingest"},
                {
                    "type": "branching",
                    "name": "classify",
                    "depends_on": ["ingest"],
                    "config": {
                        "branches": {
                            "invoices": {"condition": "type == 'invoice'"},
                            "receipts": {"condition": "type == 'receipt'"},
                        }
                    },
                },
                {"type": "extract_operator", "name": "proc_inv", "depends_on": ["classify.invoices"]},
                {"type": "extract_operator", "name": "proc_rec", "depends_on": ["classify.receipts"]},
            ],
        }

        # Act
        response = client.post("/flows", json=request_data)

        # Assert
        assert response.status_code == 201

    def test_create_flow_with_authoring_format_invalid_structure_returns_400(self, client, override_service):
        """Test creating flow with invalid authoring format structure returns 400."""
        # Arrange - Missing required 'name' field in operator
        request_data = {
            "flow_name": "invalid-flow",
            "flow": [
                {"type": "ingest_source", "config": {"paths": "./data"}},  # Missing 'name'
            ],
        }

        # Act
        response = client.post("/flows", json=request_data)

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["errors"][0]["code"] == "invalid_parameter"
        assert "name" in data["errors"][0]["message"].lower()

    def test_create_flow_with_authoring_format_empty_flow_list_returns_400(self, client, override_service):
        """Test creating flow with empty flow list returns 400."""
        # Arrange
        request_data = {"flow_name": "empty-flow", "flow": []}

        # Act
        response = client.post("/flows", json=request_data)

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["errors"][0]["code"] == "invalid_parameter"
        assert "flow" in data["errors"][0]["message"].lower()


class TestGetFlowEndpoint:
    """Tests for GET /flows/{flow_id} endpoint."""

    def test_get_flow_with_existing_id_returns_200(self, client, override_service, sample_flow_with_id):
        """Test retrieving an existing flow returns 200 (Elyra format)."""
        # Arrange
        override_service.get_flow.return_value = sample_flow_with_id

        # Act
        response = client.get("/flows/12345678-1234-1234-1234-123456789abc")

        # Assert
        assert response.status_code == 200
        assert response.json()["flow_id"] == "12345678-1234-1234-1234-123456789abc"
        assert response.json()["name"] == "Test Flow"  # Elyra format uses 'name'
        override_service.get_flow.assert_called_once_with("12345678-1234-1234-1234-123456789abc")

    def test_get_flow_with_existing_id_authoring_format_returns_200(
        self, client, override_service, sample_authoring_flow_with_id
    ):
        """Test retrieving an existing flow returns 200 (Authoring format)."""
        # Arrange
        override_service.get_flow.return_value = sample_authoring_flow_with_id

        # Act
        response = client.get("/flows/12345678-1234-1234-1234-123456789abc")

        # Assert
        assert response.status_code == 200
        assert response.json()["flow_id"] == "12345678-1234-1234-1234-123456789abc"
        assert response.json()["flow_name"] == "Test Flow"  # Authoring format uses 'flow_name'
        assert "flow" in response.json()  # Authoring format has 'flow' array
        override_service.get_flow.assert_called_once_with("12345678-1234-1234-1234-123456789abc")

    def test_get_flow_with_nonexistent_id_returns_404(self, client, override_service):
        """Test retrieving a non-existent flow returns 404."""
        # Arrange
        nonexistent_id = "12345678-1234-1234-1234-000000000000"
        override_service.get_flow.side_effect = FlowNotFoundException(
            f"Flow {nonexistent_id} not found", flow_id=nonexistent_id
        )

        # Act
        response = client.get(f"/flows/{nonexistent_id}")

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["errors"][0]["code"] == "flow_not_found"
        assert nonexistent_id in data["errors"][0]["message"]

    def test_get_flow_with_filesystem_error_returns_500(self, client, override_service):
        """Test retrieving a flow with filesystem error returns 500."""
        # Arrange
        test_id = "12345678-1234-1234-1234-123456789def"
        override_service.get_flow.side_effect = FlowStorageException(
            "Failed to read flow due to file system error: Read error",
            operation="read",
            flow_id=test_id,
        )

        # Act
        response = client.get(f"/flows/{test_id}")

        # Assert
        assert response.status_code == 500
        data = response.json()
        assert data["errors"][0]["code"] == "flow_storage_error"
        assert "file system" in data["errors"][0]["message"].lower()

    def test_get_flow_with_invalid_uuid_format_returns_422(self, client):
        """Test retrieving a flow with invalid UUID format returns 400."""
        # Act - Use invalid UUID format
        response = client.get("/flows/not-a-valid-uuid")

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["errors"][0]["code"] == "validation_error"
        assert "flow_id" in data["errors"][0]["message"].lower() or "uuid" in data["errors"][0]["message"].lower()

    def test_get_flow_with_short_uuid_returns_422(self, client):
        """Test retrieving a flow with too short UUID returns 400."""
        # Act - Use UUID that's too short
        response = client.get("/flows/123")

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["errors"][0]["code"] == "validation_error"


class TestListFlowsEndpoint:
    """Tests for GET /flows endpoint."""

    def test_list_flows_without_filters_returns_200(self, client, override_service, multiple_sample_flows):
        """Test listing all flows without filters returns 200."""
        # Arrange
        override_service.list_flows.return_value = multiple_sample_flows
        override_service.count_flows.return_value = 5

        # Act - Use is_elyra=true to match Elyra format fixtures
        response = client.get("/flows?is_elyra=true")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert len(data["flows"]) == 5
        assert data["total_count"] == 5
        assert data["offset"] == 0
        assert data["limit"] == 100

    def test_list_flows_with_pagination_returns_200(self, client, override_service, multiple_sample_flows):
        """Test listing flows with pagination returns 200."""
        # Arrange
        override_service.list_flows.return_value = multiple_sample_flows[2:4]
        override_service.count_flows.return_value = 5

        # Act - Use is_elyra=true to match Elyra format fixtures
        response = client.get("/flows?offset=2&limit=2&is_elyra=true")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert len(data["flows"]) == 2
        assert data["offset"] == 2
        assert data["limit"] == 2
        assert data["next"] is not None  # Has more pages (offset=2, len=2, total=5)

    def test_list_flows_with_name_filter_returns_200(self, client, override_service, multiple_sample_flows):
        """Test listing flows with name filter returns 200."""
        # Arrange
        filtered_flows = [f for f in multiple_sample_flows if "Flow 2" in f.name]
        override_service.list_flows.return_value = filtered_flows
        override_service.count_flows.return_value = 1

        # Act - Use is_elyra=true to match Elyra format fixtures
        response = client.get("/flows?name=Flow 2&is_elyra=true")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert len(data["flows"]) == 1
        assert data["total_count"] == 1
        override_service.list_flows.assert_called_once()
        call_kwargs = override_service.list_flows.call_args.kwargs
        assert call_kwargs["name_filter"] == "Flow 2"

    def test_list_flows_with_tags_filter_returns_200(self, client, override_service, multiple_sample_flows):
        """Test listing flows with tags filter returns 200."""
        # Arrange
        override_service.list_flows.return_value = [multiple_sample_flows[1]]
        override_service.count_flows.return_value = 1

        # Act - Use is_elyra=true to match Elyra format fixtures
        response = client.get("/flows?tags=tag-1&is_elyra=true")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert len(data["flows"]) == 1
        call_kwargs = override_service.list_flows.call_args.kwargs
        assert call_kwargs["tags_filter"] == ["tag-1"]

    def test_list_flows_with_is_hidden_filter_returns_200(self, client, override_service, multiple_sample_flows):
        """Test listing flows with is_hidden filter returns 200."""
        # Arrange
        hidden_flows = [f for f in multiple_sample_flows if f.is_hidden]
        override_service.list_flows.return_value = hidden_flows
        override_service.count_flows.return_value = len(hidden_flows)

        # Act - Use is_elyra=true to match Elyra format fixtures
        response = client.get("/flows?is_hidden=true&is_elyra=true")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == len(hidden_flows)
        call_kwargs = override_service.list_flows.call_args.kwargs
        assert call_kwargs["is_hidden"] is True

    def test_list_flows_with_invalid_skip_returns_400(self, client):
        """Test listing flows with invalid offset parameter returns 400."""
        # Act
        response = client.get("/flows?offset=-1")

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["errors"][0]["code"] == "validation_error"

    def test_list_flows_with_invalid_limit_returns_400(self, client):
        """Test listing flows with invalid limit parameter returns 400."""
        # Act
        response = client.get("/flows?limit=0")

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["errors"][0]["code"] == "validation_error"

    def test_list_flows_with_filesystem_error_returns_500(self, client, override_service):
        """Test listing flows with filesystem error returns 500."""
        # Arrange
        override_service.list_flows.side_effect = FlowStorageException(
            "Failed to list flows due to storage error", operation="list"
        )

        # Act
        response = client.get("/flows")

        # Assert
        assert response.status_code == 500
        data = response.json()
        assert data["errors"][0]["code"] == "flow_storage_error"
        assert "storage" in data["errors"][0]["message"].lower()


class TestUpdateFlowEndpoint:
    """Tests for PUT /flows/{flow_id} endpoint."""

    def test_update_flow_with_valid_data_returns_200(self, client, override_service, sample_flow_with_id):
        """Test updating a flow with valid data returns 200."""
        # Arrange
        updated_flow = sample_flow_with_id
        updated_flow.name = "Updated Flow"
        override_service.update_flow.return_value = updated_flow
        request_data = {"name": "Updated Flow", "description": "Updated description"}

        # Act - Use is_elyra=true to match Elyra format fixtures
        response = client.put("/flows/12345678-1234-1234-1234-123456789abc?is_elyra=true", json=request_data)

        # Assert
        assert response.status_code == 200
        assert response.json()["name"] == "Updated Flow"
        override_service.update_flow.assert_called_once()

    def test_update_flow_with_nonexistent_id_returns_404(self, client, override_service):
        """Test updating a non-existent flow returns 404."""
        # Arrange
        nonexistent_id = "12345678-1234-1234-1234-000000000000"
        override_service.update_flow.side_effect = FlowNotFoundException(
            f"Flow {nonexistent_id} not found", flow_id=nonexistent_id
        )
        request_data = {"name": "Updated Flow"}

        # Act - Use is_elyra=true to match Elyra format fixtures
        response = client.put(f"/flows/{nonexistent_id}?is_elyra=true", json=request_data)

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["errors"][0]["code"] == "flow_not_found"
        assert nonexistent_id in data["errors"][0]["message"]

    def test_update_flow_with_invalid_data_returns_400(self, client, override_service):
        """Test updating a flow with invalid data returns 400."""
        # Arrange
        request_data = {"name": ""}

        # Act
        response = client.put("/flows/12345678-1234-1234-1234-123456789abc", json=request_data)

        # Assert - FastAPI validation errors now return 400
        assert response.status_code == 400
        data = response.json()
        assert data["errors"][0]["code"] == "invalid_parameter"

    def test_update_flow_with_invalid_uuid_format_returns_422(self, client):
        """Test updating a flow with invalid UUID format returns 400."""
        # Arrange
        request_data = {"name": "Updated Flow"}

        # Act
        response = client.put("/flows/invalid-uuid", json=request_data)

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["errors"][0]["code"] == "validation_error"
        assert "flow_id" in data["errors"][0]["message"].lower()

    def test_update_flow_with_filesystem_error_returns_500(self, client, override_service):
        """Test updating a flow with filesystem error returns 500."""
        # Arrange
        test_id = "12345678-1234-1234-1234-123456789def"
        override_service.update_flow.side_effect = FlowStorageException(
            "Failed to update flow due to storage error",
            operation="update",
            flow_id=test_id,
        )
        request_data = {"name": "Updated Flow"}

        # Act - Use is_elyra=true to match Elyra format fixtures
        response = client.put(f"/flows/{test_id}?is_elyra=true", json=request_data)

        # Assert
        assert response.status_code == 500
        data = response.json()
        assert data["errors"][0]["code"] == "flow_storage_error"
        assert "storage" in data["errors"][0]["message"].lower()

    def test_update_flow_with_authoring_format_returns_200(self, client, override_service, sample_flow_with_id):
        """Test updating a flow with authoring format returns 200."""
        # Arrange
        updated_flow = sample_flow_with_id
        updated_flow.name = "updated-pipeline"
        updated_flow.description = "Updated description"
        # The definition stores the complete authoring format as a dict
        updated_flow.definition = {
            "flow_name": "updated-pipeline",
            "description": "Updated description",
            "flow": [{"type": "ingest_source", "name": "ingest", "config": {}}],
            "global_config": {},
            "tags": ["updated"],
        }
        override_service.update_flow.return_value = updated_flow

        # Request data in authoring format
        request_data = {
            "flow_name": "updated-pipeline",
            "description": "Updated description",
            "flow": [{"type": "ingest_source", "name": "ingest", "config": {}}],
            "global_config": {},
            "tags": ["updated"],
        }

        # Act
        response = client.put("/flows/12345678-1234-1234-1234-123456789abc?is_elyra=false", json=request_data)

        # Assert
        assert response.status_code == 200
        assert response.json()["flow_name"] == "updated-pipeline"  # Authoring response has flow_name
        override_service.update_flow.assert_called_once()

    def test_update_flow_with_elyra_format_returns_200(self, client, override_service, sample_flow_with_id):
        """Test updating a flow with Elyra format returns 200."""
        # Arrange
        updated_flow = sample_flow_with_id
        updated_flow.name = "Updated Elyra Flow"
        override_service.update_flow.return_value = updated_flow
        request_data = {
            "name": "Updated Elyra Flow",
            "definition": {
                "doc_type": "pipeline",
                "version": "3.0",
                "pipelines": [{"id": "pipeline1", "nodes": []}],
            },
        }

        # Act
        response = client.put("/flows/12345678-1234-1234-1234-123456789abc?is_elyra=true", json=request_data)

        # Assert
        assert response.status_code == 200
        assert response.json()["name"] == "Updated Elyra Flow"  # Elyra response has name
        override_service.update_flow.assert_called_once()


class TestPartialUpdateFlowEndpoint:
    """Tests for PATCH /flows/{flow_id} endpoint."""

    def test_partial_update_flow_with_valid_data_returns_200(self, client, override_service, sample_flow_with_id):
        """Test partially updating a flow with valid data returns 200."""
        # Arrange
        updated_flow = sample_flow_with_id
        updated_flow.description = "Partially updated"
        override_service.partial_update_flow.return_value = updated_flow
        request_data = {"description": "Partially updated"}

        # Act - Use is_elyra=true to match Elyra format fixtures
        response = client.patch("/flows/12345678-1234-1234-1234-123456789abc?is_elyra=true", json=request_data)

        # Assert
        assert response.status_code == 200
        assert response.json()["description"] == "Partially updated"
        override_service.partial_update_flow.assert_called_once()

    def test_partial_update_flow_with_name_change_returns_200(self, client, override_service, sample_flow_with_id):
        """Test partially updating flow name returns 200."""
        # Arrange
        updated_flow = sample_flow_with_id
        updated_flow.name = "New Name"
        override_service.partial_update_flow.return_value = updated_flow
        request_data = {"name": "New Name"}

        # Act - Use is_elyra=true to match Elyra format fixtures
        response = client.patch("/flows/12345678-1234-1234-1234-123456789abc?is_elyra=true", json=request_data)

        # Assert
        assert response.status_code == 200
        assert response.json()["name"] == "New Name"

    def test_partial_update_flow_name_authoring_format_returns_200(self, client, override_service, sample_flow_with_id):
        """Test partially updating flow_name in authoring format returns 200."""
        # Arrange
        updated_flow = sample_flow_with_id
        updated_flow.name = "new-flow-name"
        # Definition should also have updated flow_name
        updated_flow.definition = {
            "flow_name": "new-flow-name",
            "flow": [
                {"type": "ingest_source", "name": "ingest", "config": {}},
            ],
            "global_config": {"doc_column": "content"},
            "description": "Test flow",
            "tags": ["test"],
        }
        override_service.partial_update_flow.return_value = updated_flow
        request_data = {"flow_name": "new-flow-name"}

        # Act
        response = client.patch("/flows/12345678-1234-1234-1234-123456789abc", json=request_data)

        # Assert
        assert response.status_code == 200
        assert response.json()["flow_name"] == "new-flow-name"
        override_service.partial_update_flow.assert_called_once()

    def test_partial_update_flow_definition_authoring_format_returns_200(
        self, client, override_service, sample_flow_with_id
    ):
        """Test partially updating flow definition in authoring format returns 200."""
        # Arrange
        updated_flow = sample_flow_with_id
        # Definition should have complete authoring format with updated flow operators
        updated_flow.definition = {
            "flow_name": "test-flow",
            "flow": [
                {"type": "ingest_source", "name": "ingest", "config": {}},
                {"type": "extract_operator", "name": "extract", "depends_on": ["ingest"]},
            ],
            "global_config": {"doc_column": "content"},
            "description": "Test flow",
            "tags": ["test"],
        }
        override_service.partial_update_flow.return_value = updated_flow
        request_data = {
            "flow": [
                {"type": "ingest_source", "name": "ingest", "config": {}},
                {"type": "extract_operator", "name": "extract", "depends_on": ["ingest"]},
            ],
            "global_config": {"doc_column": "content"},
        }

        # Act
        response = client.patch("/flows/12345678-1234-1234-1234-123456789abc?is_elyra=false", json=request_data)

        # Assert
        assert response.status_code == 200
        assert len(response.json()["flow"]) == 2
        override_service.partial_update_flow.assert_called_once()

    def test_partial_update_multiple_fields_authoring_format_returns_200(
        self, client, override_service, sample_flow_with_id
    ):
        """Test partially updating multiple fields in authoring format returns 200."""
        # Arrange
        updated_flow = sample_flow_with_id
        updated_flow.name = "updated-name"
        updated_flow.description = "Updated description"
        updated_flow.tags = ["updated", "test"]
        updated_flow.definition = {
            "flow_name": "updated-name",
            "description": "Updated description",
            "flow": [{"type": "noop", "name": "op1"}],
            "global_config": {},
            "tags": ["updated", "test"],
        }
        override_service.partial_update_flow.return_value = updated_flow
        request_data = {
            "flow_name": "updated-name",
            "description": "Updated description",
            "tags": ["updated", "test"],
        }

        # Act
        response = client.patch("/flows/12345678-1234-1234-1234-123456789abc", json=request_data)

        # Assert
        assert response.status_code == 200
        assert response.json()["flow_name"] == "updated-name"
        assert response.json()["description"] == "Updated description"
        assert response.json()["tags"] == ["updated", "test"]
        override_service.partial_update_flow.assert_called_once()

    def test_partial_update_elyra_format_returns_200(self, client, override_service, sample_flow_with_id):
        """Test partially updating with Elyra format returns 200."""
        # Arrange
        updated_flow = sample_flow_with_id
        updated_flow.description = "Updated via Elyra"
        override_service.partial_update_flow.return_value = updated_flow
        request_data = {"description": "Updated via Elyra"}

        # Act
        response = client.patch("/flows/12345678-1234-1234-1234-123456789abc?is_elyra=true", json=request_data)

        # Assert
        assert response.status_code == 200
        assert response.json()["description"] == "Updated via Elyra"
        override_service.partial_update_flow.assert_called_once()

    def test_partial_update_flow_with_nonexistent_id_returns_404(self, client, override_service):
        """Test partially updating a non-existent flow returns 404."""
        # Arrange
        nonexistent_id = "12345678-1234-1234-1234-000000000000"
        override_service.partial_update_flow.side_effect = FlowNotFoundException(
            f"Flow {nonexistent_id} not found", flow_id=nonexistent_id
        )
        request_data = {"name": "New Name"}

        # Act
        response = client.patch(f"/flows/{nonexistent_id}", json=request_data)

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["errors"][0]["code"] == "flow_not_found"
        assert nonexistent_id in data["errors"][0]["message"]

    def test_partial_update_flow_with_invalid_uuid_format_returns_422(self, client):
        """Test partially updating a flow with invalid UUID format returns 400."""
        # Arrange
        request_data = {"description": "Updated"}

        # Act
        response = client.patch("/flows/not-valid-uuid", json=request_data)

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["errors"][0]["code"] == "validation_error"
        assert "flow_id" in data["errors"][0]["message"].lower()

    def test_partial_update_flow_with_invalid_data_returns_400(self, client, override_service, sample_flow_with_id):
        """Test partially updating a flow with invalid data returns 400."""
        # Use invalid data that fails validation for both Elyra and Authoring formats
        request_data = {"tags": "not-a-list"}  # tags must be a list, not a string

        # Act - Use is_elyra=true to match Elyra format fixtures
        response = client.patch("/flows/12345678-1234-1234-1234-123456789abc?is_elyra=true", json=request_data)

        # Assert - Pydantic validation errors return 400 with validation_error code
        assert response.status_code == 400
        data = response.json()
        assert data["errors"][0]["code"] == "invalid_parameter"
        assert "tags" in data["errors"][0]["message"].lower()

    def test_partial_update_flow_with_empty_name_returns_400(self, client, override_service, sample_flow_with_id):
        """Test that empty name field is properly validated and not silently ignored.

        This test ensures the union type fix prevents silent data loss where
        {"name": ""} with is_elyra=true would be accepted as AuthoringFlowUpdateRequest
        (which ignores the unknown 'name' field) instead of being validated against
        ElyraFlowUpdateRequest (which would reject empty string).
        """
        # Arrange
        request_data = {"name": ""}  # Empty string violates min_length=1 for Elyra format

        # Act - Use is_elyra=true to ensure validation against ElyraFlowUpdateRequest
        response = client.patch("/flows/12345678-1234-1234-1234-123456789abc?is_elyra=true", json=request_data)

        # Assert - Should return 400 with validation error, not silently ignore the field
        assert response.status_code == 400
        data = response.json()
        assert data["errors"][0]["code"] == "invalid_parameter"
        assert "name" in data["errors"][0]["message"].lower()

    def test_partial_update_flow_with_empty_body_returns_200(self, client, override_service, sample_flow_with_id):
        """Test partially updating a flow with empty body returns 200."""
        # Arrange
        override_service.partial_update_flow.return_value = sample_flow_with_id
        request_data: dict = {}

        # Act - Use is_elyra=true to match Elyra format fixtures
        response = client.patch("/flows/12345678-1234-1234-1234-123456789abc?is_elyra=true", json=request_data)

        # Assert
        assert response.status_code == 200


class TestDeleteFlowEndpoint:
    """Tests for DELETE /flows/{flow_id} endpoint."""

    def test_delete_flow_with_existing_id_returns_204(self, client, override_service):
        """Test deleting an existing flow returns 204."""
        # Arrange
        override_service.delete_flow.return_value = True

        # Act
        response = client.delete("/flows/12345678-1234-1234-1234-123456789abc")

        # Assert
        assert response.status_code == 204
        assert response.content == b""
        override_service.delete_flow.assert_called_once_with("12345678-1234-1234-1234-123456789abc")

    def test_delete_flow_with_nonexistent_id_returns_404(self, client, override_service):
        """Test deleting a non-existent flow returns 404."""
        # Arrange
        nonexistent_id = "12345678-1234-1234-1234-000000000000"
        override_service.delete_flow.side_effect = FlowNotFoundException(
            f"Flow {nonexistent_id} not found", flow_id=nonexistent_id
        )

        # Act
        response = client.delete(f"/flows/{nonexistent_id}")

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["errors"][0]["code"] == "flow_not_found"
        assert "not found" in data["errors"][0]["message"].lower()

    def test_delete_flow_with_filesystem_error_returns_500(self, client, override_service):
        """Test deleting a flow with filesystem error returns 500."""
        # Arrange
        test_id = "12345678-1234-1234-1234-123456789def"
        override_service.delete_flow.side_effect = FlowStorageException(
            "Failed to delete flow due to storage error",
            operation="delete",
            flow_id=test_id,
        )

        # Act
        response = client.delete(f"/flows/{test_id}")

        # Assert
        assert response.status_code == 500
        data = response.json()
        assert data["errors"][0]["code"] == "flow_storage_error"
        assert "storage" in data["errors"][0]["message"].lower()


class TestFlowRoutesIntegration:
    """Integration tests for flow routes."""

    def test_create_and_get_flow_workflow(self, client, override_service, sample_flow_with_id):
        """Test creating and then retrieving a flow."""
        # Arrange
        override_service.create_flow.return_value = sample_flow_with_id
        override_service.get_flow.return_value = sample_flow_with_id

        # Act - Create
        create_response = client.post("/flows?is_elyra=true", json={"name": "Test Flow"})
        flow_id = create_response.json()["flow_id"]

        # Act - Get
        get_response = client.get(f"/flows/{flow_id}")

        # Assert
        assert create_response.status_code == 201
        assert get_response.status_code == 200
        assert get_response.json()["flow_id"] == flow_id

    def test_create_update_and_delete_flow_workflow(
        self, client, override_service, sample_authoring_flow_with_id, sample_flow_with_id
    ):
        """Test creating, updating, and deleting a flow."""
        # Arrange
        override_service.create_flow.return_value = sample_authoring_flow_with_id
        updated_flow = sample_flow_with_id
        updated_flow.name = "Updated Name"
        override_service.update_flow.return_value = updated_flow
        override_service.delete_flow.return_value = True

        # Act - Create (using authoring format, is_elyra defaults to false)
        create_response = client.post(
            "/flows", json={"flow_name": "Test Flow", "flow": [{"type": "noop", "name": "op1"}]}
        )
        assert create_response.status_code == 201, f"Create failed: {create_response.json()}"
        flow_id = create_response.json()["flow_id"]

        # Act - Update (use is_elyra=true to match Elyra format)
        update_response = client.put(f"/flows/{flow_id}?is_elyra=true", json={"name": "Updated Name"})

        # Act - Delete
        delete_response = client.delete(f"/flows/{flow_id}")

        # Assert
        assert create_response.status_code == 201
        assert update_response.status_code == 200
        assert update_response.json()["name"] == "Updated Name"
        assert delete_response.status_code == 204

    def test_delete_flow_with_invalid_uuid_format_returns_422(self, client):
        """Test deleting a flow with invalid UUID format returns 400."""
        # Act
        response = client.delete("/flows/bad-uuid-format")

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["errors"][0]["code"] == "validation_error"


class TestParameterValidation:
    """Tests for parameter validation with new dependency injection."""

    def test_list_flows_with_limit_exceeding_max_returns_422(self, client):
        """Test listing flows with limit exceeding maximum returns 400."""
        # Act
        response = client.get("/flows?limit=2000")

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["errors"][0]["code"] == "validation_error"
        assert "limit" in data["errors"][0]["message"].lower()

    def test_list_flows_with_negative_offset_returns_422(self, client):
        """Test listing flows with negative offset returns 400."""
        # Act
        response = client.get("/flows?offset=-10")

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["errors"][0]["code"] == "validation_error"

    def test_get_flow_with_valid_uuid_format(self, client, override_service, sample_flow_with_id):
        """Test that valid UUID format passes validation."""
        # Arrange
        valid_uuid = "550e8400-e29b-41d4-a716-446655440000"
        override_service.get_flow.return_value = sample_flow_with_id

        # Act
        response = client.get(f"/flows/{valid_uuid}")

        # Assert
        assert response.status_code == 200
        override_service.get_flow.assert_called_once_with(valid_uuid)


class TestBulkDeleteFlows:
    """DELETE /flows?flow_ids=..."""

    def test_passes_trimmed_ids_and_returns_service_result(self, client, override_service) -> None:
        result = {
            "deleted": ["flow-1"],
            "failed": [{"flow_id": "flow-2", "error": "Flow not found"}],
            "total_requested": 2,
            "total_deleted": 1,
            "total_failed": 1,
        }
        override_service.bulk_delete_flows.return_value = result

        response = client.delete("/flows", params={"flow_ids": "flow-1,flow-2"})

        assert response.status_code == 200
        assert response.json() == result
        override_service.bulk_delete_flows.assert_called_once_with(["flow-1", "flow-2"])

    def test_malformed_id_list_returns_400(self, client, override_service) -> None:
        response = client.delete("/flows", params={"flow_ids": "flow-1,,flow 2"})

        assert response.status_code == 400
        override_service.bulk_delete_flows.assert_not_called()
