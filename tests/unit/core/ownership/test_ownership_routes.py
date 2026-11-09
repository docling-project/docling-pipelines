# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Route-level ownership tests: actor wiring, 403 mapping and ownership fields in responses."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from docpipe.api.auth.dependencies import get_current_user
from docpipe.api.auth.models import User
from docpipe.api.auth.roles import Role
from docpipe.api.dependencies import get_flow_service, get_job_management_service, get_project_service
from docpipe.api.middleware.error_handler import docpipe_exception_handler
from docpipe.api.routes.flows import flows_router
from docpipe.api.routes.job_runs import job_runs_router
from docpipe.api.routes.projects import projects_router
from docpipe.core.job_management.application.services.job_management_service import JobManagementService
from docpipe.core.job_management.domain.models import JobStats
from docpipe.core.projects.application.services.project_service import ProjectService
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from tests.unit.core.ownership.conftest import make_flow

AUTHORING_FLOW = {
    "flow_name": "owned-flow",
    "flow": [{"type": "ingest_source", "name": "ingest", "config": {}, "depends_on": []}],
    "global_config": {},
}


@pytest.fixture
def current_user():
    """Mutable holder so a test can switch the authenticated user."""
    return {"user": User(username="alice", roles=[Role.EDITOR])}


@pytest.fixture
def app(current_user, flow_service, flow_repo, project_repo, job_stats_service, mocker):
    app = FastAPI()
    app.include_router(flows_router)
    app.include_router(projects_router)
    app.include_router(job_runs_router)
    app.add_exception_handler(DocpipeException, docpipe_exception_handler)

    project_service = ProjectService(
        repository=project_repo,  # type: ignore[arg-type]
        flow_repository=flow_repo,  # type: ignore[arg-type]
        flow_service=flow_service,
        job_stats_service=job_stats_service,
    )
    job_service = JobManagementService(
        job_stats_service=job_stats_service,
        job_run_manager=mocker.Mock(),
        flow_service=flow_service,
        executor=mocker.Mock(),
    )
    app.dependency_overrides[get_current_user] = lambda: current_user["user"]
    app.dependency_overrides[get_flow_service] = lambda: flow_service
    app.dependency_overrides[get_project_service] = lambda: project_service
    app.dependency_overrides[get_job_management_service] = lambda: job_service
    return app


@pytest.fixture
def client(app, auth_enabled):
    return TestClient(app, raise_server_exceptions=False)


def test_create_flow_records_creator(client):
    response = client.post("/flows", json=AUTHORING_FLOW)

    assert response.status_code == 201
    assert response.json()["created_by"] == "alice"


def test_other_editor_gets_403_on_put_patch_delete(client, current_user, flow_repo):
    flow_repo.save(asset=make_flow(flow_id="11111111-1111-4111-8111-111111111111", created_by="bob"))
    url = "/flows/11111111-1111-4111-8111-111111111111"

    assert client.put(url, json=AUTHORING_FLOW).status_code == 403
    assert client.patch(url, json={"description": "x"}).status_code == 403
    response = client.delete(url)

    assert response.status_code == 403
    assert response.json()["errors"][0]["code"] == "forbidden"
    assert "bob" not in response.text
    assert "11111111-1111-4111-8111-111111111111" in flow_repo.flows


def test_admin_deletes_foreign_flow(client, current_user, flow_repo):
    flow_repo.save(asset=make_flow(flow_id="11111111-1111-4111-8111-111111111111", created_by="bob"))
    current_user["user"] = User(username="root", roles=[Role.ADMIN])

    assert client.delete("/flows/11111111-1111-4111-8111-111111111111").status_code == 204


def test_auth_disabled_has_no_actor_and_leaves_owner_empty(app):
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/flows", json=AUTHORING_FLOW)

    assert response.status_code == 201
    assert response.json()["created_by"] is None


def test_create_project_records_creator_and_foreign_delete_is_403(client, current_user):
    created = client.post("/projects", json={"name": "proj"}).json()
    assert created["created_by"] == "alice"

    current_user["user"] = User(username="bob", roles=[Role.EDITOR])
    response = client.delete(f"/projects/{created['project_id']}")

    assert response.status_code == 403
    assert client.get(f"/projects/{created['project_id']}").status_code == 200


def test_job_run_cancel_and_delete_by_non_owner_is_403(client, current_user, job_stats_service):
    job_stats_service.get_job_run_stats.return_value = JobStats(
        job_id="j", job_run_id="99ecd646-bb8e-494a-a0c5-86b40c1d4f90", flow_id="f", user_id="bob"
    )
    run_url = "/job_runs/99ecd646-bb8e-494a-a0c5-86b40c1d4f90"

    assert client.post(f"{run_url}/cancel").status_code == 403
    assert client.delete(run_url).status_code == 403
    job_stats_service.request_cancel_job.assert_not_called()
    job_stats_service.request_delete_job_run.assert_not_called()


def test_job_run_list_exposes_user_id(client, job_stats_service):
    job_stats_service.list_job_runs.return_value = [
        JobStats(
            job_id="550e8400-e29b-41d4-a716-446655440000",
            job_run_id="99ecd646-bb8e-494a-a0c5-86b40c1d4f90",
            flow_id="f",
            flow_name="n",
            user_id="alice",
        )
    ]

    response = client.get("/job_runs")

    assert response.status_code == 200
    assert response.json()["list"][0]["user_id"] == "alice"
