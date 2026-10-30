"""Unit tests for DefaultJobRunManager, on a real JobTrackerService over the in-memory store."""

import uuid

import pytest

from docpipe.core.constants.constants import DocpipeConstants, ExecutionStatus
from docpipe.core.job_management.adapters.frameworks import DefaultJobRunManager
from docpipe.core.job_management.adapters.services.job_tracker_service import JobTrackerService
from docpipe.core.job_management.adapters.stores.inmemory.inmemory_job_stats_store import InMemoryJobStatsStore
from docpipe.core.job_management.application.services.node_stats_aggregator import NodeStatsAggregator

JOB_ID = "job-a"


@pytest.fixture
def service() -> JobTrackerService:
    store = InMemoryJobStatsStore()
    return JobTrackerService(job_stats_store=store, node_stats_aggregator=NodeStatsAggregator(job_stats_store=store))


@pytest.fixture
def manager(service: JobTrackerService) -> DefaultJobRunManager:
    return DefaultJobRunManager(job_stats_service=service)


def _start(service: JobTrackerService, *, status: ExecutionStatus = ExecutionStatus.RUNNING) -> str:
    job_run_id = str(uuid.uuid4())
    service.start_tracking_job(job_id=JOB_ID, job_run_id=job_run_id, flow_id="flow-1", initial_status=status)
    return job_run_id


class TestCreateJobRun:
    def test_creates_a_pending_run_with_a_new_id(self, manager):
        run = manager.create_job_run(job_id=JOB_ID, job_config={})

        assert run[DocpipeConstants.JOB_ID] == JOB_ID
        assert run[DocpipeConstants.STATUS] == ExecutionStatus.PENDING.value
        assert uuid.UUID(run[DocpipeConstants.JOB_RUN_ID])
        assert "created_at" in run

    @pytest.mark.parametrize(
        ("job_id", "job_config", "message"),
        [("", {}, "job_id is required"), (JOB_ID, None, "job_config is required")],
        ids=["no-job-id", "no-config"],
    )
    def test_requires_job_id_and_config(self, manager, job_id, job_config, message):
        with pytest.raises(ValueError, match=message):
            manager.create_job_run(job_id=job_id, job_config=job_config)


class TestGetJobRun:
    def test_returns_the_stored_stats(self, manager, service):
        job_run_id = _start(service)

        run = manager.get_job_run(job_id=JOB_ID, job_run_id=job_run_id)

        assert (run["job_run_id"], run["status"]) == (job_run_id, ExecutionStatus.RUNNING)

    def test_unknown_run(self, manager):
        with pytest.raises(ValueError, match="Job run not found: nope"):
            manager.get_job_run(job_id=JOB_ID, job_run_id="nope")


class TestUpdateJobRunStatus:
    def test_updates_status_heartbeat_and_known_stats(self, manager, service):
        job_run_id = _start(service)

        manager.update_job_run_status(
            job_run_id=job_run_id,
            status=ExecutionStatus.COMPLETED,
            job_run_stats={"processed_docs": 7, "not_a_field": 1},
        )

        stats = service.get_job_run_stats(job_run_id=job_run_id)
        assert (stats.status, stats.processed_docs) == (ExecutionStatus.COMPLETED, 7)
        assert stats.heartbeat_timestamp > 0
        assert not hasattr(stats, "not_a_field")

    def test_terminal_status_is_not_overwritten_by_a_late_update(self, manager, service):
        job_run_id = _start(service, status=ExecutionStatus.FAILED)

        manager.update_job_run_status(job_run_id=job_run_id, status=ExecutionStatus.RUNNING)

        assert service.get_job_run_stats(job_run_id=job_run_id).status == ExecutionStatus.FAILED

    def test_terminal_status_can_follow_a_terminal_status(self, manager, service):
        job_run_id = _start(service, status=ExecutionStatus.FAILED)

        manager.update_job_run_status(job_run_id=job_run_id, status=ExecutionStatus.CANCELED)

        assert service.get_job_run_stats(job_run_id=job_run_id).status == ExecutionStatus.CANCELED

    def test_unknown_run_is_ignored(self, manager, service):
        manager.update_job_run_status(job_run_id="nope", status=ExecutionStatus.COMPLETED)

        assert service.get_job_run_stats(job_run_id="nope") is None


def test_cancel_and_delete_leave_the_stats_to_the_service_layer(manager, service):
    job_run_id = _start(service)

    manager.cancel_job_run(job_run_id=job_run_id)
    manager.delete_job_run(job_run_id=job_run_id)

    assert service.get_job_run_stats(job_run_id=job_run_id).status == ExecutionStatus.RUNNING
