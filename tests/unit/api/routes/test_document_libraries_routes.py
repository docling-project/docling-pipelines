"""Route tests for /document-libraries against a real DocumentLibraryService on DuckDB.

The service and repository are the production classes, backed by a DuckDB file in tmp_path.
Only the document set service is replaced, because the listing route only reads document
set metadata from it. The tests follow openspec/specs/backend/document-libraries-api.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from docpipe.api.dependencies import get_document_library_service, get_document_set_service
from docpipe.api.middleware.error_handler import (
    docpipe_exception_handler,
    generic_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from docpipe.api.routes.document_libraries import document_libraries_router
from docpipe.core.assets.common.adapters.repositories.duckdb_asset_repository import DuckDBAssetRepository
from docpipe.core.assets.document_libraries.application.services.document_library_service import (
    DocumentLibraryService,
)
from docpipe.core.assets.document_libraries.domain.models.document_library import DocumentLibrary
from docpipe.core.assets.document_sets.domain.models.document_set import DocumentSet
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.storage.duck_db.duckdb_key_value_storage import DuckDBKeyValueStorage

_BASE = "/document-libraries"
_SET_1 = "11111111-1111-4111-8111-111111111111"
_SET_2 = "22222222-2222-4222-8222-222222222222"
_UNKNOWN = "99999999-9999-4999-8999-999999999999"
_PROJECT = "33333333-3333-4333-8333-333333333333"


class FakeDocumentSetService:
    """Serves stored DocumentSet objects by ID."""

    def __init__(self, document_sets: list[DocumentSet]) -> None:
        self._by_id = {d.asset_id: d for d in document_sets}

    def get_document_set(self, *, document_set_id: str) -> DocumentSet:
        return self._by_id[document_set_id]


@pytest.fixture
def library_service(tmp_path: Path) -> DocumentLibraryService:
    database_path = str(tmp_path / "libraries.duckdb")
    repository = DuckDBAssetRepository(
        asset_type=DocumentLibrary,
        key_value_storage=DuckDBKeyValueStorage(database_path=database_path),
        database_path=database_path,
    )
    return DocumentLibraryService(repository=repository)


@pytest.fixture
def document_set_service() -> FakeDocumentSetService:
    return FakeDocumentSetService(
        [
            DocumentSet(
                asset_id=_SET_1,
                name="Contracts",
                description="Signed contracts",
                total_documents=12,
                total_size_bytes=4096,
                metadata={"container_id": _PROJECT, "container_type": "project", "tags": ["legal"]},
            ),
            DocumentSet(asset_id=_SET_2, name="Drafts"),
        ]
    )


@pytest.fixture
def client(library_service: DocumentLibraryService, document_set_service: FakeDocumentSetService) -> TestClient:
    app = FastAPI()
    app.include_router(document_libraries_router)
    app.add_exception_handler(DocpipeException, docpipe_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
    app.dependency_overrides[get_document_library_service] = lambda: library_service
    app.dependency_overrides[get_document_set_service] = lambda: document_set_service
    return TestClient(app, raise_server_exceptions=False)


def _create(client: TestClient, **fields: object) -> dict:
    response = client.post(_BASE, json={"name": "Research Papers", **fields})
    assert response.status_code == 201, response.text
    return response.json()


class TestCreateAndGet:
    """POST and GET of a single library."""

    def test_create_returns_full_library(self, client: TestClient) -> None:
        created = _create(client, description="Papers", purpose="search", tags=["ml"], original_size=10, final_size=5)

        assert created["name"] == "Research Papers"
        assert created["description"] == "Papers"
        assert created["purpose"] == "search"
        assert created["tags"] == ["ml"]
        assert (created["original_size"], created["final_size"]) == (10, 5)
        assert created["document_set_ids"] == []

    def test_get_returns_created_library(self, client: TestClient) -> None:
        created = _create(client)

        response = client.get(f"{_BASE}/{created['library_id']}")

        assert response.status_code == 200
        assert response.json()["name"] == "Research Papers"

    def test_get_unknown_library_returns_404(self, client: TestClient) -> None:
        assert client.get(f"{_BASE}/{_UNKNOWN}").status_code == 404

    def test_get_malformed_id_returns_400(self, client: TestClient) -> None:
        assert client.get(f"{_BASE}/not-a-uuid").status_code == 400

    def test_duplicate_name_returns_409(self, client: TestClient) -> None:
        _create(client)

        assert client.post(_BASE, json={"name": "Research Papers"}).status_code == 409


class TestList:
    """GET /document-libraries."""

    def test_empty_list(self, client: TestClient) -> None:
        response = client.get(_BASE)

        assert response.status_code == 200
        assert response.json() == []

    def test_pagination(self, client: TestClient) -> None:
        for name in ("Alpha", "Beta", "Gamma"):
            _create(client, name=name)

        all_names = [lib["name"] for lib in client.get(_BASE).json()]
        page = [lib["name"] for lib in client.get(_BASE, params={"limit": 1, "offset": 1}).json()]

        assert sorted(all_names) == ["Alpha", "Beta", "Gamma"]
        assert page == all_names[1:2]

    @pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 1001}, {"offset": -1}])
    def test_out_of_range_pagination_returns_400(self, client: TestClient, params: dict) -> None:
        assert client.get(_BASE, params=params).status_code == 400


class TestUpdate:
    """PATCH /document-libraries/{library_id}."""

    def test_patch_changes_only_supplied_fields(self, client: TestClient) -> None:
        created = _create(client, description="Original", tags=["old"])

        response = client.patch(f"{_BASE}/{created['library_id']}", json={"tags": ["new-tag"]})

        assert response.status_code == 200
        updated = response.json()
        assert updated["tags"] == ["new-tag"]
        assert (updated["name"], updated["description"]) == ("Research Papers", "Original")

    def test_patch_all_fields(self, client: TestClient) -> None:
        created = _create(client)
        changes = {
            "name": "Renamed",
            "description": "New description",
            "purpose": "archive",
            "original_size": 20,
            "final_size": 8,
            "tags": ["a", "b"],
        }

        updated = client.patch(f"{_BASE}/{created['library_id']}", json=changes).json()

        assert {key: updated[key] for key in changes} == changes

    def test_patch_unknown_library_returns_404(self, client: TestClient) -> None:
        assert client.patch(f"{_BASE}/{_UNKNOWN}", json={"tags": ["x"]}).status_code == 404


class TestDocumentSets:
    """Bulk add, list and remove of document set associations."""

    def test_add_list_and_remove(self, client: TestClient) -> None:
        library_id = _create(client)["library_id"]

        added = client.put(f"{_BASE}/{library_id}/document-sets", params={"document_sets_ids": f"{_SET_1}, {_SET_2}"})
        listed = client.get(f"{_BASE}/{library_id}/document-sets")
        removed = client.request("DELETE", f"{_BASE}/{library_id}/document-sets", params={"document_sets_ids": _SET_2})
        remaining = client.get(f"{_BASE}/{library_id}/document-sets")

        assert (added.status_code, listed.status_code, removed.status_code) == (204, 200, 204)
        contracts, drafts = listed.json()["document_sets"]
        assert {k: contracts[k] for k in ("id", "name", "container_id", "container_type", "description", "tags")} == {
            "id": _SET_1,
            "name": "Contracts",
            "container_id": _PROJECT,
            "container_type": "project",
            "description": "Signed contracts",
            "tags": ["legal"],
        }
        assert contracts["documents"]["count"] == 12
        assert (drafts["id"], drafts["name"], drafts["documents"], drafts["tags"]) == (_SET_2, "Drafts", None, [])
        assert [d["id"] for d in remaining.json()["document_sets"]] == [_SET_1]
        assert client.get(f"{_BASE}/{library_id}").json()["document_set_ids"] == [_SET_1]

    def test_adding_the_same_set_twice_returns_400(self, client: TestClient) -> None:
        library_id = _create(client)["library_id"]
        client.put(f"{_BASE}/{library_id}/document-sets", params={"document_sets_ids": _SET_1})

        response = client.put(f"{_BASE}/{library_id}/document-sets", params={"document_sets_ids": _SET_1})

        assert response.status_code == 400

    def test_list_for_unknown_library_returns_404(self, client: TestClient) -> None:
        assert client.get(f"{_BASE}/{_UNKNOWN}/document-sets").status_code == 404

    def test_missing_ids_parameter_returns_400(self, client: TestClient) -> None:
        library_id = _create(client)["library_id"]

        assert client.put(f"{_BASE}/{library_id}/document-sets").status_code == 400


def test_delete_removes_library_but_not_document_sets(
    client: TestClient, document_set_service: FakeDocumentSetService
) -> None:
    library_id = _create(client)["library_id"]
    client.put(f"{_BASE}/{library_id}/document-sets", params={"document_sets_ids": _SET_1})

    response = client.delete(f"{_BASE}/{library_id}")

    assert response.status_code == 204
    assert client.get(f"{_BASE}/{library_id}").status_code == 404
    assert document_set_service.get_document_set(document_set_id=_SET_1).name == "Contracts"
