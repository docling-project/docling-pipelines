"""Route tests for /documents (ACL-filtered OpenSearch reads), following
openspec/specs/backend/documents-api.

OpenSearch is replaced by a fake client that records the query body it receives, so the
tests can check that the ACL filter for the authenticated user is part of every request.
"""

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opensearchpy.exceptions import NotFoundError, RequestError

from docpipe.api.auth.dependencies import get_current_user
from docpipe.api.auth.models import User
from docpipe.api.routes.documents import documents_router
from docpipe.api.services.opensearch_service import get_opensearch_service

_ACL_FILTER = {"term": {"allowed_users": "alice"}}


class FakeClient:
    def __init__(self, result: dict | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def search(self, *, index: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"index": index, "body": body})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeConfig:
    opensearch_default_index = "acl-documents"


class FakeOpenSearchService:
    def __init__(self, client: FakeClient) -> None:
        self.client = client
        self.config = FakeConfig()

    def get_client(self) -> FakeClient:
        return self.client


def _hit(doc_id: str, **source: Any) -> dict[str, Any]:
    return {"_id": doc_id, "_source": source}


def _client_for(result: dict | Exception) -> tuple[TestClient, FakeClient]:
    fake = FakeClient(result)
    app = FastAPI()
    app.include_router(documents_router)
    app.dependency_overrides[get_current_user] = lambda: User(username="alice", email="alice@example.com")
    app.dependency_overrides[get_opensearch_service] = lambda: FakeOpenSearchService(fake)
    return TestClient(app, raise_server_exceptions=False), fake


def _must_clauses(body: dict[str, Any]) -> list[dict[str, Any]]:
    return body["query"]["bool"]["must"]


class TestGetDocument:
    """GET /documents/{document_id}."""

    def test_returns_document_with_acl_filtered_query(self) -> None:
        hit = _hit(
            "doc-1",
            content="Quarterly report",
            metadata={"category": "finance"},
            created_at="2026-05-01T10:00:00Z",
            updated_at="2026-05-15T14:30:00Z",
        )
        client, fake = _client_for({"hits": {"hits": [hit]}})

        response = client.get("/documents/doc-1")

        assert response.status_code == 200
        body = response.json()
        assert (body["id"], body["content"], body["metadata"]) == ("doc-1", "Quarterly report", {"category": "finance"})
        assert fake.calls[0]["index"] == "acl-documents"
        assert {"term": {"_id": "doc-1"}} in _must_clauses(fake.calls[0]["body"])
        assert _ACL_FILTER in _must_clauses(fake.calls[0]["body"])

    def test_text_field_is_used_when_content_is_missing(self) -> None:
        client, _ = _client_for({"hits": {"hits": [_hit("doc-2", text="Plain text body")]}})

        assert client.get("/documents/doc-2").json()["content"] == "Plain text body"

    def test_missing_or_unauthorised_document_returns_404(self) -> None:
        client, _ = _client_for({"hits": {"hits": []}})

        response = client.get("/documents/doc-404")

        assert response.status_code == 404
        assert response.json()["detail"] == "Document not found"

    @pytest.mark.parametrize(
        ("error", "status", "detail"),
        [
            (NotFoundError(404, "index_not_found_exception", {}), 503, "Document service unavailable"),
            (RequestError(400, "parsing_exception", {}), 400, "Invalid document request"),
            (ConnectionError("cluster unreachable"), 503, "Document service error"),
        ],
    )
    def test_opensearch_errors(self, error: Exception, status: int, detail: str) -> None:
        client, _ = _client_for(error)

        response = client.get("/documents/doc-1")

        assert response.status_code == status
        assert response.json()["detail"] == detail


class TestSearchDocuments:
    """POST /documents/search."""

    def test_search_applies_acl_query_and_pagination(self) -> None:
        result = {"hits": {"total": {"value": 42}, "hits": [_hit("doc-1", content="ML basics"), _hit("doc-2")]}}
        client, fake = _client_for(result)

        response = client.post(
            "/documents/search",
            json={
                "query": "machine learning",
                "filters": {"metadata.category": "tech"},
                "sort": [{"created_at": "desc"}],
                "limit": 2,
                "offset": 20,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert [d["id"] for d in body["documents"]] == ["doc-1", "doc-2"]
        assert (body["total"], body["limit"], body["offset"], body["has_more"]) == (42, 2, 20, True)
        sent = fake.calls[0]["body"]
        assert (sent["size"], sent["from"]) == (2, 20)
        assert _ACL_FILTER in _must_clauses(sent)

    def test_missing_index_returns_empty_result(self) -> None:
        client, _ = _client_for(NotFoundError(404, "index_not_found_exception", {}))

        response = client.post("/documents/search", json={"limit": 10, "offset": 0})

        assert response.status_code == 200
        assert response.json() == {"documents": [], "total": 0, "limit": 10, "offset": 0, "has_more": False}

    @pytest.mark.parametrize(
        ("error", "status", "detail"),
        [
            (RequestError(400, "parsing_exception", {}), 400, "Invalid search request"),
            (ConnectionError("cluster unreachable"), 503, "Document search service error"),
        ],
    )
    def test_opensearch_errors(self, error: Exception, status: int, detail: str) -> None:
        client, _ = _client_for(error)

        response = client.post("/documents/search", json={"query": "anything"})

        assert response.status_code == status
        assert response.json()["detail"] == detail
