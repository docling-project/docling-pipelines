"""
Unit tests for JobTrackerService.

Tests cover:
- Service lifecycle methods (start_tracking_job, end_job, get_job, get_job_run_stats)
- Final document counting logic (Phase 7)
- Status normalization
- Keyword-only argument compliance

Final document counting algorithm:
1. Failed documents (from any node's failed_docs list)
2. Completed documents (reached destination nodes, not failed)
3. Skipped documents (from ingest, neither completed nor failed)
"""

from unittest.mock import Mock

import pytest

from docpipe.core.constants.constants import ExecutionStatus
from docpipe.core.job_management.adapters.services.job_tracker_service import JobTrackerService
from docpipe.core.job_management.domain.models.job_stats import JobStats
from docpipe.core.job_management.domain.models.node_stats import NodeStats

# Test UUIDs (36 characters, hex format)
JOB_ID = "12345678-1234-1234-1234-123456789012"
JOB_RUN_ID = "87654321-4321-4321-4321-210987654321"
INGEST_NODE_ID = "a1111111-0000-0000-0000-000000000001"
TRANSFORM_NODE_ID = "b2222222-0000-0000-0000-000000000001"
DEST_NODE_ID_1 = "c3333333-0000-0000-0000-000000000001"
DEST_NODE_ID_2 = "c4444444-0000-0000-0000-000000000002"
NODE_ID_1 = "d5555555-0000-0000-0000-000000000001"
NODE_ID_2 = "d6666666-0000-0000-0000-000000000002"
BATCH_ID = "e1111111-0000-0000-0000-000000000001"


@pytest.fixture
def mock_store():
    """Create mock JobStatsStore."""
    return Mock()


@pytest.fixture
def mock_aggregator():
    """Create mock NodeStatsAggregator."""
    return Mock()


@pytest.fixture
def job_tracker_service(*, mock_store, mock_aggregator):
    """Create JobTrackerService with mocked dependencies."""
    return JobTrackerService(job_stats_store=mock_store, node_stats_aggregator=mock_aggregator)


@pytest.fixture
def sample_dag_linear():
    """Linear DAG: Ingest -> Transform -> Destination."""
    return [
        {"id": INGEST_NODE_ID, "input_edges": [], "output_edges": [TRANSFORM_NODE_ID]},
        {
            "id": TRANSFORM_NODE_ID,
            "input_edges": [INGEST_NODE_ID],
            "output_edges": [DEST_NODE_ID_1],
        },
        {"id": DEST_NODE_ID_1, "input_edges": [TRANSFORM_NODE_ID], "output_edges": []},
    ]


@pytest.fixture
def sample_dag_branching():
    """Branching DAG: Ingest -> Transform -> [Dest1, Dest2]."""
    return [
        {"id": INGEST_NODE_ID, "input_edges": [], "output_edges": [TRANSFORM_NODE_ID]},
        {
            "id": TRANSFORM_NODE_ID,
            "input_edges": [INGEST_NODE_ID],
            "output_edges": [DEST_NODE_ID_1, DEST_NODE_ID_2],
        },
        {"id": DEST_NODE_ID_1, "input_edges": [TRANSFORM_NODE_ID], "output_edges": []},
        {"id": DEST_NODE_ID_2, "input_edges": [TRANSFORM_NODE_ID], "output_edges": []},
    ]


class TestFinalDocumentCounting:
    """Test final document counting logic."""

    def test_all_documents_completed(self, *, job_tracker_service, sample_dag_linear):
        """Test when all documents complete successfully."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            total_docs=3,
            node_stats={
                INGEST_NODE_ID: NodeStats(
                    id=INGEST_NODE_ID,
                    name="Ingest",
                    total_docs=["doc1", "doc2", "doc3"],
                    docs_completed=["doc1", "doc2", "doc3"],
                    failed_docs=[],
                    skipped_docs=[],
                ),
                TRANSFORM_NODE_ID: NodeStats(
                    id=TRANSFORM_NODE_ID,
                    name="Transform",
                    total_docs=["doc1", "doc2", "doc3"],
                    docs_completed=["doc1", "doc2", "doc3"],
                    failed_docs=[],
                    skipped_docs=[],
                ),
                DEST_NODE_ID_1: NodeStats(
                    id=DEST_NODE_ID_1,
                    name="Destination",
                    total_docs=["doc1", "doc2", "doc3"],
                    docs_completed=["doc1", "doc2", "doc3"],
                    failed_docs=[],
                    skipped_docs=[],
                ),
            },
        )

        job_tracker_service.determine_and_update_final_documents_count(job_stats=job_stats, dag_nodes=sample_dag_linear)

        assert job_stats.completed_docs == 3
        assert job_stats.failed_docs == 0
        assert job_stats.skipped_docs == 0
        assert job_stats.processed_docs == 3

    def test_some_documents_failed(self, *, job_tracker_service, sample_dag_linear):
        """Test when some documents fail during processing."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            total_docs=3,
            node_stats={
                INGEST_NODE_ID: NodeStats(
                    id=INGEST_NODE_ID,
                    name="Ingest",
                    total_docs=["doc1", "doc2", "doc3"],
                    docs_completed=["doc1", "doc2", "doc3"],
                    failed_docs=[],
                    skipped_docs=[],
                ),
                TRANSFORM_NODE_ID: NodeStats(
                    id=TRANSFORM_NODE_ID,
                    name="Transform",
                    total_docs=["doc1", "doc2", "doc3"],
                    docs_completed=["doc1", "doc2"],
                    failed_docs=["doc3"],
                    skipped_docs=[],
                ),
                DEST_NODE_ID_1: NodeStats(
                    id=DEST_NODE_ID_1,
                    name="Destination",
                    total_docs=["doc1", "doc2"],
                    docs_completed=["doc1", "doc2"],
                    failed_docs=[],
                    skipped_docs=[],
                ),
            },
        )

        job_tracker_service.determine_and_update_final_documents_count(job_stats=job_stats, dag_nodes=sample_dag_linear)

        assert job_stats.completed_docs == 2
        assert job_stats.failed_docs == 1
        assert job_stats.skipped_docs == 0
        assert job_stats.processed_docs == 3

    def test_some_documents_skipped(self, *, job_tracker_service, sample_dag_linear):
        """Test when some documents are skipped (not processed)."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            total_docs=5,
            node_stats={
                INGEST_NODE_ID: NodeStats(
                    id=INGEST_NODE_ID,
                    name="Ingest",
                    total_docs=["doc1", "doc2", "doc3", "doc4", "doc5"],
                    docs_completed=["doc1", "doc2", "doc3"],
                    failed_docs=[],
                    skipped_docs=[],
                ),
                TRANSFORM_NODE_ID: NodeStats(
                    id=TRANSFORM_NODE_ID,
                    name="Transform",
                    total_docs=["doc1", "doc2", "doc3"],
                    docs_completed=["doc1", "doc2", "doc3"],
                    failed_docs=[],
                    skipped_docs=[],
                ),
                DEST_NODE_ID_1: NodeStats(
                    id=DEST_NODE_ID_1,
                    name="Destination",
                    total_docs=["doc1", "doc2", "doc3"],
                    docs_completed=["doc1", "doc2", "doc3"],
                    failed_docs=[],
                    skipped_docs=[],
                ),
            },
        )

        job_tracker_service.determine_and_update_final_documents_count(job_stats=job_stats, dag_nodes=sample_dag_linear)

        assert job_stats.completed_docs == 3
        assert job_stats.failed_docs == 0
        assert job_stats.skipped_docs == 2
        assert job_stats.processed_docs == 5

    def test_mixed_outcomes(self, *, job_tracker_service, sample_dag_linear):
        """Test with mixed outcomes: completed, failed, and skipped."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            total_docs=5,
            node_stats={
                INGEST_NODE_ID: NodeStats(
                    id=INGEST_NODE_ID,
                    name="Ingest",
                    total_docs=["doc1", "doc2", "doc3", "doc4", "doc5"],
                    docs_completed=["doc1", "doc2", "doc3", "doc4"],
                    failed_docs=[],
                    skipped_docs=[],
                ),
                TRANSFORM_NODE_ID: NodeStats(
                    id=TRANSFORM_NODE_ID,
                    name="Transform",
                    total_docs=["doc1", "doc2", "doc3", "doc4"],
                    docs_completed=["doc1", "doc2"],
                    failed_docs=["doc3"],
                    skipped_docs=[],
                ),
                DEST_NODE_ID_1: NodeStats(
                    id=DEST_NODE_ID_1,
                    name="Destination",
                    total_docs=["doc1", "doc2"],
                    docs_completed=["doc1", "doc2"],
                    failed_docs=[],
                    skipped_docs=[],
                ),
            },
        )

        job_tracker_service.determine_and_update_final_documents_count(job_stats=job_stats, dag_nodes=sample_dag_linear)

        assert job_stats.completed_docs == 2
        assert job_stats.failed_docs == 1
        assert job_stats.skipped_docs == 2
        assert job_stats.processed_docs == 5

    def test_multiple_destination_nodes(self, *, job_tracker_service, sample_dag_branching):
        """Test with multiple destination nodes (branching flow)."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            total_docs=4,
            node_stats={
                INGEST_NODE_ID: NodeStats(
                    id=INGEST_NODE_ID,
                    name="Ingest",
                    total_docs=["doc1", "doc2", "doc3", "doc4"],
                    docs_completed=["doc1", "doc2", "doc3", "doc4"],
                    failed_docs=[],
                    skipped_docs=[],
                ),
                TRANSFORM_NODE_ID: NodeStats(
                    id=TRANSFORM_NODE_ID,
                    name="Transform",
                    total_docs=["doc1", "doc2", "doc3", "doc4"],
                    docs_completed=["doc1", "doc2", "doc3", "doc4"],
                    failed_docs=[],
                    skipped_docs=[],
                ),
                DEST_NODE_ID_1: NodeStats(
                    id=DEST_NODE_ID_1,
                    name="Destination 1",
                    total_docs=["doc1", "doc2"],
                    docs_completed=["doc1", "doc2"],
                    failed_docs=[],
                    skipped_docs=[],
                ),
                DEST_NODE_ID_2: NodeStats(
                    id=DEST_NODE_ID_2,
                    name="Destination 2",
                    total_docs=["doc3", "doc4"],
                    docs_completed=["doc3", "doc4"],
                    failed_docs=[],
                    skipped_docs=[],
                ),
            },
        )

        job_tracker_service.determine_and_update_final_documents_count(
            job_stats=job_stats, dag_nodes=sample_dag_branching
        )

        assert job_stats.completed_docs == 4
        assert job_stats.failed_docs == 0
        assert job_stats.skipped_docs == 0
        assert job_stats.processed_docs == 4

    def test_failed_takes_precedence_over_completed(self, *, job_tracker_service, sample_dag_branching):
        """Test that failed status takes precedence even if doc reached a destination."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            total_docs=2,
            node_stats={
                INGEST_NODE_ID: NodeStats(
                    id=INGEST_NODE_ID,
                    name="Ingest",
                    total_docs=["doc1", "doc2"],
                    docs_completed=["doc1", "doc2"],
                    failed_docs=[],
                    skipped_docs=[],
                ),
                TRANSFORM_NODE_ID: NodeStats(
                    id=TRANSFORM_NODE_ID,
                    name="Transform",
                    total_docs=["doc1", "doc2"],
                    docs_completed=["doc1", "doc2"],
                    failed_docs=[],
                    skipped_docs=[],
                ),
                DEST_NODE_ID_1: NodeStats(
                    id=DEST_NODE_ID_1,
                    name="Destination 1",
                    total_docs=["doc1", "doc2"],
                    docs_completed=["doc1", "doc2"],
                    failed_docs=[],
                    skipped_docs=[],
                ),
                DEST_NODE_ID_2: NodeStats(
                    id=DEST_NODE_ID_2,
                    name="Destination 2",
                    total_docs=["doc1", "doc2"],
                    docs_completed=["doc2"],
                    failed_docs=["doc1"],
                    skipped_docs=[],
                ),
            },
        )

        job_tracker_service.determine_and_update_final_documents_count(
            job_stats=job_stats, dag_nodes=sample_dag_branching
        )

        assert job_stats.completed_docs == 1
        assert job_stats.failed_docs == 1
        assert job_stats.skipped_docs == 0
        assert job_stats.processed_docs == 2

    def test_empty_node_stats(self, *, job_tracker_service, sample_dag_linear):
        """Test with empty node stats."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, total_docs=0, node_stats={})

        job_tracker_service.determine_and_update_final_documents_count(job_stats=job_stats, dag_nodes=sample_dag_linear)

        assert job_stats.completed_docs == 0
        assert job_stats.failed_docs == 0
        assert job_stats.skipped_docs == 0
        assert job_stats.processed_docs == 0

    def test_no_destination_nodes(self, *, job_tracker_service):
        """Test when DAG has no destination nodes (all nodes have output edges)."""
        dag_nodes = [
            {"id": NODE_ID_1, "input_edges": [], "output_edges": [NODE_ID_2]},
            {"id": NODE_ID_2, "input_edges": [NODE_ID_1], "output_edges": [NODE_ID_1]},
        ]

        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            total_docs=2,
            node_stats={
                NODE_ID_1: NodeStats(
                    id=NODE_ID_1,
                    name="Node 1",
                    total_docs=["doc1", "doc2"],
                    docs_completed=["doc1", "doc2"],
                    failed_docs=[],
                    skipped_docs=[],
                )
            },
        )

        job_tracker_service.determine_and_update_final_documents_count(job_stats=job_stats, dag_nodes=dag_nodes)

        assert job_stats.completed_docs == 0
        assert job_stats.failed_docs == 0
        assert job_stats.skipped_docs == 2
        assert job_stats.processed_docs == 2


class TestHelperMethods:
    """Test individual helper methods."""

    def test_mark_failed_documents(self, *, job_tracker_service):
        """Test _mark_failed_documents helper."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            node_stats={
                NODE_ID_1: NodeStats(id=NODE_ID_1, name="Node 1", failed_docs=["doc1", "doc2"]),
                NODE_ID_2: NodeStats(id=NODE_ID_2, name="Node 2", failed_docs=["doc3"]),
            },
        )

        final_docs_status: dict[str, str] = {}
        job_tracker_service._mark_failed_documents(job_stats=job_stats, final_docs_status=final_docs_status)

        assert final_docs_status == {
            "doc1": "FAILED",
            "doc2": "FAILED",
            "doc3": "FAILED",
        }

    def test_identify_ingest_and_destination_nodes(self, *, job_tracker_service, sample_dag_linear):
        """Test _identify_ingest_and_destination_nodes helper."""
        ingest_id, dest_ids = job_tracker_service._identify_ingest_and_destination_nodes(dag_nodes=sample_dag_linear)

        assert ingest_id == INGEST_NODE_ID
        assert dest_ids == [DEST_NODE_ID_1]

    def test_mark_completed_documents(self, *, job_tracker_service):
        """Test _mark_completed_documents helper."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            node_stats={
                DEST_NODE_ID_1: NodeStats(
                    id=DEST_NODE_ID_1,
                    name="Destination",
                    docs_completed=["doc1", "doc2", "doc3"],
                )
            },
        )

        final_docs_status = {"doc3": "FAILED"}
        job_tracker_service._mark_completed_documents(
            job_stats=job_stats,
            destination_node_ids=[DEST_NODE_ID_1],
            final_docs_status=final_docs_status,
        )

        assert final_docs_status == {
            "doc1": "COMPLETED",
            "doc2": "COMPLETED",
            "doc3": "FAILED",
        }

    def test_mark_skipped_documents(self, *, job_tracker_service):
        """Test _mark_skipped_documents helper."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            node_stats={
                INGEST_NODE_ID: NodeStats(
                    id=INGEST_NODE_ID,
                    name="Ingest",
                    total_docs=["doc1", "doc2", "doc3", "doc4"],
                )
            },
        )

        final_docs_status = {"doc1": "COMPLETED", "doc2": "FAILED"}

        job_tracker_service._mark_skipped_documents(
            job_stats=job_stats,
            ingest_node_id=INGEST_NODE_ID,
            final_docs_status=final_docs_status,
        )

        assert final_docs_status == {
            "doc1": "COMPLETED",
            "doc2": "FAILED",
            "doc3": "SKIPPED",
            "doc4": "SKIPPED",
        }


class TestStartTrackingJob:
    """Test start_tracking_job method."""

    def test_start_tracking_job_basic(self, *, job_tracker_service, mock_store):
        """Start tracking creates initial job stats with correct flow_id and flow_name."""
        job_tracker_service.start_tracking_job(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            flow_id="test-flow-uuid",
            flow_name="test_flow",
            user_id="test_user",
        )

        assert mock_store.store_job_stats.called
        call_args = mock_store.store_job_stats.call_args
        job_stats = call_args[0][0]

        assert job_stats.job_id == JOB_ID
        assert job_stats.job_run_id == JOB_RUN_ID
        assert job_stats.flow_id == "test-flow-uuid"
        assert job_stats.flow_name == "test_flow"
        assert job_stats.user_id == "test_user"
        assert job_stats.status == ExecutionStatus.RUNNING
        assert job_stats.start_time is not None

    def test_start_tracking_job_flow_name_none(self, *, job_tracker_service, mock_store):
        """start_tracking_job stores flow_name=None without error."""
        job_tracker_service.start_tracking_job(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            flow_id="test-flow-uuid",
            flow_name=None,
        )

        call_args = mock_store.store_job_stats.call_args
        job_stats = call_args[0][0]

        assert job_stats.flow_id == "test-flow-uuid"
        assert job_stats.flow_name is None

    def test_start_tracking_job_custom_initial_status(self, *, job_tracker_service, mock_store):
        """start_tracking_job stores the given initial_status when provided."""
        job_tracker_service.start_tracking_job(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            flow_id="test-flow-uuid",
            flow_name="test_flow",
            initial_status=ExecutionStatus.QUEUED,
        )

        call_args = mock_store.store_job_stats.call_args
        job_stats = call_args[0][0]

        assert job_stats.status == ExecutionStatus.QUEUED

    def test_start_tracking_job_default_user(self, *, job_tracker_service, mock_store):
        """Start tracking with no user_id uses default."""
        job_tracker_service.start_tracking_job(
            job_id=JOB_ID, job_run_id=JOB_RUN_ID, flow_id="test-flow-uuid", flow_name="test_flow"
        )

        call_args = mock_store.store_job_stats.call_args
        job_stats = call_args[0][0]

        assert job_stats.user_id is None


class TestEndJob:
    """Test end_job method."""

    def test_end_job_completed(self, *, job_tracker_service, mock_store):
        """End job with COMPLETED status."""
        # Setup mock
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.RUNNING.value,
            start_time=1000,
        )
        mock_store.get_job_stats.return_value = job_stats

        job_tracker_service.end_job(job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED)

        # Verify store_job_stats was called with updated stats
        assert mock_store.store_job_stats.called
        call_args = mock_store.store_job_stats.call_args
        updated_stats = call_args[0][0]

        assert updated_stats.status == ExecutionStatus.COMPLETED
        assert updated_stats.end_time is not None
        assert updated_stats.duration is not None

    def test_end_job_failed(self, *, job_tracker_service, mock_store):
        """End job with FAILED status."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.RUNNING.value,
            start_time=1000,
        )
        mock_store.get_job_stats.return_value = job_stats

        job_tracker_service.end_job(
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.FAILED,
            job_run_stats={"message": "Test error"},
        )

        call_args = mock_store.store_job_stats.call_args
        updated_stats = call_args[0][0]

        assert updated_stats.status == ExecutionStatus.FAILED
        assert updated_stats.message == "Test error"

    def test_end_job_canceled(self, *, job_tracker_service, mock_store):
        """End job with CANCELED status."""
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.RUNNING.value,
            start_time=1000,
        )
        mock_store.get_job_stats.return_value = job_stats

        job_tracker_service.end_job(job_run_id=JOB_RUN_ID, status=ExecutionStatus.CANCELED)

        call_args = mock_store.store_job_stats.call_args
        updated_stats = call_args[0][0]

        assert updated_stats.status == ExecutionStatus.CANCELED

    def test_end_job_not_found(self, *, job_tracker_service, mock_store):
        """End job raises JobRunNotFoundException if job not found."""
        mock_store.get_job_stats.return_value = None

        from docpipe.exceptions.docpipe_exceptions import JobRunNotFoundException

        with pytest.raises(JobRunNotFoundException, match="Job run not found"):
            job_tracker_service.end_job(job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED)


class TestGetJob:
    """Test get_job method with aggregation options."""

    def test_get_job_with_node_stats(self, *, job_tracker_service, mock_store, mock_aggregator):
        """Get job with aggregated node stats."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.RUNNING)
        mock_store.get_job_stats.return_value = job_stats

        aggregated_node_stats = {
            INGEST_NODE_ID: NodeStats(
                id=INGEST_NODE_ID,
                name="TestNode",
                node_status=ExecutionStatus.COMPLETED,
            )
        }
        mock_aggregator.get_aggregated_node_stats.return_value = aggregated_node_stats

        result = job_tracker_service.get_job(job_run_id=JOB_RUN_ID, include_node_stats=True, include_batch_stats=False)

        assert result is not None
        assert result.node_stats == aggregated_node_stats
        assert result.batch_node_stats == {}
        assert mock_aggregator.get_aggregated_node_stats.called

    def test_get_job_with_batch_stats(self, *, job_tracker_service, mock_store, mock_aggregator):
        """Get job with batch-level node stats."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.RUNNING)
        mock_store.get_job_stats.return_value = job_stats

        batch_node_stats = {
            INGEST_NODE_ID: {
                BATCH_ID: NodeStats(
                    id=INGEST_NODE_ID,
                    name="TestNode",
                    batch_id=BATCH_ID,
                    batch_num=0,
                )
            }
        }
        mock_aggregator.get_batch_node_stats.return_value = batch_node_stats

        result = job_tracker_service.get_job(job_run_id=JOB_RUN_ID, include_node_stats=False, include_batch_stats=True)

        assert result is not None
        assert result.node_stats == {}
        assert result.batch_node_stats == batch_node_stats
        assert mock_aggregator.get_batch_node_stats.called

    def test_get_job_without_aggregation(self, *, job_tracker_service, mock_store, mock_aggregator):
        """Get job without any aggregation."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.RUNNING)
        mock_store.get_job_stats.return_value = job_stats

        result = job_tracker_service.get_job(job_run_id=JOB_RUN_ID, include_node_stats=False, include_batch_stats=False)

        assert result is not None
        assert result.node_stats == {}
        assert result.batch_node_stats == {}
        assert not mock_aggregator.get_aggregated_node_stats.called
        assert not mock_aggregator.get_batch_node_stats.called

    def test_get_job_not_found(self, *, job_tracker_service, mock_store):
        """Get job returns None if not found."""
        mock_store.get_job_stats.return_value = None

        result = job_tracker_service.get_job(job_run_id=JOB_RUN_ID)

        assert result is None


class TestGetJobRunStats:
    """Test get_job_run_stats method (lightweight retrieval)."""

    def test_get_job_run_stats_basic(self, *, job_tracker_service, mock_store):
        """Get job run stats without aggregation."""
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.RUNNING)
        mock_store.get_job_stats.return_value = job_stats

        result = job_tracker_service.get_job_run_stats(job_run_id=JOB_RUN_ID)

        assert result is not None
        assert result.job_run_id == JOB_RUN_ID
        assert mock_store.get_job_stats.called

    def test_get_job_run_stats_not_found(self, *, job_tracker_service, mock_store):
        """Get job run stats returns None if not found."""
        mock_store.get_job_stats.return_value = None

        result = job_tracker_service.get_job_run_stats(job_run_id=JOB_RUN_ID)

        assert result is None


class TestNormalizeExecutionStatus:
    """Test normalize_execution_status static method."""

    def test_normalize_enum_value(self, *, job_tracker_service):
        """Normalize ExecutionStatus enum."""
        result = job_tracker_service.normalize_execution_status(ExecutionStatus.COMPLETED)
        assert result == ExecutionStatus.COMPLETED

    def test_normalize_string_exact(self, *, job_tracker_service):
        """Normalize exact string match."""
        result = job_tracker_service.normalize_execution_status("Completed")
        assert result == ExecutionStatus.COMPLETED

    def test_normalize_string_uppercase(self, *, job_tracker_service):
        """Normalize uppercase string via enum key lookup."""
        result = job_tracker_service.normalize_execution_status("COMPLETED")
        assert result == ExecutionStatus.COMPLETED

    def test_normalize_string_case_insensitive(self, *, job_tracker_service):
        """Normalize case-insensitive string."""
        result = job_tracker_service.normalize_execution_status("completed")
        assert result == ExecutionStatus.COMPLETED

    def test_normalize_string_with_spaces(self, *, job_tracker_service):
        """Normalize string with spaces."""
        result = job_tracker_service.normalize_execution_status("  Completed  ")
        assert result == ExecutionStatus.COMPLETED

    def test_normalize_invalid_status(self, *, job_tracker_service):
        """Normalize invalid status raises ValueError."""
        with pytest.raises(ValueError, match="Invalid status"):
            job_tracker_service.normalize_execution_status("INVALID_STATUS")

    def test_normalize_empty_status(self, *, job_tracker_service):
        """Normalize empty status raises ValueError."""
        with pytest.raises(ValueError, match="Invalid status: empty value"):
            job_tracker_service.normalize_execution_status("")


class TestStartNodeExecution:
    """Test start_node_execution method."""

    def test_start_node_execution_non_batch(self, *, job_tracker_service, mock_store):
        """Start node execution without batch context."""
        job_tracker_service.start_node_execution(
            job_run_id=JOB_RUN_ID,
            node_id=INGEST_NODE_ID,
            node_name="Ingest",
            total_docs=["doc1", "doc2", "doc3"],
        )

        assert mock_store.store_node_stats.called
        call_args = mock_store.store_node_stats.call_args
        node_stats = call_args[1]["node_stats"]

        assert node_stats.id == INGEST_NODE_ID
        assert node_stats.name == "Ingest"
        assert node_stats.node_status == ExecutionStatus.RUNNING.value
        assert node_stats.total_docs == ["doc1", "doc2", "doc3"]
        assert node_stats.batch_id is None
        assert node_stats.batch_num is None

    def test_start_node_execution_with_batch(self, *, job_tracker_service, mock_store):
        """Start node execution with batch context."""
        job_tracker_service.start_node_execution(
            job_run_id=JOB_RUN_ID,
            node_id=TRANSFORM_NODE_ID,
            node_name="Transform",
            total_docs=["doc1", "doc2"],
            batch_id=BATCH_ID,
            batch_num=0,
        )

        call_args = mock_store.store_node_stats.call_args
        node_stats = call_args[1]["node_stats"]

        assert node_stats.batch_id == BATCH_ID
        assert node_stats.batch_num == 0


class TestCompleteNodeExecution:
    """Test complete_node_execution method."""

    def test_complete_node_execution_success(self, *, job_tracker_service, mock_store):
        """Complete node execution successfully."""
        # Setup existing node with realistic timestamp
        import time

        current_time = int(time.time())
        existing_node = NodeStats(
            id=INGEST_NODE_ID,
            name="Ingest",
            start_time=current_time - 10,  # Started 10 seconds ago
            total_docs=["doc1", "doc2", "doc3"],
            node_status=ExecutionStatus.RUNNING.value,
        )
        mock_store.get_node_stats_by_batch_and_node.return_value = existing_node

        job_tracker_service.complete_node_execution(
            job_run_id=JOB_RUN_ID,
            node_id=INGEST_NODE_ID,
            node_name="Ingest",
            docs_completed=["doc1", "doc2", "doc3"],
            failed_docs=[],
            skipped_docs=[],
            col_names=["col1", "col2"],
            node_status=ExecutionStatus.COMPLETED.value,
        )

        assert mock_store.store_node_stats.called
        call_args = mock_store.store_node_stats.call_args
        node_stats = call_args[1]["node_stats"]

        assert node_stats.node_status == ExecutionStatus.COMPLETED.value
        assert node_stats.docs_completed == ["doc1", "doc2", "doc3"]
        assert node_stats.docs_completed_count == 3
        assert node_stats.end_time is not None
        assert node_stats.time_taken is not None

    def test_complete_node_execution_with_failures(self, *, job_tracker_service, mock_store):
        """Complete node execution with some failures."""
        import time

        current_time = int(time.time())
        existing_node = NodeStats(
            id=TRANSFORM_NODE_ID,
            name="Transform",
            start_time=current_time - 10,
            total_docs=["doc1", "doc2", "doc3"],
            node_status=ExecutionStatus.RUNNING.value,
        )
        mock_store.get_node_stats_by_batch_and_node.return_value = existing_node

        job_tracker_service.complete_node_execution(
            job_run_id=JOB_RUN_ID,
            node_id=TRANSFORM_NODE_ID,
            node_name="Transform",
            docs_completed=["doc1", "doc2"],
            failed_docs=["doc3"],
            skipped_docs=[],
            col_names=["col1"],
            node_status=ExecutionStatus.COMPLETED.value,
        )

        call_args = mock_store.store_node_stats.call_args
        node_stats = call_args[1]["node_stats"]

        assert node_stats.docs_completed_count == 2
        assert node_stats.failed_docs == ["doc3"]
        assert "1 failed" in node_stats.error

    def test_complete_node_execution_with_batch(self, *, job_tracker_service, mock_store):
        """Complete node execution with batch context."""
        import time

        current_time = int(time.time())
        existing_node = NodeStats(
            id=TRANSFORM_NODE_ID,
            name="Transform",
            start_time=current_time - 10,
            total_docs=["doc1", "doc2"],
            node_status=ExecutionStatus.RUNNING.value,
            batch_id=BATCH_ID,
            batch_num=0,
        )
        mock_store.get_node_stats_by_batch_and_node.return_value = existing_node

        job_tracker_service.complete_node_execution(
            job_run_id=JOB_RUN_ID,
            node_id=TRANSFORM_NODE_ID,
            node_name="Transform",
            docs_completed=["doc1", "doc2"],
            failed_docs=[],
            skipped_docs=[],
            col_names=["col1"],
            node_status=ExecutionStatus.COMPLETED.value,
            batch_id=BATCH_ID,
            batch_num=0,
        )

        call_args = mock_store.store_node_stats.call_args
        node_stats = call_args[1]["node_stats"]

        assert node_stats.batch_id == BATCH_ID
        assert node_stats.batch_num == 0

    def test_complete_node_execution_not_started(self, *, job_tracker_service, mock_store):
        """Complete node execution raises error if not started."""
        mock_store.get_node_stats_by_batch_and_node.return_value = None

        with pytest.raises(ValueError, match="Node execution was not started"):
            job_tracker_service.complete_node_execution(
                job_run_id=JOB_RUN_ID,
                node_id=INGEST_NODE_ID,
                node_name="Ingest",
                docs_completed=["doc1"],
                failed_docs=[],
                skipped_docs=[],
                col_names=[],
                node_status=ExecutionStatus.COMPLETED.value,
            )


class TestFailNodeExecution:
    """Test fail_node_execution method."""

    def test_fail_node_execution_with_exception(self, *, job_tracker_service, mock_store):
        """Fail node execution with exception."""
        import time

        current_time = int(time.time())
        existing_node = NodeStats(
            id=TRANSFORM_NODE_ID,
            name="Transform",
            start_time=current_time - 10,
            total_docs=["doc1", "doc2"],
            node_status=ExecutionStatus.RUNNING.value,
        )
        mock_store.get_node_stats_by_batch_and_node.return_value = existing_node

        test_exception = ValueError("Test error message")
        job_tracker_service.fail_node_execution(
            job_run_id=JOB_RUN_ID,
            node_id=TRANSFORM_NODE_ID,
            node_name="Transform",
            exception=test_exception,
        )

        assert mock_store.store_node_stats.called
        call_args = mock_store.store_node_stats.call_args
        node_stats = call_args[1]["node_stats"]

        assert node_stats.node_status == ExecutionStatus.FAILED.value
        assert "Test error message" in node_stats.error
        assert node_stats.docs_completed_count == 0

    def test_fail_node_execution_with_error_string(self, *, job_tracker_service, mock_store):
        """Fail node execution with error string."""
        import time

        current_time = int(time.time())
        existing_node = NodeStats(
            id=TRANSFORM_NODE_ID,
            name="Transform",
            start_time=current_time - 10,
            total_docs=["doc1"],
            node_status=ExecutionStatus.RUNNING.value,
        )
        mock_store.get_node_stats_by_batch_and_node.return_value = existing_node

        job_tracker_service.fail_node_execution(
            job_run_id=JOB_RUN_ID,
            node_id=TRANSFORM_NODE_ID,
            node_name="Transform",
            error="Custom error message",
        )

        call_args = mock_store.store_node_stats.call_args
        node_stats = call_args[1]["node_stats"]

        assert node_stats.error == "Custom error message"

    def test_fail_node_execution_with_batch(self, *, job_tracker_service, mock_store):
        """Fail node execution with batch context."""
        import time

        current_time = int(time.time())
        existing_node = NodeStats(
            id=TRANSFORM_NODE_ID,
            name="Transform",
            start_time=current_time - 10,
            total_docs=["doc1"],
            node_status=ExecutionStatus.RUNNING.value,
            batch_id=BATCH_ID,
            batch_num=0,
        )
        mock_store.get_node_stats_by_batch_and_node.return_value = existing_node

        job_tracker_service.fail_node_execution(
            job_run_id=JOB_RUN_ID,
            node_id=TRANSFORM_NODE_ID,
            node_name="Transform",
            error="Batch failed",
            batch_id=BATCH_ID,
            batch_num=0,
        )

        call_args = mock_store.store_node_stats.call_args
        node_stats = call_args[1]["node_stats"]

        assert node_stats.batch_id == BATCH_ID
        assert node_stats.batch_num == 0

    def test_fail_node_execution_no_error(self, *, job_tracker_service, mock_store):
        """Fail node execution raises error if no exception or error provided."""
        with pytest.raises(ValueError, match="Either exception or error must be provided"):
            job_tracker_service.fail_node_execution(
                job_run_id=JOB_RUN_ID, node_id=TRANSFORM_NODE_ID, node_name="Transform"
            )


class TestCancelNodeExecution:
    """Test cancel_node_execution method."""

    def test_cancel_node_execution_basic(self, *, job_tracker_service, mock_store):
        """Cancel node execution."""
        import time

        current_time = int(time.time())
        existing_node = NodeStats(
            id=TRANSFORM_NODE_ID,
            name="Transform",
            start_time=current_time - 10,
            total_docs=["doc1", "doc2"],
            node_status=ExecutionStatus.RUNNING.value,
        )
        mock_store.get_node_stats_by_batch_and_node.return_value = existing_node

        job_tracker_service.cancel_node_execution(
            job_run_id=JOB_RUN_ID, node_id=TRANSFORM_NODE_ID, node_name="Transform"
        )

        assert mock_store.store_node_stats.called
        call_args = mock_store.store_node_stats.call_args
        node_stats = call_args[1]["node_stats"]

        assert node_stats.node_status == ExecutionStatus.CANCELED.value
        assert node_stats.docs_completed_count == 0

    def test_cancel_node_execution_with_batch(self, *, job_tracker_service, mock_store):
        """Cancel node execution with batch context."""
        import time

        current_time = int(time.time())
        existing_node = NodeStats(
            id=TRANSFORM_NODE_ID,
            name="Transform",
            start_time=current_time - 10,
            total_docs=["doc1"],
            node_status=ExecutionStatus.RUNNING.value,
            batch_id=BATCH_ID,
            batch_num=0,
        )
        mock_store.get_node_stats_by_batch_and_node.return_value = existing_node

        job_tracker_service.cancel_node_execution(
            job_run_id=JOB_RUN_ID,
            node_id=TRANSFORM_NODE_ID,
            node_name="Transform",
            batch_id=BATCH_ID,
            batch_num=0,
        )

        call_args = mock_store.store_node_stats.call_args
        node_stats = call_args[1]["node_stats"]

        assert node_stats.batch_id == BATCH_ID
        assert node_stats.batch_num == 0


class TestAbortNodeExecution:
    """Test abort_node_execution method."""

    def test_abort_node_execution_basic(self, *, job_tracker_service, mock_store):
        """Abort node execution with reason."""
        import time

        current_time = int(time.time())
        existing_node = NodeStats(
            id=TRANSFORM_NODE_ID,
            name="Transform",
            start_time=current_time - 10,
            total_docs=["doc1", "doc2"],
            node_status=ExecutionStatus.RUNNING.value,
        )
        mock_store.get_node_stats_by_batch_and_node.return_value = existing_node

        job_tracker_service.abort_node_execution(
            job_run_id=JOB_RUN_ID,
            node_id=TRANSFORM_NODE_ID,
            node_name="Transform",
            reason="Upstream failure",
        )

        assert mock_store.store_node_stats.called
        call_args = mock_store.store_node_stats.call_args
        node_stats = call_args[1]["node_stats"]

        assert node_stats.node_status == ExecutionStatus.ABORTED.value
        assert node_stats.error == "Upstream failure"
        assert node_stats.docs_completed_count == 0


class TestSkipNodeExecution:
    """Test skip_node_execution method."""

    def test_skip_node_execution_basic(self, *, job_tracker_service, mock_store):
        """Skip node execution with reason."""
        import time

        current_time = int(time.time())
        existing_node = NodeStats(
            id=TRANSFORM_NODE_ID,
            name="Transform",
            start_time=current_time - 10,
            total_docs=["doc1"],
            node_status=ExecutionStatus.RUNNING.value,
        )
        mock_store.get_node_stats_by_batch_and_node.return_value = existing_node

        job_tracker_service.skip_node_execution(
            job_run_id=JOB_RUN_ID,
            node_id=TRANSFORM_NODE_ID,
            node_name="Transform",
            reason="No documents to process",
            col_names=["col1"],
        )

        assert mock_store.store_node_stats.called
        call_args = mock_store.store_node_stats.call_args
        node_stats = call_args[1]["node_stats"]

        assert node_stats.node_status == ExecutionStatus.SKIPPED.value
        assert node_stats.error == "No documents to process"
        assert node_stats.col_names == ["col1"]

    def test_fail_node_execution_metadata_structure(self, *, job_tracker_service, mock_store):
        """Verify fail_node_execution creates proper nested metadata structure."""
        import time

        from docpipe.core.constants.constants import Metrics

        current_time = int(time.time())
        existing_node = NodeStats(
            id=TRANSFORM_NODE_ID,
            name="Transform",
            start_time=current_time - 10,
            total_docs=["doc1"],
            node_status=ExecutionStatus.RUNNING.value,
        )
        mock_store.get_node_stats_by_batch_and_node.return_value = existing_node

        job_tracker_service.fail_node_execution(
            job_run_id=JOB_RUN_ID,
            node_id=TRANSFORM_NODE_ID,
            node_name="Transform",
            error="Test failure",
        )

        call_args = mock_store.store_node_stats.call_args
        node_stats = call_args[1]["node_stats"]

        # Verify proper nested structure
        assert node_stats.node_metadata is not None
        assert "id" in node_stats.node_metadata
        assert "operator" in node_stats.node_metadata
        assert "node_metadata" in node_stats.node_metadata
        assert node_stats.node_metadata["id"] == TRANSFORM_NODE_ID
        assert node_stats.node_metadata["operator"] == "Transform"
        assert Metrics.External.NODE_STATUS in node_stats.node_metadata["node_metadata"]
        assert node_stats.node_metadata["node_metadata"][Metrics.External.NODE_STATUS] == ExecutionStatus.FAILED.value

    def test_skip_node_execution_metadata_structure(self, *, job_tracker_service, mock_store):
        """Verify skip_node_execution creates proper nested metadata structure."""
        import time

        from docpipe.core.constants.constants import Metrics

        current_time = int(time.time())
        existing_node = NodeStats(
            id=TRANSFORM_NODE_ID,
            name="Transform",
            start_time=current_time - 10,
            total_docs=["doc1", "doc2"],
            node_status=ExecutionStatus.RUNNING.value,
        )
        mock_store.get_node_stats_by_batch_and_node.return_value = existing_node

        job_tracker_service.skip_node_execution(
            job_run_id=JOB_RUN_ID,
            node_id=TRANSFORM_NODE_ID,
            node_name="Transform",
            reason="Skipped for testing",
            col_names=["col1"],
        )

        call_args = mock_store.store_node_stats.call_args
        node_stats = call_args[1]["node_stats"]

        # Verify proper nested structure
        assert node_stats.node_metadata is not None
        assert "id" in node_stats.node_metadata
        assert "operator" in node_stats.node_metadata
        assert "node_metadata" in node_stats.node_metadata
        assert node_stats.node_metadata["id"] == TRANSFORM_NODE_ID
        assert node_stats.node_metadata["operator"] == "Transform"
        assert Metrics.External.NODE_STATUS in node_stats.node_metadata["node_metadata"]
        assert node_stats.node_metadata["node_metadata"][Metrics.External.NODE_STATUS] == ExecutionStatus.SKIPPED.value
        assert Metrics.External.TOTAL_DOCS in node_stats.node_metadata["node_metadata"]
        assert node_stats.node_metadata["node_metadata"][Metrics.External.TOTAL_DOCS] == 2


class TestUpdateNodeStats:
    """Test update_node_stats merge behavior."""

    def test_update_node_stats_no_existing_state(self, *, job_tracker_service, mock_store):
        """Test update with no existing state creates new record."""
        mock_store.get_node_stats_by_batch_and_node.return_value = None

        job_tracker_service.update_node_stats(
            job_run_id=JOB_RUN_ID,
            node_id=NODE_ID_1,
            node_stats={
                "name": "Test Node",
                "node_status": "COMPLETED",
                "docs_completed": ["doc1", "doc2"],
                "docs_completed_count": 2,
            },
        )

        mock_store.store_node_stats.assert_called_once()
        stored_stats = mock_store.store_node_stats.call_args[1]["node_stats"]
        assert stored_stats.id == NODE_ID_1
        assert stored_stats.name == "Test Node"
        assert stored_stats.node_status == "COMPLETED"
        assert stored_stats.docs_completed == ["doc1", "doc2"]
        assert stored_stats.docs_completed_count == 2

    def test_update_node_stats_merges_with_existing(self, *, job_tracker_service, mock_store):
        """Test update merges with existing state."""
        existing_stats = NodeStats(
            id=NODE_ID_1,
            name="Test Node",
            node_status=ExecutionStatus.RUNNING,
            start_time=1000,
            total_docs=["doc1", "doc2", "doc3"],
            docs_completed=[],
            docs_completed_count=0,
        )
        mock_store.get_node_stats_by_batch_and_node.return_value = existing_stats

        job_tracker_service.update_node_stats(
            job_run_id=JOB_RUN_ID,
            node_id=NODE_ID_1,
            node_stats={
                "node_status": "COMPLETED",
                "end_time": 2000,
                "time_taken": 1000,
                "docs_completed": ["doc1", "doc2"],
                "docs_completed_count": 2,
            },
        )

        mock_store.store_node_stats.assert_called_once()
        stored_stats = mock_store.store_node_stats.call_args[1]["node_stats"]

        # Verify merge: existing fields preserved
        assert stored_stats.id == NODE_ID_1
        assert stored_stats.name == "Test Node"
        assert stored_stats.start_time == 1000
        assert stored_stats.total_docs == ["doc1", "doc2", "doc3"]

        # Verify merge: new fields applied
        assert stored_stats.node_status == "COMPLETED"
        assert stored_stats.end_time == 2000
        assert stored_stats.time_taken == 1000
        assert stored_stats.docs_completed == ["doc1", "doc2"]
        assert stored_stats.docs_completed_count == 2

    def test_update_node_stats_preserves_metadata(self, *, job_tracker_service, mock_store):
        """Test update preserves existing metadata when not provided."""
        existing_stats = NodeStats(
            id=NODE_ID_1,
            name="Test Node",
            node_status=ExecutionStatus.RUNNING,
            node_metadata={
                "id": NODE_ID_1,
                "operator": "TestOperator",
                "node_metadata": {"custom_field": "value1", "counter": 42},
            },
        )
        mock_store.get_node_stats_by_batch_and_node.return_value = existing_stats

        job_tracker_service.update_node_stats(
            job_run_id=JOB_RUN_ID,
            node_id=NODE_ID_1,
            node_stats={"node_status": "COMPLETED", "docs_completed_count": 5},
        )

        stored_stats = mock_store.store_node_stats.call_args[1]["node_stats"]

        # Verify metadata preserved
        assert stored_stats.node_metadata is not None
        assert stored_stats.node_metadata["id"] == NODE_ID_1
        assert stored_stats.node_metadata["operator"] == "TestOperator"
        assert stored_stats.node_metadata["node_metadata"]["custom_field"] == "value1"
        assert stored_stats.node_metadata["node_metadata"]["counter"] == 42

        # Verify new fields applied
        assert stored_stats.node_status == "COMPLETED"
        assert stored_stats.docs_completed_count == 5

    def test_update_node_stats_partial_update_preserves_counters(self, *, job_tracker_service, mock_store):
        """Test partial update doesn't discard existing counters."""
        existing_stats = NodeStats(
            id=NODE_ID_1,
            name="Test Node",
            node_status=ExecutionStatus.RUNNING,
            start_time=1000,
            total_docs=["doc1", "doc2", "doc3"],
            docs_completed=["doc1"],
            docs_completed_count=1,
            failed_docs=["doc2"],
            skipped_docs=[],
        )
        mock_store.get_node_stats_by_batch_and_node.return_value = existing_stats

        # Partial update with only status change
        job_tracker_service.update_node_stats(
            job_run_id=JOB_RUN_ID,
            node_id=NODE_ID_1,
            node_stats={"node_status": "COMPLETED"},
        )

        stored_stats = mock_store.store_node_stats.call_args[1]["node_stats"]

        # Verify all existing fields preserved
        assert stored_stats.start_time == 1000
        assert stored_stats.total_docs == ["doc1", "doc2", "doc3"]
        assert stored_stats.docs_completed == ["doc1"]
        assert stored_stats.docs_completed_count == 1
        assert stored_stats.failed_docs == ["doc2"]
        assert stored_stats.skipped_docs == []

        # Verify only status updated
        assert stored_stats.node_status == "COMPLETED"

    def test_update_node_stats_with_batch_id(self, *, job_tracker_service, mock_store):
        """Test update with batch_id parameter."""
        existing_stats = NodeStats(
            id=NODE_ID_1,
            name="Test Node",
            batch_id=BATCH_ID,
            batch_num=1,
            node_status=ExecutionStatus.RUNNING,
        )
        mock_store.get_node_stats_by_batch_and_node.return_value = existing_stats

        job_tracker_service.update_node_stats(
            job_run_id=JOB_RUN_ID,
            node_id=NODE_ID_1,
            node_stats={"node_status": "COMPLETED"},
            batch_id=BATCH_ID,
        )

        # Verify get called with batch_id
        mock_store.get_node_stats_by_batch_and_node.assert_called_once_with(
            job_run_id=JOB_RUN_ID, node_id=NODE_ID_1, batch_id=BATCH_ID
        )

        stored_stats = mock_store.store_node_stats.call_args[1]["node_stats"]
        assert stored_stats.batch_id == BATCH_ID
        assert stored_stats.batch_num == 1

    def test_update_node_stats_with_node_stats_dto(self, *, job_tracker_service, mock_store):
        """Test update accepts NodeStats input."""
        existing_stats = NodeStats(
            id=NODE_ID_1,
            name="Test Node",
            node_status=ExecutionStatus.RUNNING,
            start_time=1000,
        )
        mock_store.get_node_stats_by_batch_and_node.return_value = existing_stats

        update_dto = NodeStats(
            id=NODE_ID_1,
            name="Test Node",
            node_status=ExecutionStatus.COMPLETED,
            end_time=2000,
        )

        job_tracker_service.update_node_stats(job_run_id=JOB_RUN_ID, node_id=NODE_ID_1, node_stats=update_dto)

        stored_stats = mock_store.store_node_stats.call_args[1]["node_stats"]
        assert stored_stats.start_time == 1000  # Preserved from existing
        assert stored_stats.end_time == 2000  # From update
        assert stored_stats.node_status == ExecutionStatus.COMPLETED

    def test_update_node_stats_invalid_type(self, *, job_tracker_service, mock_store):
        """Test update raises error for invalid input type."""
        mock_store.get_node_stats_by_batch_and_node.return_value = None

        with pytest.raises(ValueError, match="Invalid node_stats type"):
            job_tracker_service.update_node_stats(job_run_id=JOB_RUN_ID, node_id=NODE_ID_1, node_stats="invalid_string")


class TestRequestCancelJob:
    """Test request_cancel_job method."""

    @pytest.mark.parametrize(
        "terminal_status",
        [
            ExecutionStatus.COMPLETED,
            ExecutionStatus.COMPLETED_WITH_ERRORS,
            ExecutionStatus.COMPLETED_WITH_WARNINGS,
            ExecutionStatus.CANCELED,
            ExecutionStatus.FAILED,
            ExecutionStatus.ABORTED,
        ],
    )
    def test_cancel_job_in_terminal_state_raises_exception(self, *, job_tracker_service, mock_store, terminal_status):
        """Test that canceling a job in terminal state raises JobRunInvalidStateException."""
        from docpipe.exceptions.docpipe_exceptions import JobRunInvalidStateException

        # Arrange
        job_run_id = "test-job-run-123"
        job_stats = JobStats(
            job_id="test-job-123",
            job_run_id=job_run_id,
            status=terminal_status,
        )
        mock_store.get_job_stats.return_value = job_stats

        # Act & Assert
        with pytest.raises(JobRunInvalidStateException) as exc_info:
            job_tracker_service.request_cancel_job(job_run_id=job_run_id)

        # Verify exception details
        assert exc_info.value.job_run_id == job_run_id
        assert exc_info.value.current_state == terminal_status.value
        assert terminal_status.value in str(exc_info.value)
        assert "Cannot cancel" in str(exc_info.value)

    @pytest.mark.parametrize(
        "active_status",
        [
            ExecutionStatus.QUEUED,
            ExecutionStatus.PENDING,
            ExecutionStatus.STARTING,
            ExecutionStatus.RUNNING,
            ExecutionStatus.PAUSED,
            ExecutionStatus.RESUMING,
        ],
    )
    def test_cancel_job_in_active_state_succeeds(self, *, job_tracker_service, mock_store, active_status):
        """Test that canceling a job in active state succeeds."""
        # Arrange
        job_run_id = "test-job-run-456"
        job_stats = JobStats(
            job_id="test-job-456",
            job_run_id=job_run_id,
            status=active_status,
        )
        mock_store.get_job_stats.return_value = job_stats

        # Act
        job_tracker_service.request_cancel_job(job_run_id=job_run_id)

        # Assert
        mock_store.store_job_stats.assert_called_once()
        stored_stats = mock_store.store_job_stats.call_args[0][0]
        assert stored_stats.status == ExecutionStatus.CANCELING

    def test_cancel_already_canceling_job_succeeds(self, *, job_tracker_service, mock_store):
        """Test that canceling a job already in CANCELING state succeeds (idempotent)."""
        # Arrange
        job_run_id = "test-job-run-789"
        job_stats = JobStats(
            job_id="test-job-789",
            job_run_id=job_run_id,
            status=ExecutionStatus.CANCELING,
        )
        mock_store.get_job_stats.return_value = job_stats

        # Act
        job_tracker_service.request_cancel_job(job_run_id=job_run_id)


class TestMarkPendingBatchesAsSkipped:
    """Test mark_pending_batches_as_skipped method."""

    def test_mark_pending_batches_as_skipped_basic(self, *, job_tracker_service, mock_store):
        """Test marking pending batch node stats as skipped."""
        job_run_id = "test-job-run"

        # Setup: Create pending batch node stats
        pending_stats = [
            NodeStats(
                id="node1",
                name="extract",
                node_status=ExecutionStatus.PENDING.value,
                batch_id="batch-1",
                batch_num=1,
                total_docs=[],
                docs_completed=[],
                failed_docs=[],
                skipped_docs=[],
                col_names=[],
            ),
            NodeStats(
                id="node2",
                name="chunker",
                node_status=ExecutionStatus.PENDING.value,
                batch_id="batch-2",
                batch_num=2,
                total_docs=[],
                docs_completed=[],
                failed_docs=[],
                skipped_docs=[],
                col_names=[],
            ),
        ]

        mock_store.get_node_stats.return_value = pending_stats

        # Execute
        job_tracker_service.mark_pending_batches_as_skipped(
            job_run_id=job_run_id, reason="Skipped - flow failed in fail-fast mode"
        )

        # Verify bulk_store_node_stats was called with SKIPPED status
        assert mock_store.bulk_store_node_stats.called
        updated_stats = mock_store.bulk_store_node_stats.call_args[1]["node_stats_list"]
        assert len(updated_stats) == 2
        assert all(s.node_status == ExecutionStatus.SKIPPED.value for s in updated_stats)
        assert all(s.batch_id is not None for s in updated_stats)

    def test_mark_pending_batches_skips_completed(self, *, job_tracker_service, mock_store):
        """Test that completed batches are not marked as skipped."""
        job_run_id = "test-job-run"

        # Setup: Mix of pending and completed batch node stats
        mixed_stats = [
            NodeStats(
                id="node1",
                name="extract",
                node_status=ExecutionStatus.PENDING.value,
                batch_id="batch-1",
                batch_num=1,
                total_docs=[],
                docs_completed=[],
                failed_docs=[],
                skipped_docs=[],
                col_names=[],
            ),
            NodeStats(
                id="node2",
                name="chunker",
                node_status=ExecutionStatus.COMPLETED.value,  # Already completed
                batch_id="batch-2",
                batch_num=2,
                total_docs=["doc1"],
                docs_completed=["doc1"],
                failed_docs=[],
                skipped_docs=[],
                col_names=[],
            ),
        ]

        mock_store.get_node_stats.return_value = mixed_stats

        # Execute
        job_tracker_service.mark_pending_batches_as_skipped(
            job_run_id=job_run_id, reason="Skipped - flow failed in fail-fast mode"
        )

        # Verify only pending batch was updated
        assert mock_store.bulk_store_node_stats.called
        updated_stats = mock_store.bulk_store_node_stats.call_args[1]["node_stats_list"]
        assert len(updated_stats) == 1
        assert updated_stats[0].id == "node1"
        assert updated_stats[0].node_status == ExecutionStatus.SKIPPED.value

    def test_mark_pending_batches_handles_queued(self, *, job_tracker_service, mock_store):
        """Test that QUEUED batches are also marked as skipped."""
        job_run_id = "test-job-run"

        # Setup: QUEUED batch node stats
        queued_stats = [
            NodeStats(
                id="node1",
                name="extract",
                node_status=ExecutionStatus.QUEUED.value,
                batch_id="batch-1",
                batch_num=1,
                total_docs=[],
                docs_completed=[],
                failed_docs=[],
                skipped_docs=[],
                col_names=[],
            ),
        ]

        mock_store.get_node_stats.return_value = queued_stats

        # Execute
        job_tracker_service.mark_pending_batches_as_skipped(
            job_run_id=job_run_id, reason="Skipped - flow failed in fail-fast mode"
        )

        # Verify QUEUED batch was updated to SKIPPED
        assert mock_store.bulk_store_node_stats.called
        updated_stats = mock_store.bulk_store_node_stats.call_args[1]["node_stats_list"]
        assert len(updated_stats) == 1
        assert updated_stats[0].node_status == ExecutionStatus.SKIPPED.value

    def test_mark_pending_batches_no_pending_batches(self, *, job_tracker_service, mock_store):
        """Test when there are no pending batches."""
        job_run_id = "test-job-run"

        # Setup: Only completed batches
        completed_stats = [
            NodeStats(
                id="node1",
                name="extract",
                node_status=ExecutionStatus.COMPLETED.value,
                batch_id="batch-1",
                batch_num=1,
                total_docs=["doc1"],
                docs_completed=["doc1"],
                failed_docs=[],
                skipped_docs=[],
                col_names=[],
            ),
        ]

        mock_store.get_node_stats.return_value = completed_stats

        # Execute
        job_tracker_service.mark_pending_batches_as_skipped(
            job_run_id=job_run_id, reason="Skipped - flow failed in fail-fast mode"
        )

        # Verify bulk_store_node_stats was not called
        assert not mock_store.bulk_store_node_stats.called

    def test_mark_pending_batches_empty_node_stats(self, *, job_tracker_service, mock_store):
        """Test when there are no node stats at all."""
        job_run_id = "test-job-run"

        # Setup: Empty node stats
        mock_store.get_node_stats.return_value = []

        # Execute
        job_tracker_service.mark_pending_batches_as_skipped(
            job_run_id=job_run_id, reason="Skipped - flow failed in fail-fast mode"
        )

        # Verify bulk_store_node_stats was not called
        assert not mock_store.bulk_store_node_stats.called

    def test_mark_pending_batches_preserves_metadata(self, *, job_tracker_service, mock_store):
        """Test that skip reason is added to metadata."""
        job_run_id = "test-job-run"
        reason = "Skipped - flow failed in fail-fast mode before batch execution"

        # Setup: Pending batch
        pending_stats = [
            NodeStats(
                id="node1",
                name="extract",
                node_status=ExecutionStatus.PENDING.value,
                batch_id="batch-1",
                batch_num=1,
                total_docs=[],
                docs_completed=[],
                failed_docs=[],
                skipped_docs=[],
                col_names=[],
            ),
        ]

        mock_store.get_node_stats.return_value = pending_stats

        # Execute
        job_tracker_service.mark_pending_batches_as_skipped(job_run_id=job_run_id, reason=reason)

        # Verify metadata contains skip reason
        updated_stats = mock_store.bulk_store_node_stats.call_args[1]["node_stats_list"]
        assert len(updated_stats) == 1
        assert "node_metadata" in updated_stats[0].node_metadata
        assert "skip_reason" in updated_stats[0].node_metadata["node_metadata"]
        assert updated_stats[0].node_metadata["node_metadata"]["skip_reason"] == reason


class TestGetNodeStats:
    def test_delegates_to_aggregator(self, *, job_tracker_service, mock_aggregator):
        """Covers get_node_stats (line 715)."""
        mock_aggregator.get_aggregated_node_stats.return_value = {"n1": NodeStats(id="n1", name="ingest")}
        result = job_tracker_service.get_node_stats(job_id=JOB_ID, job_run_id=JOB_RUN_ID)
        mock_aggregator.get_aggregated_node_stats.assert_called_once_with(job_id=JOB_ID, job_run_id=JOB_RUN_ID)
        assert "n1" in result


class TestCountJobRuns:
    def test_count_job_runs_delegates_to_store(self, *, job_tracker_service, mock_store):
        mock_store.count_job_runs.return_value = 7

        result = job_tracker_service.count_job_runs(
            job_id=JOB_ID,
            job_ids=[JOB_ID],
            status=ExecutionStatus.COMPLETED,
        )

        assert result == 7
        mock_store.count_job_runs.assert_called_once_with(
            job_id=JOB_ID,
            job_ids=[JOB_ID],
            status=ExecutionStatus.COMPLETED,
        )


class TestCancelJobRunIfCancelling:
    def test_returns_false_when_no_job(self, *, job_tracker_service, mock_store):
        """Line 846 branch: job not found."""
        mock_store.get_job_stats.return_value = None
        assert job_tracker_service.cancel_job_run_if_cancelling(job_run_id=JOB_RUN_ID) is False

    def test_returns_true_and_stores_when_canceling(self, *, job_tracker_service, mock_store):
        """Lines 848-856: CANCELING -> CANCELED."""
        from docpipe.core.job_management.domain.models.job_stats import JobStats

        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.CANCELING)
        mock_store.get_job_stats.return_value = job_stats
        result = job_tracker_service.cancel_job_run_if_cancelling(job_run_id=JOB_RUN_ID)
        assert result is True
        mock_store.store_job_stats.assert_called_once()

    def test_returns_false_when_not_canceling(self, *, job_tracker_service, mock_store):
        """Line 858: non-canceling status."""
        from docpipe.core.job_management.domain.models.job_stats import JobStats

        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.RUNNING)
        mock_store.get_job_stats.return_value = job_stats
        result = job_tracker_service.cancel_job_run_if_cancelling(job_run_id=JOB_RUN_ID)
        assert result is False


class TestRequestDeleteJobRun:
    def test_raises_when_not_found(self, *, job_tracker_service, mock_store):
        """Lines 873-877: job not found."""
        from docpipe.exceptions.docpipe_exceptions import JobRunNotFoundException

        mock_store.get_job_stats.return_value = None
        with pytest.raises(JobRunNotFoundException):
            job_tracker_service.request_delete_job_run(job_run_id=JOB_RUN_ID)

    def test_deletes_and_returns_message(self, *, job_tracker_service, mock_store):
        """Lines 880-883: happy path."""
        from docpipe.core.job_management.domain.models.job_stats import JobStats

        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID)
        mock_store.get_job_stats.return_value = job_stats
        result = job_tracker_service.request_delete_job_run(job_run_id=JOB_RUN_ID)
        mock_store.delete_job_stats.assert_called_once_with(JOB_RUN_ID)
        assert JOB_RUN_ID in result


class TestDeleteJobRunsByJobId:
    """Tests for JobTrackerService.delete_job_runs_by_job_id."""

    def test_no_runs_returns_zero(self, *, job_tracker_service, mock_store):
        """Returns 0 immediately when no job runs exist for the given job_id."""
        mock_store.list_job_runs.return_value = []
        result = job_tracker_service.delete_job_runs_by_job_id(job_id=JOB_ID)
        assert result == 0
        mock_store.delete_job_stats.assert_not_called()

    def test_deletes_all_runs_for_job_id(self, *, job_tracker_service, mock_store):
        """Deletes every run returned by list_job_runs and returns the count."""
        run_id_1 = "aaaaaaaa-0000-0000-0000-000000000001"
        run_id_2 = "aaaaaaaa-0000-0000-0000-000000000002"
        mock_store.list_job_runs.return_value = [
            JobStats(job_id=JOB_ID, job_run_id=run_id_1),
            JobStats(job_id=JOB_ID, job_run_id=run_id_2),
        ]
        result = job_tracker_service.delete_job_runs_by_job_id(job_id=JOB_ID)
        assert result == 2
        mock_store.delete_job_stats.assert_any_call(run_id_1)
        mock_store.delete_job_stats.assert_any_call(run_id_2)
        assert mock_store.delete_job_stats.call_count == 2

    def test_partial_failure_continues_and_returns_deleted_count(self, *, job_tracker_service, mock_store):
        """A failing delete for one run does not abort others; only successful count is returned."""
        run_id_ok = "bbbbbbbb-0000-0000-0000-000000000001"
        run_id_bad = "bbbbbbbb-0000-0000-0000-000000000002"
        mock_store.list_job_runs.return_value = [
            JobStats(job_id=JOB_ID, job_run_id=run_id_ok),
            JobStats(job_id=JOB_ID, job_run_id=run_id_bad),
        ]
        mock_store.delete_job_stats.side_effect = [None, RuntimeError("store error")]
        result = job_tracker_service.delete_job_runs_by_job_id(job_id=JOB_ID)
        assert result == 1

    def test_list_called_with_correct_job_id(self, *, job_tracker_service, mock_store):
        """list_job_runs is called with the provided job_id."""
        mock_store.list_job_runs.return_value = []
        job_tracker_service.delete_job_runs_by_job_id(job_id=JOB_ID)
        mock_store.list_job_runs.assert_called_once_with(job_id=JOB_ID, limit=100_000)


class TestBuildBatchSummaryLines:
    def test_empty_batch_stats_returns_empty(self, *, job_tracker_service):
        """Line 910-911: empty dict."""
        result = job_tracker_service._build_batch_summary_lines({})
        assert result == []

    def test_batch_with_failed_status_appended(self, *, job_tracker_service):
        """Lines 922-935: failed batch shows error details."""
        batch_stat = NodeStats(
            id="b1",
            name="extract",
            node_status=ExecutionStatus.FAILED.value,
            batch_num=1,
            time_taken=2.0,
            total_docs=["d1"],
            failed_docs=["d1"],
            docs_completed=[],
            skipped_docs=[],
            col_names=[],
        )
        batch_stat.error = "timeout"
        lines = job_tracker_service._build_batch_summary_lines({"batch_1": batch_stat})
        assert any("Error Details" in line for line in lines)

    def test_skipped_batch_with_reason(self, *, job_tracker_service):
        """Line 931-932: skipped batch with error reason."""
        batch_stat = NodeStats(
            id="b1",
            name="extract",
            node_status=ExecutionStatus.SKIPPED.value,
            batch_num=1,
            time_taken=0.0,
            total_docs=[],
            failed_docs=[],
            docs_completed=[],
            skipped_docs=[],
            col_names=[],
        )
        batch_stat.error = "upstream failed"
        lines = job_tracker_service._build_batch_summary_lines({"batch_1": batch_stat})
        assert any("Reason: upstream failed" in line for line in lines)


class TestBuildNodeLogLines:
    def test_builds_lines_without_batch_stats(self, *, job_tracker_service):
        """Lines 945-979: builds log lines from NodeStats."""
        node = NodeStats(
            id="n1",
            name="ingest",
            node_status=ExecutionStatus.COMPLETED.value,
            time_taken=3.0,
            total_docs=["d1"],
            docs_completed=["d1"],
            failed_docs=[],
            skipped_docs=[],
            col_names=["id", "content"],
        )
        lines = job_tracker_service._build_node_log_lines(node)
        assert any("ingest" in line for line in lines)
        assert any("Operator Summary" in line for line in lines)

    def test_builds_lines_with_batch_stats(self, *, job_tracker_service):
        """Lines 963-964: includes batch summary when batch_stats present."""
        node = NodeStats(
            id="n1",
            name="extract",
            node_status=ExecutionStatus.COMPLETED.value,
            time_taken=5.0,
            total_docs=["d1"],
            docs_completed=["d1"],
            failed_docs=[],
            skipped_docs=[],
            col_names=[],
        )
        batch_stat = NodeStats(
            id="n1",
            name="extract",
            node_status=ExecutionStatus.COMPLETED.value,
            batch_num=1,
            time_taken=2.0,
            total_docs=["d1"],
            docs_completed=["d1"],
            failed_docs=[],
            skipped_docs=[],
            col_names=[],
        )
        lines = job_tracker_service._build_node_log_lines(node, batch_stats={"batch_1": batch_stat})
        assert any("Batch" in line for line in lines)


class TestGetJobRunLogs:
    def test_returns_empty_when_no_job(self, *, job_tracker_service, mock_store):
        """Lines 986-987: no job found."""
        mock_store.get_job_stats.return_value = None
        result = job_tracker_service.get_job_run_logs(job_run_id=JOB_RUN_ID)
        assert result == []

    def test_returns_logs_for_job(self, *, job_tracker_service, mock_store, mock_aggregator):
        """Lines 989-1006: returns formatted log lines."""
        from docpipe.core.job_management.domain.models.job_stats import JobStats

        node = NodeStats(
            id="n1",
            name="ingest",
            node_status=ExecutionStatus.COMPLETED.value,
            time_taken=1.0,
            total_docs=["d1"],
            docs_completed=["d1"],
            failed_docs=[],
            skipped_docs=[],
            col_names=[],
        )
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID)
        mock_store.get_job_stats.return_value = job_stats
        # get_job() calls aggregator — return proper dict and empty batch stats
        mock_aggregator.get_aggregated_node_stats.return_value = {"n1": node}
        mock_aggregator.get_batch_node_stats.return_value = {}
        result = job_tracker_service.get_job_run_logs(job_run_id=JOB_RUN_ID)
        assert len(result) > 0


class TestIsJobRunComplete:
    def test_returns_false_when_not_found(self, *, job_tracker_service, mock_store):
        """Lines 1018-1020."""
        mock_store.get_job_stats.return_value = None
        assert job_tracker_service.is_job_run_complete(job_run_id=JOB_RUN_ID) is False

    def test_returns_true_for_completed(self, *, job_tracker_service, mock_store):
        """Lines 1022-1027."""
        from docpipe.core.job_management.domain.models.job_stats import JobStats

        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED)
        mock_store.get_job_stats.return_value = job_stats
        assert job_tracker_service.is_job_run_complete(job_run_id=JOB_RUN_ID) is True

    def test_returns_false_for_running(self, *, job_tracker_service, mock_store):
        from docpipe.core.job_management.domain.models.job_stats import JobStats

        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID, status=ExecutionStatus.RUNNING)
        mock_store.get_job_stats.return_value = job_stats
        assert job_tracker_service.is_job_run_complete(job_run_id=JOB_RUN_ID) is False


class TestCalculateNodeSequence:
    def test_empty_returns_empty(self):
        assert JobTrackerService._calculate_node_sequence(node_stats={}) == []

    def test_sorts_by_start_time(self):
        """Lines 1464-1472."""
        n1 = NodeStats(id="n1", name="a", start_time=10, end_time=20)
        n2 = NodeStats(id="n2", name="b", start_time=5, end_time=15)
        result = JobTrackerService._calculate_node_sequence(node_stats={"n1": n1, "n2": n2})
        assert result[0] == "n2"


class TestBuildNodeMetadataArray:
    def test_builds_from_object_stats(self):
        """Lines 1478-1494."""
        node = NodeStats(id="n1", name="ingest")
        result = JobTrackerService._build_node_metadata_array(node_stats={"n1": node})
        assert len(result) == 1
        assert result[0]["id"] == "n1"
        assert result[0]["operator"] == "ingest"

    def test_builds_from_dict_stats(self):
        """Line 1480-1481: dict branch."""
        node = {"name": "extract", "node_metadata": {"total_docs": 10}}
        result = JobTrackerService._build_node_metadata_array(node_stats={"n1": node})
        assert result[0]["operator"] == "extract"


class TestDetectPartialBatchFailure:
    def test_returns_false_when_batching_disabled(self, *, job_tracker_service, mock_store):
        """Line 1436-1437."""
        from docpipe.core.job_management.domain.models.job_stats import JobStats

        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID)
        result = job_tracker_service.detect_partial_batch_failure(
            job_stats=job_stats, global_config={"enable_micro_batching": False}
        )
        assert result is False

    def test_returns_false_when_no_batch_stats(self, *, job_tracker_service, mock_store):
        """Lines 1440-1441."""
        from docpipe.core.job_management.domain.models.job_stats import JobStats

        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID)
        job_stats.batch_node_stats = {}
        result = job_tracker_service.detect_partial_batch_failure(
            job_stats=job_stats,
            global_config={"enable_micro_batching": True, "continue_on_batch_failure": True},
        )
        assert result is False

    def test_returns_true_for_partial_failure(self, *, job_tracker_service):
        """Lines 1447-1455: some but not all batches failed."""
        from docpipe.core.job_management.domain.models.job_stats import JobStats

        failed_stat = NodeStats(id="n1", name="x", node_status=ExecutionStatus.FAILED.value)
        ok_stat = NodeStats(id="n1", name="x", node_status=ExecutionStatus.COMPLETED.value)
        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID)
        job_stats.batch_node_stats = {"n1": {"b1": failed_stat, "b2": ok_stat}}
        result = job_tracker_service.detect_partial_batch_failure(
            job_stats=job_stats,
            global_config={"enable_micro_batching": True, "continue_on_batch_failure": True},
        )
        assert result is True


class TestCreatePendingBatchNodeStats:
    def test_creates_pending_stats_bulk(self, *, job_tracker_service, mock_store):
        """Lines 1579-1614."""
        job_tracker_service.create_pending_batch_node_stats(
            job_run_id=JOB_RUN_ID,
            batch_ids=["b1", "b2"],
            batch_nums=[1, 2],
            downstream_node_ids=["n1"],
            downstream_node_names=["extract"],
        )
        mock_store.bulk_store_node_stats.assert_called_once()
        stored = mock_store.bulk_store_node_stats.call_args[1]["node_stats_list"]
        assert len(stored) == 2

    def test_raises_on_batch_length_mismatch(self, *, job_tracker_service):
        """Line 1580."""
        with pytest.raises(ValueError, match="same length"):
            job_tracker_service.create_pending_batch_node_stats(
                job_run_id=JOB_RUN_ID,
                batch_ids=["b1"],
                batch_nums=[1, 2],
                downstream_node_ids=["n1"],
                downstream_node_names=["extract"],
            )

    def test_raises_on_node_length_mismatch(self, *, job_tracker_service):
        """Lines 1582-1586."""
        with pytest.raises(ValueError, match="same length"):
            job_tracker_service.create_pending_batch_node_stats(
                job_run_id=JOB_RUN_ID,
                batch_ids=["b1"],
                batch_nums=[1],
                downstream_node_ids=["n1", "n2"],
                downstream_node_names=["extract"],
            )


class TestUpdateDocCounts:
    def test_raises_when_job_not_found(self, *, job_tracker_service, mock_store):
        """Lines 731-733."""
        from docpipe.exceptions.docpipe_exceptions import JobRunNotFoundException

        mock_store.get_job_stats.return_value = None
        with pytest.raises(JobRunNotFoundException):
            job_tracker_service.update_doc_counts(job_run_id=JOB_RUN_ID, metadata={}, operator_category="ingest")

    def test_updates_ingest_total_docs_list(self, *, job_tracker_service, mock_store):
        """Lines 743-750: ingest category, list value."""
        from docpipe.core.constants.constants import Metrics
        from docpipe.core.job_management.domain.models.job_stats import JobStats

        job_stats = JobStats(job_id=JOB_ID, job_run_id=JOB_RUN_ID)
        mock_store.get_job_stats.return_value = job_stats
        job_tracker_service.update_doc_counts(
            job_run_id=JOB_RUN_ID,
            metadata={Metrics.External.TOTAL_DOCS: ["d1", "d2"]},
            operator_category="Ingest",
        )
        assert job_stats.total_docs == 2
