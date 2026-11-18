"""Unit tests for FlowService cascade-delete of job runs.

Verifies that delete_flow() and bulk_delete_flows() trigger
_delete_job_runs_for_flow() when a JobStatsService is provided, and
that failures in the job-stats layer never block the flow delete.
"""

from unittest.mock import Mock

import pytest

from docpipe.core.assets.flows.application.services.flow_service import FlowService
from docpipe.exceptions.docpipe_exceptions import FlowNotFoundException

FLOW_ID = "12345678-1234-1234-1234-123456789abc"
FLOW_ID_2 = "abcdefab-abcd-abcd-abcd-abcdefabcdef"


@pytest.fixture
def mock_repository():
    repo = Mock()
    # delete() used by delete_flow returns True (flow deleted)
    repo.delete.return_value = True
    # bulk_delete used by bulk_delete_flows
    repo.bulk_delete.return_value = {
        "deleted": [FLOW_ID, FLOW_ID_2],
        "failed": [],
        "total_requested": 2,
        "total_deleted": 2,
        "total_failed": 0,
    }
    return repo


@pytest.fixture
def mock_job_stats_service():
    svc = Mock()
    svc.delete_job_runs_by_job_id.return_value = 1
    return svc


@pytest.fixture
def service_without_stats(mock_repository):
    return FlowService(repository=mock_repository)


@pytest.fixture
def service_with_stats(mock_repository, mock_job_stats_service):
    return FlowService(repository=mock_repository, job_stats_service=mock_job_stats_service)


class TestDeleteFlowCascade:
    """delete_flow() cascade behaviour."""

    def test_cascade_called_after_flow_deleted(self, service_with_stats, mock_repository, mock_job_stats_service):
        """delete_job_runs_by_job_id is called with the deleted flow's ID."""
        result = service_with_stats.delete_flow(FLOW_ID)
        assert result is True
        mock_job_stats_service.delete_job_runs_by_job_id.assert_called_once_with(job_id=FLOW_ID)

    def test_no_cascade_without_stats_service(self, service_without_stats, mock_repository):
        """When no job_stats_service is injected, delete succeeds without error."""
        result = service_without_stats.delete_flow(FLOW_ID)
        assert result is True  # flow was deleted; no stats call attempted

    def test_cascade_failure_does_not_raise(self, service_with_stats, mock_job_stats_service):
        """A RuntimeError from the stats service is swallowed so the flow delete succeeds."""
        mock_job_stats_service.delete_job_runs_by_job_id.side_effect = RuntimeError("stats store down")
        # Should not raise
        result = service_with_stats.delete_flow(FLOW_ID)
        assert result is True

    def test_flow_not_found_does_not_cascade(self, mock_repository, mock_job_stats_service):
        """When the repository raises FlowNotFoundException the cascade is never attempted."""
        mock_repository.delete.side_effect = FlowNotFoundException("not found", flow_id=FLOW_ID)
        svc = FlowService(repository=mock_repository, job_stats_service=mock_job_stats_service)
        with pytest.raises(FlowNotFoundException):
            svc.delete_flow(FLOW_ID)
        mock_job_stats_service.delete_job_runs_by_job_id.assert_not_called()


class TestBulkDeleteFlowsCascade:
    """bulk_delete_flows() cascade behaviour."""

    def test_cascade_called_for_each_deleted_flow(self, service_with_stats, mock_job_stats_service):
        """delete_job_runs_by_job_id is called once per successfully deleted flow."""
        service_with_stats.bulk_delete_flows([FLOW_ID, FLOW_ID_2])
        assert mock_job_stats_service.delete_job_runs_by_job_id.call_count == 2
        mock_job_stats_service.delete_job_runs_by_job_id.assert_any_call(job_id=FLOW_ID)
        mock_job_stats_service.delete_job_runs_by_job_id.assert_any_call(job_id=FLOW_ID_2)

    def test_cascade_only_for_deleted_not_failed(self, mock_repository, mock_job_stats_service):
        """When one flow fails to delete, cascade is called only for the one that succeeded."""
        mock_repository.bulk_delete.return_value = {
            "deleted": [FLOW_ID],
            "failed": [{"flow_id": FLOW_ID_2, "error": "not found"}],
            "total_requested": 2,
            "total_deleted": 1,
            "total_failed": 1,
        }
        svc = FlowService(repository=mock_repository, job_stats_service=mock_job_stats_service)
        svc.bulk_delete_flows([FLOW_ID, FLOW_ID_2])
        mock_job_stats_service.delete_job_runs_by_job_id.assert_called_once_with(job_id=FLOW_ID)

    def test_no_cascade_without_stats_service(self, service_without_stats):
        """Bulk delete works with no stats service configured."""
        result = service_without_stats.bulk_delete_flows([FLOW_ID])
        assert result["total_deleted"] == 2  # from mock_repository fixture
