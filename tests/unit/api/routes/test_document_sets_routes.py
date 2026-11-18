"""Unit tests for document sets API routes."""

from datetime import UTC, datetime
from unittest.mock import Mock

import pyarrow as pa
import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from docpipe.api.dependencies import get_document_set_service
from docpipe.api.middleware.error_handler import (
    docpipe_exception_handler,
    generic_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from docpipe.api.routes.document_sets import document_sets_router
from docpipe.core.assets.common.domain.models.attachment_ref import AttachmentRef
from docpipe.core.assets.document_sets.application.services.document_set_service import DocumentSetService
from docpipe.core.assets.document_sets.domain.models.document_set import DocumentSet
from docpipe.exceptions.docpipe_exceptions import AssetNotFoundException, DocpipeException

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DS_ID = "550e8400-e29b-41d4-a716-446655440001"
_DS_ID_2 = "550e8400-e29b-41d4-a716-446655440002"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    """FastAPI app with document-sets router and standard exception handlers."""
    test_app = FastAPI()
    test_app.include_router(document_sets_router)
    test_app.add_exception_handler(DocpipeException, docpipe_exception_handler)
    test_app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    test_app.add_exception_handler(RequestValidationError, validation_exception_handler)
    test_app.add_exception_handler(Exception, generic_exception_handler)
    return test_app


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def mock_service():
    return Mock(spec=DocumentSetService)


@pytest.fixture
def override_service(app, mock_service):
    app.dependency_overrides[get_document_set_service] = lambda: mock_service
    yield mock_service
    app.dependency_overrides.clear()


@pytest.fixture
def document_set() -> DocumentSet:
    return DocumentSet(
        asset_id=_DS_ID,
        name="Research Documents",
        description="A collection of research papers",
        storage_backend="duckdb",
        total_documents=5,
        total_size_bytes=1024,
        total_pages=10,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 2, tzinfo=UTC),
        metadata={"source": "test"},
    )


@pytest.fixture
def attachment_ref() -> AttachmentRef:
    return AttachmentRef(
        backend_type="duckdb",
        name="research_documents",
        details={
            "database_path": "/data/docsets.duckdb",
            "table_name": "research_documents",
        },
    )


# ---------------------------------------------------------------------------
# POST /document-sets — create_document_set API
# ---------------------------------------------------------------------------


class TestCreateDocumentSet:
    def test_returns_201_with_valid_payload(self, client, override_service, document_set, attachment_ref):
        override_service.create_document_set.return_value = document_set
        override_service.get_attachment_ref.return_value = attachment_ref

        response = client.post("/document-sets", json={"name": "Research Documents"})

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Research Documents"
        assert data["id"] == _DS_ID

    def test_missing_name_returns_400(self, client, override_service):
        response = client.post("/document-sets", json={})

        assert response.status_code == 400

    def test_calls_service_with_correct_args(self, client, override_service, document_set, attachment_ref):
        override_service.create_document_set.return_value = document_set
        override_service.get_attachment_ref.return_value = attachment_ref

        client.post(
            "/document-sets", json={"name": "Research Documents", "description": "desc", "metadata": {"k": "v"}}
        )

        override_service.create_document_set.assert_called_once_with(
            name="Research Documents", description="desc", metadata={"k": "v"}
        )


# ---------------------------------------------------------------------------
# GET /document-sets/{document_set_id} — get_document_set API
# ---------------------------------------------------------------------------


class TestGetDocumentSet:
    def test_returns_200_for_existing_document_set(self, client, override_service, document_set, attachment_ref):
        override_service.get_document_set.return_value = document_set
        override_service.get_attachment_ref.return_value = attachment_ref

        response = client.get(f"/document-sets/{_DS_ID}")

        assert response.status_code == 200
        assert response.json()["id"] == _DS_ID

    def test_returns_404_when_not_found(self, client, override_service):
        override_service.get_document_set.side_effect = AssetNotFoundException(
            "not found", asset_id=_DS_ID, asset_type="DocumentSet"
        )

        response = client.get(f"/document-sets/{_DS_ID}")

        assert response.status_code == 404

    def test_invalid_uuid_returns_400(self, client, override_service):
        response = client.get("/document-sets/not-a-valid-uuid")

        assert response.status_code == 400


# ---------------------------------------------------------------------------
# GET /document-sets — list_document_sets API
# ---------------------------------------------------------------------------


class TestListDocumentSets:
    def test_returns_200_with_items(self, client, override_service, document_set, attachment_ref):
        override_service.list_document_sets.return_value = [document_set]
        override_service.get_attachment_ref.return_value = attachment_ref

        response = client.get("/document-sets")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == _DS_ID

    def test_empty_list_returns_200(self, client, override_service):
        override_service.list_document_sets.return_value = []

        response = client.get("/document-sets")

        assert response.status_code == 200
        assert response.json()["total"] == 0

    def test_pagination_params_forwarded(self, client, override_service):
        override_service.list_document_sets.return_value = []

        client.get("/document-sets?limit=10&offset=5")

        override_service.list_document_sets.assert_called_once_with(limit=10, offset=5)


# ---------------------------------------------------------------------------
# PATCH /document-sets/{document_set_id} — update_document_set API
# ---------------------------------------------------------------------------


class TestUpdateDocumentSet:
    def test_returns_200_on_successful_update(self, client, override_service, document_set, attachment_ref):
        override_service.update_document_set.return_value = document_set
        override_service.get_attachment_ref.return_value = attachment_ref

        response = client.patch(f"/document-sets/{_DS_ID}", json={"description": "Updated"})

        assert response.status_code == 200
        assert response.json()["id"] == _DS_ID

    def test_returns_404_when_not_found(self, client, override_service):
        override_service.update_document_set.side_effect = AssetNotFoundException(
            "not found", asset_id=_DS_ID, asset_type="DocumentSet"
        )

        response = client.patch(f"/document-sets/{_DS_ID}", json={"description": "Updated"})

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /document-sets/{document_set_id} — delete_document_set API
# ---------------------------------------------------------------------------


class TestDeleteDocumentSet:
    def test_returns_204_on_successful_delete(self, client, override_service):
        override_service.delete_document_set.return_value = None

        response = client.delete(f"/document-sets/{_DS_ID}")

        assert response.status_code == 204

    def test_returns_404_when_not_found(self, client, override_service):
        override_service.delete_document_set.side_effect = AssetNotFoundException(
            "not found", asset_id=_DS_ID, asset_type="DocumentSet"
        )

        response = client.delete(f"/document-sets/{_DS_ID}")

        assert response.status_code == 404

    def test_delete_data_query_param_forwarded(self, client, override_service):
        override_service.delete_document_set.return_value = None

        client.delete(f"/document-sets/{_DS_ID}?delete_data=false")

        override_service.delete_document_set.assert_called_once_with(document_set_id=_DS_ID, delete_data=False)


class TestPreviewDocumentSetData:
    """GET /document-sets/{id}/preview."""

    def test_returns_serialised_rows_with_pagination(self, client, override_service) -> None:
        override_service.preview_data.return_value = pa.table(
            {
                "id": ["doc-1", "doc-2"],
                "created_at": [datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC)],
                "payload": [b"raw", None],
            }
        )

        response = client.get(f"/document-sets/{_DS_ID}/preview", params={"limit": 2, "offset": 4})

        assert response.status_code == 200
        assert response.json() == {
            "columns": ["id", "created_at", "payload"],
            "data": [
                {"id": "doc-1", "created_at": "2024-01-01T00:00:00+00:00", "payload": "raw"},
                {"id": "doc-2", "created_at": "2024-01-02T00:00:00+00:00", "payload": None},
            ],
            "total_rows": 2,
        }
        override_service.preview_data.assert_called_once_with(document_set_id=_DS_ID, limit=2, offset=4)

    def test_unknown_document_set_returns_404(self, client, override_service) -> None:
        override_service.preview_data.side_effect = AssetNotFoundException(f"DocumentSet not found: {_DS_ID}")

        assert client.get(f"/document-sets/{_DS_ID}/preview").status_code == 404
