"""
NodeStatsAggregator reading from the real InMemoryJobStatsStore.
"""

from docpipe.core.constants.constants import ExecutionStatus
from docpipe.core.job_management.adapters.stores.inmemory.inmemory_job_stats_store import InMemoryJobStatsStore
from docpipe.core.job_management.application.services.node_stats_aggregator import NodeStatsAggregator
from docpipe.core.job_management.domain.models import NodeStats

JOB_ID = "job-1"
RUN_ID = "run-1"


def _store_all(store: InMemoryJobStatsStore, records: list[NodeStats]) -> None:
    for record in records:
        store.store_node_stats(job_run_id=RUN_ID, node_stats=record)


class TestAggregatedNodeStatsFromInMemoryStore:
    """get_aggregated_node_stats over records persisted in the in-memory store."""

    def test_batch_and_non_batch_nodes_are_returned_per_node(self):
        """Batch records are aggregated per node, non-batch records are returned with progress."""
        store = InMemoryJobStatsStore()
        _store_all(
            store,
            [
                NodeStats(
                    id="ingest",
                    name="Ingest",
                    node_status=ExecutionStatus.COMPLETED.value,
                    total_docs=["d1", "d2", "d3"],
                    docs_completed=["d1", "d2", "d3"],
                    node_metadata={"id": "ingest", "operator": "Ingest", "node_metadata": {"documents_in_scope": 3}},
                ),
                NodeStats(
                    id="chunk",
                    name="Chunker",
                    node_status=ExecutionStatus.COMPLETED.value,
                    batch_id="b0",
                    batch_num=0,
                    total_docs=["d1", "d2"],
                    docs_completed=["d1", "d2"],
                    node_metadata={
                        "id": "chunk",
                        "operator": "Chunker",
                        "node_metadata": {"documents_in_scope": 2, "processed_docs": 2, "total_chunks": 7},
                    },
                ),
                NodeStats(
                    id="chunk",
                    name="Chunker",
                    node_status=ExecutionStatus.RUNNING.value,
                    batch_id="b1",
                    batch_num=1,
                    total_docs=["d3"],
                    node_metadata={"id": "chunk", "operator": "Chunker", "node_metadata": {"documents_in_scope": 1}},
                ),
                # Every batch of this node is still queued: the node is not reported yet.
                NodeStats(id="embed", name="Embeddings", node_status=ExecutionStatus.QUEUED.value, batch_id="b0"),
                NodeStats(id="embed", name="Embeddings", node_status=ExecutionStatus.PENDING.value, batch_id="b1"),
            ],
        )

        result = NodeStatsAggregator(job_stats_store=store).get_aggregated_node_stats(job_id=JOB_ID, job_run_id=RUN_ID)

        assert set(result) == {"ingest", "chunk"}

        ingest = result["ingest"]
        assert ingest.node_metadata is not None
        assert ingest.node_metadata["node_metadata"]["progress_percentage"] == 100.0

        chunk = result["chunk"]
        assert chunk.name == "Chunker"
        assert chunk.node_status == ExecutionStatus.RUNNING.value
        assert chunk.total_docs == ["d1", "d2", "d3"]
        assert chunk.docs_completed_count == 2
        assert chunk.batch_id is None
        assert chunk.node_metadata is not None
        inner = chunk.node_metadata["node_metadata"]
        assert inner["documents_in_scope"] == 3
        assert inner["total_chunks"] == 7
        assert inner["Progress"] == "1 of 2 batches (50.0%) | Completed: 1, Running: 1"

    def test_records_without_node_id_are_ignored(self):
        """Batch and non-batch records with an empty node id are not keyed into the result."""
        store = InMemoryJobStatsStore()
        _store_all(
            store,
            [
                NodeStats(id="", name="orphan", node_status=ExecutionStatus.COMPLETED.value),
                NodeStats(id="", name="orphan", node_status=ExecutionStatus.COMPLETED.value, batch_id="b0"),
                NodeStats(id="extract", name="Extract", node_status=ExecutionStatus.COMPLETED.value, batch_id="b0"),
            ],
        )

        result = NodeStatsAggregator(job_stats_store=store).get_aggregated_node_stats(job_id=JOB_ID, job_run_id=RUN_ID)

        assert list(result) == ["extract"]
        assert result["extract"].node_status == ExecutionStatus.COMPLETED.value

    def test_unknown_run_gives_empty_result(self):
        """A run without stored node stats aggregates to {}."""
        aggregator = NodeStatsAggregator(job_stats_store=InMemoryJobStatsStore())

        assert aggregator.get_aggregated_node_stats(job_id=JOB_ID, job_run_id="missing") == {}

    def test_batch_node_stats_are_passed_through_grouped_by_node_and_batch(self):
        """get_batch_node_stats returns the store's raw {node_id: {batch_id: NodeStats}} view."""
        store = InMemoryJobStatsStore()
        _store_all(
            store,
            [
                NodeStats(id="extract", name="Extract", node_status=ExecutionStatus.COMPLETED.value, batch_id="b0"),
                NodeStats(id="extract", name="Extract", node_status=ExecutionStatus.RUNNING.value, batch_id="b1"),
            ],
        )

        result = NodeStatsAggregator(job_stats_store=store).get_batch_node_stats(job_id=JOB_ID, job_run_id=RUN_ID)

        assert set(result) == {"extract"}
        assert {batch_id: stats.node_status for batch_id, stats in result["extract"].items()} == {
            "b0": ExecutionStatus.COMPLETED.value,
            "b1": ExecutionStatus.RUNNING.value,
        }
