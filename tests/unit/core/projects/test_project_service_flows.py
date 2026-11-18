"""Unit tests for ProjectService project-flows methods."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from docpipe.core.assets.flows.domain.models.flow import Flow
from docpipe.core.constants.constants import ExecutionStatus
from docpipe.core.job_management.domain.models.job_stats import JobStats
from docpipe.core.projects.application.services.project_service import ProjectService
from docpipe.core.projects.domain.models.project import Project
from docpipe.exceptions.docpipe_exceptions import ProjectNotFoundException

# ── Fixtures ────────────────────────────────────────────────────────────────


def _make_project(project_id: str = "aaaa0000-0000-0000-0000-000000000001") -> Project:
    return Project(
        project_id=project_id,
        name="Test Project",
        created_on=datetime.now(UTC),
        modified_on=datetime.now(UTC),
    )


def _make_flow(flow_id: str, container_id: str) -> Flow:
    return Flow(
        asset_id=flow_id,
        name=f"Flow {flow_id[:4]}",
        definition={"flow_name": "test", "flow": []},
        container_id=container_id,
        container_kind="project",
    )


def _make_job_stats(job_id: str, job_run_id: str, status: ExecutionStatus, start_time: int) -> JobStats:
    return JobStats(
        job_id=job_id,
        job_run_id=job_run_id,
        status=status,
        start_time=start_time,
    )


def _make_service(
    project: Project | None = None,
    flows: list[Flow] | None = None,
    job_runs: list[JobStats] | None = None,
) -> ProjectService:
    repo = MagicMock()
    repo.get.return_value = project
    repo.exists.return_value = project is not None

    flow_repo = MagicMock()
    flow_repo.find_all.return_value = flows or []

    flow_service = MagicMock()
    flow_service.list_flows.return_value = flows or []
    flow_service.count_flows.return_value = len(flows or [])

    job_stats_service = MagicMock()
    job_stats_service.list_job_runs.return_value = job_runs or []

    return ProjectService(
        repository=repo,
        flow_repository=flow_repo,
        flow_service=flow_service,
        job_stats_service=job_stats_service,
    )


PROJECT_ID = "aaaa0000-0000-0000-0000-000000000001"
FLOW_ID_1 = "bbbb0000-0000-0000-0000-000000000001"
FLOW_ID_2 = "cccc0000-0000-0000-0000-000000000002"
RUN_ID_1 = "dddd0000-0000-0000-0000-000000000001"
RUN_ID_2 = "eeee0000-0000-0000-0000-000000000002"
RUN_ID_3 = "ffff0000-0000-0000-0000-000000000003"


# ── get_project_flows_with_run_summary ───────────────────────────────────────


def test_get_project_flows_passes_container_id_and_is_elyra_to_flow_service():
    project = _make_project(PROJECT_ID)
    flows = [_make_flow(FLOW_ID_1, PROJECT_ID)]
    svc = _make_service(project=project, flows=flows)

    svc.get_project_flows_with_run_summary(project_id=PROJECT_ID, is_elyra=True)

    svc._flow_service.list_flows.assert_called_once()
    call_kwargs = svc._flow_service.list_flows.call_args.kwargs
    assert call_kwargs["container_id"] == PROJECT_ID
    assert call_kwargs["is_elyra"] is True


def test_get_project_flows_raises_404_for_unknown_project():
    svc = _make_service(project=None)
    svc._repository.get.return_value = None

    with pytest.raises(ProjectNotFoundException):
        svc.get_project_flows_with_run_summary(project_id=PROJECT_ID)

    svc._flow_service.list_flows.assert_not_called()


def test_get_project_flows_returns_summaries_keyed_by_flow_id():
    project = _make_project(PROJECT_ID)
    flows = [_make_flow(FLOW_ID_1, PROJECT_ID)]
    runs = [_make_job_stats(FLOW_ID_1, RUN_ID_1, ExecutionStatus.COMPLETED, 1000)]
    svc = _make_service(project=project, flows=flows, job_runs=runs)

    returned_flows, summaries, total = svc.get_project_flows_with_run_summary(project_id=PROJECT_ID)

    assert returned_flows == flows
    assert total == 1
    assert FLOW_ID_1 in summaries
    assert summaries[FLOW_ID_1].total_runs == 1


def test_get_project_flows_count_matches_flow_service_count_flows():
    project = _make_project(PROJECT_ID)
    flows = [_make_flow(FLOW_ID_1, PROJECT_ID), _make_flow(FLOW_ID_2, PROJECT_ID)]
    svc = _make_service(project=project, flows=flows)

    _, _, total = svc.get_project_flows_with_run_summary(project_id=PROJECT_ID)

    assert total == 2
    call_kwargs = svc._flow_service.count_flows.call_args.kwargs
    assert call_kwargs["container_id"] == PROJECT_ID


# ── _build_job_run_summaries ──────────────────────────────────────────────────


def test_build_job_run_summaries_groups_by_job_id():
    runs = [
        _make_job_stats(FLOW_ID_1, RUN_ID_1, ExecutionStatus.COMPLETED, 1000),
        _make_job_stats(FLOW_ID_1, RUN_ID_2, ExecutionStatus.FAILED, 2000),
        _make_job_stats(FLOW_ID_2, RUN_ID_3, ExecutionStatus.RUNNING, 3000),
    ]
    project = _make_project(PROJECT_ID)
    svc = _make_service(project=project, job_runs=runs)

    summaries = svc._build_job_run_summaries(flow_ids=[FLOW_ID_1, FLOW_ID_2])

    assert summaries[FLOW_ID_1].total_runs == 2
    assert summaries[FLOW_ID_1].status_counts["Completed"] == 1
    assert summaries[FLOW_ID_1].status_counts["Failed"] == 1
    assert summaries[FLOW_ID_2].total_runs == 1


def test_build_job_run_summaries_returns_empty_for_no_matching_runs():
    project = _make_project(PROJECT_ID)
    svc = _make_service(project=project, job_runs=[])

    result = svc._build_job_run_summaries(flow_ids=[FLOW_ID_1])

    assert result == {}


def test_build_job_run_summaries_returns_empty_for_empty_flow_ids():
    project = _make_project(PROJECT_ID)
    svc = _make_service(project=project)

    result = svc._build_job_run_summaries(flow_ids=[])

    assert result == {}
    svc._job_stats_service.list_job_runs.assert_not_called()


def test_build_job_run_summaries_latest_run_is_highest_start_time():
    runs = [
        _make_job_stats(FLOW_ID_1, RUN_ID_1, ExecutionStatus.COMPLETED, 1000),
        _make_job_stats(FLOW_ID_1, RUN_ID_2, ExecutionStatus.FAILED, 9000),  # latest
    ]
    project = _make_project(PROJECT_ID)
    svc = _make_service(project=project, job_runs=runs)

    summaries = svc._build_job_run_summaries(flow_ids=[FLOW_ID_1])

    assert summaries[FLOW_ID_1].last_run_id == RUN_ID_2
    assert summaries[FLOW_ID_1].last_run_status == "Failed"
    assert summaries[FLOW_ID_1].last_run_start_time == 9000
