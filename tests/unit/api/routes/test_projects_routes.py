# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for Project API routes and ProjectMapper."""

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from docpipe.api.dependencies import get_project_service
from docpipe.api.dto.mappers.project_mapper import ProjectMapper
from docpipe.api.dto.project_dto import ProjectCreateRequest, ProjectUpdateRequest
from docpipe.api.routes.projects import projects_router
from docpipe.core.projects.application.services.project_service import ProjectService
from docpipe.core.projects.domain.models.project import Project
from docpipe.exceptions.docpipe_exceptions import (
    ProjectAlreadyExistsException,
    ProjectInvalidDataException,
    ProjectNotFoundException,
)

# ── Constants ────────────────────────────────────────────────────────────

_PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"
_CREATED_ON = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
_MODIFIED_ON = datetime(2024, 1, 2, 12, 0, 0, tzinfo=UTC)


# ── Shared fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def app():
    """FastAPI app wired with projects_router and the same exception handlers as main.py."""
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
    app.include_router(projects_router)
    app.add_exception_handler(DocpipeException, docpipe_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
    return app


@pytest.fixture
def client(app):
    """Test client that converts server exceptions to HTTP responses."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def mock_service():
    """Mock ProjectService."""
    return Mock(spec=ProjectService)


@pytest.fixture
def override_service(app, mock_service):
    """Override the get_project_service FastAPI dependency."""
    app.dependency_overrides[get_project_service] = lambda: mock_service
    yield mock_service
    app.dependency_overrides.clear()


@pytest.fixture
def sample_project():
    """A fully-populated Project domain model."""
    return Project(
        project_id=_PROJECT_ID,
        name="Invoice-Processing",
        description="Flows for processing invoices",
        tags=["finance", "invoices"],
        created_on=_CREATED_ON,
        modified_on=_MODIFIED_ON,
        created_by="alice@example.com",
        modified_by=None,
        href=None,
        flow_count=3,
    )


# ── POST /projects ────────────────────────────────────────────────────────


class TestCreateProjectEndpoint:
    """Tests for POST /projects."""

    def test_create_project_returns_201(self, client, override_service, sample_project):
        """Happy path: valid body → 201 with project data."""
        override_service.create_project.return_value = sample_project

        resp = client.post(
            "/projects",
            json={"name": "Invoice-Processing", "description": "Flows for processing invoices"},
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["project_id"] == _PROJECT_ID
        assert data["name"] == "Invoice-Processing"
        assert data["flow_count"] == 3

    def test_create_project_returns_409_on_duplicate_name(self, client, override_service):
        """Duplicate name → 409 Conflict."""
        override_service.create_project.side_effect = ProjectAlreadyExistsException(project_name="Invoice-Processing")

        resp = client.post("/projects", json={"name": "Invoice-Processing"})

        assert resp.status_code == 409

    def test_create_project_returns_400_on_service_validation_error(self, client, override_service):
        """Service-level validation failure → 400."""
        override_service.create_project.side_effect = ProjectInvalidDataException(
            "Project name cannot be empty", field_name="name"
        )

        resp = client.post("/projects", json={"name": "Valid-Name"})

        assert resp.status_code == 400

    def test_create_project_missing_required_name_returns_400(self, client, override_service):
        """Missing required 'name' field → 400 (validation handler returns 400, not 422)."""
        resp = client.post("/projects", json={"description": "No name given"})

        assert resp.status_code == 400

    def test_create_project_with_tags_deduplicates(self, client, override_service, sample_project):
        """Tags are deduplicated before reaching the service."""
        override_service.create_project.return_value = sample_project

        resp = client.post(
            "/projects",
            json={"name": "Invoice-Processing", "tags": ["finance", "finance", "invoices"]},
        )

        assert resp.status_code == 201
        call_kwargs = override_service.create_project.call_args
        project_arg = call_kwargs.kwargs["project"]
        assert project_arg.tags.count("finance") == 1


# ── GET /projects ─────────────────────────────────────────────────────────


class TestListProjectsEndpoint:
    """Tests for GET /projects."""

    def test_list_projects_returns_200(self, client, override_service, sample_project):
        """Happy path: returns paginated list."""
        override_service.list_projects.return_value = [sample_project]
        override_service.count_projects.return_value = 1

        resp = client.get("/projects")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 1
        assert len(data["projects"]) == 1
        assert data["projects"][0]["project_id"] == _PROJECT_ID

    def test_list_projects_empty_returns_200(self, client, override_service):
        """No projects → 200 with empty list."""
        override_service.list_projects.return_value = []
        override_service.count_projects.return_value = 0

        resp = client.get("/projects")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 0
        assert data["projects"] == []

    def test_list_projects_pagination_params_forwarded(self, client, override_service):
        """skip/limit query params are passed to the service."""
        override_service.list_projects.return_value = []
        override_service.count_projects.return_value = 0

        client.get("/projects?offset=10&limit=5")

        override_service.list_projects.assert_called_once_with(skip=10, limit=5, name_filter=None, tags_filter=None)

    def test_list_projects_name_filter_forwarded(self, client, override_service, sample_project):
        """name query param is forwarded as name_filter."""
        override_service.list_projects.return_value = [sample_project]
        override_service.count_projects.return_value = 1

        client.get("/projects?name=invoice")

        call_kwargs = override_service.list_projects.call_args.kwargs
        assert call_kwargs["name_filter"] == "invoice"

    def test_list_projects_invalid_limit_returns_400(self, client, override_service):
        """limit > LIMIT_MAX → 400 (validation handler returns 400)."""
        resp = client.get("/projects?limit=9999")

        assert resp.status_code == 400

    def test_list_projects_negative_offset_returns_400(self, client, override_service):
        """offset < 0 → 400 (validation handler returns 400)."""
        resp = client.get("/projects?offset=-1")

        assert resp.status_code == 400


# ── GET /projects/{project_id} ────────────────────────────────────────────


class TestGetProjectEndpoint:
    """Tests for GET /projects/{project_id}."""

    def test_get_project_returns_200(self, client, override_service, sample_project):
        """Happy path: existing project_id → 200 with project data."""
        override_service.get_project.return_value = sample_project

        resp = client.get(f"/projects/{_PROJECT_ID}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == _PROJECT_ID
        assert data["name"] == "Invoice-Processing"

    def test_get_project_returns_404_when_not_found(self, client, override_service):
        """Non-existent ID → 404."""
        override_service.get_project.side_effect = ProjectNotFoundException(project_id=_PROJECT_ID)

        resp = client.get(f"/projects/{_PROJECT_ID}")

        assert resp.status_code == 404

    def test_get_project_invalid_uuid_returns_400(self, client, override_service):
        """Malformed UUID in path → 400 (validation handler returns 400)."""
        resp = client.get("/projects/not-a-uuid")

        assert resp.status_code == 400

    def test_get_project_calls_service_with_keyword_arg(self, client, override_service, sample_project):
        """Service is called with project_id as a keyword argument."""
        override_service.get_project.return_value = sample_project

        client.get(f"/projects/{_PROJECT_ID}")

        override_service.get_project.assert_called_once_with(project_id=_PROJECT_ID)


# ── PUT /projects/{project_id} ────────────────────────────────────────────


class TestReplaceProjectEndpoint:
    """Tests for PUT /projects/{project_id}."""

    def test_replace_project_returns_200(self, client, override_service, sample_project):
        """Happy path: valid body → 200 with updated project data."""
        override_service.get_project.return_value = sample_project
        override_service.update_project.return_value = sample_project

        resp = client.put(
            f"/projects/{_PROJECT_ID}",
            json={"name": "Invoice-Processing", "description": "Updated description"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == _PROJECT_ID

    def test_replace_project_returns_404_when_not_found(self, client, override_service):
        """Non-existent project → 404."""
        override_service.get_project.side_effect = ProjectNotFoundException(project_id=_PROJECT_ID)

        resp = client.put(
            f"/projects/{_PROJECT_ID}",
            json={"name": "Invoice-Processing"},
        )

        assert resp.status_code == 404

    def test_replace_project_missing_required_name_returns_400(self, client, override_service, sample_project):
        """PUT body without 'name' fails DTO validation → 400."""
        override_service.get_project.return_value = sample_project

        resp = client.put(
            f"/projects/{_PROJECT_ID}",
            json={"description": "No name"},
        )

        assert resp.status_code == 400

    def test_replace_project_invalid_uuid_returns_400(self, client, override_service):
        """Malformed UUID → 400."""
        resp = client.put("/projects/not-a-uuid", json={"name": "Test"})

        assert resp.status_code == 400

    def test_replace_project_calls_update_with_keyword_args(self, client, override_service, sample_project):
        """update_project called with project= keyword argument."""
        override_service.get_project.return_value = sample_project
        override_service.update_project.return_value = sample_project

        client.put(f"/projects/{_PROJECT_ID}", json={"name": "Invoice-Processing"})

        call_kwargs = override_service.update_project.call_args.kwargs
        assert "project" in call_kwargs


# ── PATCH /projects/{project_id} ─────────────────────────────────────────


class TestPartialUpdateProjectEndpoint:
    """Tests for PATCH /projects/{project_id}."""

    def test_partial_update_returns_200(self, client, override_service, sample_project):
        """Happy path: partial body → 200 with updated project data."""
        override_service.partial_update_project.return_value = sample_project

        resp = client.patch(
            f"/projects/{_PROJECT_ID}",
            json={"description": "New description"},
        )

        assert resp.status_code == 200
        assert resp.json()["project_id"] == _PROJECT_ID

    def test_partial_update_returns_404_when_not_found(self, client, override_service):
        """Non-existent project → 404."""
        override_service.partial_update_project.side_effect = ProjectNotFoundException(project_id=_PROJECT_ID)

        resp = client.patch(
            f"/projects/{_PROJECT_ID}",
            json={"description": "New description"},
        )

        assert resp.status_code == 404

    def test_partial_update_empty_body_returns_200(self, client, override_service, sample_project):
        """Empty PATCH body is valid — no fields to update."""
        override_service.partial_update_project.return_value = sample_project

        resp = client.patch(f"/projects/{_PROJECT_ID}", json={})

        assert resp.status_code == 200

    def test_partial_update_invalid_uuid_returns_400(self, client, override_service):
        """Malformed UUID → 400."""
        resp = client.patch("/projects/not-a-uuid", json={"name": "New-Name"})

        assert resp.status_code == 400

    def test_partial_update_returns_400_on_invalid_name(self, client, override_service):
        """Empty name string → 400 from service validation."""
        override_service.partial_update_project.side_effect = ProjectInvalidDataException(
            "Project name cannot be empty", field_name="name"
        )

        resp = client.patch(f"/projects/{_PROJECT_ID}", json={"name": "Valid-Name"})

        assert resp.status_code == 400

    def test_partial_update_only_sends_provided_fields(self, client, override_service, sample_project):
        """Only the fields present in the request body are forwarded as updates."""
        override_service.partial_update_project.return_value = sample_project

        client.patch(f"/projects/{_PROJECT_ID}", json={"description": "Only desc"})

        call_kwargs = override_service.partial_update_project.call_args.kwargs
        updates = call_kwargs["updates"]
        assert "description" in updates
        assert "name" not in updates


# ── DELETE /projects/{project_id} ────────────────────────────────────────


class TestDeleteProjectEndpoint:
    """Tests for DELETE /projects/{project_id}."""

    def test_delete_project_returns_204(self, client, override_service):
        """Happy path: existing project → 204 No Content."""
        override_service.delete_project.return_value = None

        resp = client.delete(f"/projects/{_PROJECT_ID}")

        assert resp.status_code == 204
        assert resp.content == b""

    def test_delete_project_returns_404_when_not_found(self, client, override_service):
        """Non-existent project → 404."""
        override_service.delete_project.side_effect = ProjectNotFoundException(project_id=_PROJECT_ID)

        resp = client.delete(f"/projects/{_PROJECT_ID}")

        assert resp.status_code == 404

    def test_delete_project_invalid_uuid_returns_400(self, client, override_service):
        """Malformed UUID → 400."""
        resp = client.delete("/projects/not-a-uuid")

        assert resp.status_code == 400

    def test_delete_project_calls_service_with_keyword_arg(self, client, override_service):
        """Service is called with project_id as keyword argument."""
        override_service.delete_project.return_value = None

        client.delete(f"/projects/{_PROJECT_ID}")

        override_service.delete_project.assert_called_once_with(project_id=_PROJECT_ID, actor=None)


# ── ProjectMapper unit tests ───────────────────────────────────────────────


class TestProjectMapper:
    """Unit tests for ProjectMapper static methods."""

    def test_create_request_to_domain_maps_all_fields(self):
        """create_request_to_domain produces a Project with the correct fields."""
        dto = ProjectCreateRequest(
            name="Invoice-Processing",
            description="Test desc",
            tags=["finance"],
            created_by="alice@example.com",
        )

        project = ProjectMapper.create_request_to_domain(dto=dto)

        assert project.name == "Invoice-Processing"
        assert project.description == "Test desc"
        assert project.tags == ["finance"]
        assert project.created_by == "alice@example.com"
        # auto-generated UUID should be 36 chars
        assert len(project.project_id) == 36

    def test_create_request_to_domain_defaults_tags_to_empty(self):
        """Tags default to [] when not provided."""
        dto = ProjectCreateRequest(name="My-Project")

        project = ProjectMapper.create_request_to_domain(dto=dto)

        assert project.tags == []

    def test_update_request_to_domain_preserves_immutable_fields(self):
        """Immutable fields (project_id, created_on, created_by) are taken from existing."""
        existing = Project(
            project_id=_PROJECT_ID,
            name="Old-Name",
            created_on=_CREATED_ON,
            created_by="alice@example.com",
        )
        dto = ProjectUpdateRequest(name="New-Name", modified_by="bob@example.com")

        project = ProjectMapper.update_request_to_domain(
            project_id=_PROJECT_ID,
            existing=existing,
            dto=dto,
        )

        assert project.project_id == _PROJECT_ID
        assert project.created_on == _CREATED_ON
        assert project.created_by == "alice@example.com"

    def test_update_request_to_domain_applies_new_mutable_fields(self):
        """Mutable fields are taken from the DTO."""
        existing = Project(project_id=_PROJECT_ID, name="Old-Name", created_on=_CREATED_ON)
        dto = ProjectUpdateRequest(
            name="New-Name",
            description="New desc",
            tags=["newtag"],
            modified_by="bob@example.com",
        )

        project = ProjectMapper.update_request_to_domain(
            project_id=_PROJECT_ID,
            existing=existing,
            dto=dto,
        )

        assert project.name == "New-Name"
        assert project.description == "New desc"
        assert project.tags == ["newtag"]
        assert project.modified_by == "bob@example.com"

    def test_domain_to_dto_maps_all_fields(self):
        """domain_to_dto produces a ProjectResponse with all domain fields."""
        project = Project(
            project_id=_PROJECT_ID,
            name="Invoice-Processing",
            description="Test",
            tags=["finance"],
            created_on=_CREATED_ON,
            modified_on=_MODIFIED_ON,
            created_by="alice@example.com",
            modified_by="bob@example.com",
            href="/api/v1/projects/550e8400-e29b-41d4-a716-446655440000",
            flow_count=5,
        )

        dto = ProjectMapper.domain_to_dto(project)

        assert dto.project_id == _PROJECT_ID
        assert dto.name == "Invoice-Processing"
        assert dto.description == "Test"
        assert dto.tags == ["finance"]
        assert dto.flow_count == 5
        assert dto.created_by == "alice@example.com"
        assert dto.modified_by == "bob@example.com"
        assert dto.href == "/api/v1/projects/550e8400-e29b-41d4-a716-446655440000"

    def test_domain_to_dto_flow_count_zero_by_default(self):
        """flow_count defaults to 0 when not set on the domain model."""
        project = Project(project_id=_PROJECT_ID, name="My-Project")

        dto = ProjectMapper.domain_to_dto(project)

        assert dto.flow_count == 0


# ── Pagination link-building tests ────────────────────────────────────────


def _make_project(n: int) -> Project:
    """Build a minimal Project with a deterministic ID."""
    return Project(
        project_id=f"550e8400-e29b-41d4-a716-{str(n).zfill(12)}",
        name=f"Project-{n}",
        created_on=_CREATED_ON,
        modified_on=_MODIFIED_ON,
    )


class TestListProjectsPaginationLinks:
    """Verify first/next/prev link construction in GET /projects."""

    def test_first_page_no_prev_has_next(self, client, override_service):
        """First page (offset=0) with more items → prev=None, next set."""
        override_service.list_projects.return_value = [_make_project(i) for i in range(5)]
        override_service.count_projects.return_value = 10

        data = client.get("/projects?offset=0&limit=5").json()

        assert data["prev"] is None
        assert data["next"] is not None
        assert "offset=5" in data["next"]
        assert "limit=5" in data["next"]
        assert "offset=0" in data["first"]

    def test_last_page_no_next_has_prev(self, client, override_service):
        """Last page → next=None, prev set."""
        override_service.list_projects.return_value = [_make_project(i) for i in range(3)]
        override_service.count_projects.return_value = 8

        data = client.get("/projects?offset=5&limit=5").json()

        assert data["next"] is None
        assert data["prev"] is not None
        assert "offset=0" in data["prev"]

    def test_middle_page_has_both_prev_and_next(self, client, override_service):
        """Middle page → both prev and next are set."""
        override_service.list_projects.return_value = [_make_project(i) for i in range(5)]
        override_service.count_projects.return_value = 20

        data = client.get("/projects?offset=5&limit=5").json()

        assert data["prev"] is not None
        assert data["next"] is not None
        assert "offset=0" in data["prev"]
        assert "offset=10" in data["next"]

    def test_exact_page_boundary_no_next(self, client, override_service):
        """offset + len(results) == total → next must be None."""
        override_service.list_projects.return_value = [_make_project(i) for i in range(5)]
        override_service.count_projects.return_value = 5

        data = client.get("/projects?offset=0&limit=5").json()

        assert data["next"] is None

    def test_empty_result_set_no_next_no_prev(self, client, override_service):
        """No projects → next=None, prev=None."""
        override_service.list_projects.return_value = []
        override_service.count_projects.return_value = 0

        data = client.get("/projects?offset=0&limit=10").json()

        assert data["prev"] is None
        assert data["next"] is None

    def test_first_link_always_offset_zero(self, client, override_service):
        """first link is always offset=0 regardless of current offset."""
        override_service.list_projects.return_value = [_make_project(i) for i in range(5)]
        override_service.count_projects.return_value = 30

        data = client.get("/projects?offset=10&limit=5").json()

        assert "offset=0" in data["first"]
        assert "limit=5" in data["first"]

    def test_name_filter_included_in_links(self, client, override_service):
        """name query param is forwarded into first and next links."""
        override_service.list_projects.return_value = [_make_project(i) for i in range(5)]
        override_service.count_projects.return_value = 20

        data = client.get("/projects?offset=0&limit=5&name=invoice").json()

        assert "name=invoice" in data["first"]
        assert "name=invoice" in data["next"]

    def test_prev_link_clamps_to_zero_when_offset_less_than_limit(self, client, override_service):
        """max(0, offset - limit) clamps prev offset to 0 when offset < limit."""
        override_service.list_projects.return_value = [_make_project(i) for i in range(3)]
        override_service.count_projects.return_value = 10

        data = client.get("/projects?offset=3&limit=5").json()

        assert "offset=0" in data["prev"]

    def test_next_offset_equals_current_offset_plus_limit(self, client, override_service):
        """next link offset = current offset + limit."""
        override_service.list_projects.return_value = [_make_project(i) for i in range(5)]
        override_service.count_projects.return_value = 30

        data = client.get("/projects?offset=10&limit=5").json()

        assert "offset=15" in data["next"]

    def test_prev_offset_equals_current_offset_minus_limit(self, client, override_service):
        """prev link offset = current offset - limit (when offset >= limit)."""
        override_service.list_projects.return_value = [_make_project(i) for i in range(5)]
        override_service.count_projects.return_value = 30

        data = client.get("/projects?offset=10&limit=5").json()

        assert "offset=5" in data["prev"]

    def test_offset_limit_total_reflected_in_response_body(self, client, override_service):
        """Response body offset, limit, and total_count echo request params and service result."""
        override_service.list_projects.return_value = [_make_project(i) for i in range(3)]
        override_service.count_projects.return_value = 10

        data = client.get("/projects?offset=2&limit=3").json()

        assert data["offset"] == 2
        assert data["limit"] == 3
        assert data["total_count"] == 10
