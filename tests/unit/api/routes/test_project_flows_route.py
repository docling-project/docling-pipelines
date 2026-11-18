"""Route-level unit tests for GET /projects/{project_id}/flows."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from docpipe.api.dependencies import get_project_service
from docpipe.api.main import app
from docpipe.core.assets.flows.domain.models.flow import Flow
from docpipe.core.projects.domain.models.flow_job_run_summary import FlowJobRunSummary
from docpipe.exceptions.docpipe_exceptions import ProjectNotFoundException

PROJECT_ID = "aaaa0000-0000-0000-0000-000000000001"
FLOW_ID_1 = "bbbb0000-0000-0000-0000-000000000001"
RUN_ID_1 = "dddd0000-0000-0000-0000-000000000001"

NOW = datetime.now(UTC)


def _make_flow(flow_id: str = FLOW_ID_1) -> Flow:
    return Flow(
        asset_id=flow_id,
        name="Invoice Pipeline",
        definition={"flow_name": "test", "flow": []},
        container_id=PROJECT_ID,
        container_kind="project",
        tags=["invoice"],
        created_on=NOW,
        modified_on=NOW,
    )


def _make_summary() -> FlowJobRunSummary:
    return FlowJobRunSummary(
        total_runs=3,
        last_run_id=RUN_ID_1,
        last_run_status="Completed",
        last_run_start_time=1000,
        status_counts={"Completed": 3},
    )


def _mock_service(
    flows: list | None = None,
    summaries: dict | None = None,
    count: int = 0,
    raise_404: bool = False,
) -> MagicMock:
    svc = MagicMock()
    if raise_404:
        svc.get_project_flows_with_run_summary.side_effect = ProjectNotFoundException(project_id=PROJECT_ID)
    else:
        svc.get_project_flows_with_run_summary.return_value = (
            flows or [],
            summaries or {},
            count,
        )
    return svc


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def _client_with(svc: MagicMock) -> TestClient:
    app.dependency_overrides[get_project_service] = lambda: svc
    return TestClient(app)


# ── Tests ────────────────────────────────────────────────────────────────────


def test_list_project_flows_returns_200():
    flow = _make_flow()
    summary = _make_summary()
    svc = _mock_service(flows=[flow], summaries={FLOW_ID_1: summary}, count=1)
    client = _client_with(svc)

    resp = client.get(f"/api/v1/projects/{PROJECT_ID}/flows")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] == 1
    assert len(body["flows"]) == 1
    assert body["flows"][0]["flow_id"] == FLOW_ID_1
    assert body["flows"][0]["name"] == "Invoice Pipeline"
    assert body["flows"][0]["job_run_summary"]["total_runs"] == 3


def test_list_project_flows_returns_empty_list_when_no_flows():
    svc = _mock_service(flows=[], summaries={}, count=0)
    client = _client_with(svc)

    resp = client.get(f"/api/v1/projects/{PROJECT_ID}/flows")

    assert resp.status_code == 200
    assert resp.json()["flows"] == []
    assert resp.json()["total_count"] == 0


def test_list_project_flows_returns_404_for_unknown_project():
    svc = _mock_service(raise_404=True)
    client = _client_with(svc)

    resp = client.get(f"/api/v1/projects/{PROJECT_ID}/flows")

    assert resp.status_code == 404


def test_list_project_flows_invalid_project_id_returns_400():
    svc = _mock_service()
    client = _client_with(svc)

    resp = client.get("/api/v1/projects/not-a-uuid/flows")

    assert resp.status_code == 400


def test_list_project_flows_job_run_summary_null_when_no_runs():
    flow = _make_flow()
    svc = _mock_service(flows=[flow], summaries={}, count=1)
    client = _client_with(svc)

    resp = client.get(f"/api/v1/projects/{PROJECT_ID}/flows")

    assert resp.status_code == 200
    assert resp.json()["flows"][0]["job_run_summary"] is None


def test_list_project_flows_pagination_links_correct():
    flows = [_make_flow(f"bbbb0000-0000-0000-0000-00000000000{i}") for i in range(1, 4)]
    svc = _mock_service(flows=flows, summaries={}, count=10)
    client = _client_with(svc)

    resp = client.get(f"/api/v1/projects/{PROJECT_ID}/flows?limit=3&offset=3")

    assert resp.status_code == 200
    body = resp.json()
    assert "next" in body
    assert "prev" in body
    assert body["prev"] is not None
    assert body["next"] is not None


def test_list_project_flows_name_filter_forwarded_to_service():
    svc = _mock_service(flows=[], summaries={}, count=0)
    client = _client_with(svc)

    client.get(f"/api/v1/projects/{PROJECT_ID}/flows?name=invoice&is_elyra=true")

    call_kwargs = svc.get_project_flows_with_run_summary.call_args.kwargs
    assert call_kwargs["name_filter"] == "invoice"
    assert call_kwargs["is_elyra"] is True


def test_list_project_flows_pagination_links_preserve_filters():
    flows = [_make_flow(f"bbbb0000-0000-0000-0000-00000000000{i}") for i in range(1, 4)]
    svc = _mock_service(flows=flows, summaries={}, count=10)
    client = _client_with(svc)

    resp = client.get(f"/api/v1/projects/{PROJECT_ID}/flows?limit=3&offset=3&name=invoice&tags=etl")

    assert resp.status_code == 200
    body = resp.json()
    for link in (body["first"], body["next"], body["prev"]):
        assert link is not None
        assert "name=invoice" in link
        assert "tags=etl" in link
