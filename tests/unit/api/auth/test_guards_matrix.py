# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Permission matrix: every write route refuses callers below the required role."""

import logging
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from docpipe.api import dependencies as deps
from docpipe.api.auth.dependencies import get_current_user
from docpipe.api.auth.models import User
from docpipe.api.auth.roles import Role
from docpipe.api.middleware.error_handler import docpipe_exception_handler
from docpipe.api.routes.custom_operators import custom_operators_router
from docpipe.api.routes.document_classes import document_classes_router
from docpipe.api.routes.document_libraries import document_libraries_router
from docpipe.api.routes.document_sets import document_sets_router
from docpipe.api.routes.event_mappings import event_mappings_router
from docpipe.api.routes.flows import flows_router
from docpipe.api.routes.job_runs import job_runs_router
from docpipe.api.routes.operators import operators_router
from docpipe.api.routes.projects import projects_router
from docpipe.api.routes.providers import providers_router
from docpipe.api.routes.validation import validation_router
from docpipe.exceptions.docpipe_exceptions import DocpipeException

ID = "11111111-1111-4111-8111-111111111111"

# (method, path, minimum role). Bodies are omitted on purpose: the guard runs before
# body validation, so a caller that passes the guard gets 422 or 500, never 401/403.
WRITE_ROUTES: list[tuple[str, str, Role]] = [
    ("POST", "/flows", Role.EDITOR),
    ("PUT", f"/flows/{ID}", Role.EDITOR),
    ("PATCH", f"/flows/{ID}", Role.EDITOR),
    ("DELETE", f"/flows/{ID}", Role.EDITOR),
    ("DELETE", "/flows", Role.EDITOR),
    ("POST", "/projects", Role.EDITOR),
    ("PUT", f"/projects/{ID}", Role.EDITOR),
    ("PATCH", f"/projects/{ID}", Role.EDITOR),
    ("DELETE", f"/projects/{ID}", Role.EDITOR),
    ("POST", "/event_mappings", Role.EDITOR),
    ("PUT", "/event_mappings/key", Role.EDITOR),
    ("DELETE", "/event_mappings/key", Role.EDITOR),
    ("POST", "/job_runs", Role.EDITOR),
    ("POST", f"/job_runs/{ID}/cancel", Role.EDITOR),
    ("DELETE", f"/job_runs/{ID}", Role.EDITOR),
    ("POST", "/document-sets", Role.EDITOR),
    ("PATCH", f"/document-sets/{ID}", Role.EDITOR),
    ("DELETE", f"/document-sets/{ID}", Role.EDITOR),
    ("POST", "/document-libraries", Role.EDITOR),
    ("PATCH", f"/document-libraries/{ID}", Role.EDITOR),
    ("DELETE", f"/document-libraries/{ID}", Role.EDITOR),
    ("PUT", f"/document-libraries/{ID}/document-sets", Role.EDITOR),
    ("DELETE", f"/document-libraries/{ID}/document-sets", Role.EDITOR),
    ("POST", "/custom_operators", Role.ADMIN),
    ("PATCH", f"/custom_operators/{ID}", Role.ADMIN),
    ("DELETE", f"/custom_operators/{ID}", Role.ADMIN),
]

# Read-only routes, including the two read-only POSTs under validation.
VIEWER_ROUTES: list[tuple[str, str]] = [
    ("GET", "/flows"),
    ("GET", "/projects"),
    ("GET", "/event_mappings"),
    ("GET", "/job_runs"),
    ("GET", "/document-sets"),
    ("GET", "/document-libraries"),
    ("GET", "/document_classes"),
    ("GET", "/custom_operators"),
    ("GET", "/operators/metadata"),
    ("POST", "/validation/validate_flow"),
    ("POST", "/validation/enrich_flow_features"),
]

ROLES = [Role.VIEWER, Role.EDITOR, Role.ADMIN]


@pytest.fixture
def current_user():
    return {"user": User(username="alice", roles=[Role.VIEWER])}


@pytest.fixture
def app(current_user):
    app = FastAPI()
    for router in (
        flows_router,
        projects_router,
        event_mappings_router,
        job_runs_router,
        document_sets_router,
        document_libraries_router,
        document_classes_router,
        custom_operators_router,
        operators_router,
        providers_router,
        validation_router,
    ):
        app.include_router(router)
    app.add_exception_handler(DocpipeException, docpipe_exception_handler)
    app.dependency_overrides[get_current_user] = lambda: current_user["user"]
    for name in (
        "get_flow_service",
        "get_project_service",
        "get_event_mapping_service",
        "get_job_management_service",
        "get_job_stats_service",
        "get_document_set_service",
        "get_document_library_service",
        "get_custom_operator_service",
    ):
        app.dependency_overrides[getattr(deps, name)] = lambda: MagicMock()
    return app


@pytest.fixture
def client(app, auth_enabled):
    return TestClient(app, raise_server_exceptions=False)


def _as(current_user, role: Role) -> None:
    current_user["user"] = User(username="alice", roles=[role])


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize(("method", "path", "minimum"), WRITE_ROUTES)
def test_write_route_matrix(client, current_user, role, method, path, minimum):
    _as(current_user, role)

    response = client.request(method, path)

    if role >= minimum:
        assert response.status_code not in (401, 403)
    else:
        assert response.status_code == 403
        assert response.json()["errors"][0]["code"] == "forbidden"


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize(("method", "path"), VIEWER_ROUTES)
def test_viewer_can_call_read_routes(client, current_user, role, method, path):
    _as(current_user, role)

    response = client.request(method, path)

    assert response.status_code not in (401, 403)


def test_unknown_roles_fall_back_to_viewer(client, current_user):
    current_user["user"] = User(username="alice")

    assert client.post("/flows").status_code == 403
    assert client.get("/flows").status_code not in (401, 403)


def test_highest_role_wins(client, current_user):
    current_user["user"] = User(username="alice", roles=[Role.VIEWER, Role.EDITOR])

    assert client.post("/flows").status_code not in (401, 403)
    assert client.post("/custom_operators").status_code == 403


def test_guard_allows_everything_when_auth_disabled(app):
    client = TestClient(app, raise_server_exceptions=False)

    assert client.post("/custom_operators").status_code not in (401, 403)
    assert client.delete(f"/flows/{ID}").status_code not in (401, 403)


def test_denial_is_audited(client, current_user):
    logger = logging.getLogger("docpipe.audit")
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture()
    logger.addHandler(handler)
    try:
        client.post("/flows")
    finally:
        logger.removeHandler(handler)

    messages = [r.getMessage() for r in records]
    assert any("user=alice" in m and "outcome=denied" in m and "target=/flows" in m for m in messages)
