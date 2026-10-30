"""
Unit tests for aggregate_batch_node_stats, the read-side batch aggregation.

The batch records are shaped the way JobTrackerService writes them: the
operator metadata sits in a NodeMetadataItem payload
(``{"id", "operator", "node_metadata": {...}}``), started batches carry
``documents_in_scope``, completed batches carry the operator's base metadata
and failed/legacy records may carry less.
"""

from typing import Any

from docpipe.core.constants.constants import ExecutionStatus
from docpipe.core.job_management.application.aggregation import MetadataAggregator, aggregate_batch_node_stats
from docpipe.core.job_management.domain.models import NodeStats

NODE_ID = "node-extract"


def _payload(inner: dict[str, Any], *, operator: str = "Extract") -> dict[str, Any]:
    """Wrap operator metadata the way JobTrackerService stores it (NodeMetadataItem)."""
    return {"id": NODE_ID, "operator": operator, "node_metadata": inner}


def _batch(
    batch_num: int,
    status: ExecutionStatus,
    *,
    node_metadata: dict[str, Any] | None = None,
    **fields: Any,
) -> NodeStats:
    """Build one batch-level NodeStats record for NODE_ID."""
    return NodeStats(
        id=NODE_ID,
        name="Extract",
        node_status=status.value,
        batch_id=f"batch-{batch_num}",
        batch_num=batch_num,
        node_metadata=node_metadata,
        **fields,
    )


def _stage(*, total: int, completed: int, status: str) -> dict[str, Any]:
    """One per-stage entry of extraction_stage_progress as the extract operator writes it."""
    return {
        "status": status,
        "documents_total": total,
        "documents_completed": completed,
        "documents_failed": 0,
        "progress_percentage": round(completed / total * 100, 2) if total else 0.0,
    }


def _aggregate(records: list[NodeStats]) -> NodeStats:
    return aggregate_batch_node_stats(node_id=NODE_ID, batch_records=records, aggregator=MetadataAggregator())


def _inner(result: NodeStats) -> dict[str, Any]:
    assert result.node_metadata is not None
    return result.node_metadata["node_metadata"]


class TestNoBatches:
    """A node without any batch record yet."""

    def test_returns_pending_placeholder(self):
        """No batches → an empty Pending NodeStats for the node (nothing has run)."""
        result = aggregate_batch_node_stats(node_id=NODE_ID, batch_records=[], aggregator=MetadataAggregator())

        assert result.id == NODE_ID
        assert result.name == "Unknown"
        assert result.node_status == ExecutionStatus.PENDING.value
        assert (result.start_time, result.end_time, result.time_taken) == (0, 0, 0)
        assert result.total_docs == []
        assert result.docs_completed == []
        assert result.docs_completed_count == 0
        assert result.node_metadata == {}
        assert result.error == ""


class TestAggregatedStatusAndProgress:
    """Node status and the batch-based Progress field."""

    def test_completed_with_errors_batch_makes_node_completed_with_errors(self):
        """A CompletedWithErrors batch without any Failed batch still yields CompletedWithErrors."""
        result = _aggregate(
            [
                _batch(0, ExecutionStatus.COMPLETED),
                _batch(1, ExecutionStatus.COMPLETED_WITH_ERRORS),
            ]
        )

        assert result.node_status == ExecutionStatus.COMPLETED_WITH_ERRORS.value
        inner = _inner(result)
        assert inner["node_status"] == ExecutionStatus.COMPLETED_WITH_ERRORS.value
        # Both variants count as "Completed" in the breakdown.
        assert inner["Progress"] == "2 of 2 batches (100.0%) | Completed: 2"
        assert inner["progress_percentage"] == 100.0

    def test_completed_with_warnings_batch_makes_node_completed_with_warnings(self):
        """A CompletedWithWarnings batch among Completed ones yields CompletedWithWarnings."""
        result = _aggregate(
            [
                _batch(0, ExecutionStatus.COMPLETED),
                _batch(1, ExecutionStatus.COMPLETED_WITH_WARNINGS),
            ]
        )

        assert result.node_status == ExecutionStatus.COMPLETED_WITH_WARNINGS.value
        assert _inner(result)["Progress"] == "2 of 2 batches (100.0%) | Completed: 2"

    def test_starting_batch_keeps_node_running(self):
        """A batch that is still Starting is not finished, so the node stays Running."""
        result = _aggregate(
            [
                _batch(0, ExecutionStatus.COMPLETED),
                _batch(1, ExecutionStatus.STARTING),
            ]
        )

        assert result.node_status == ExecutionStatus.RUNNING.value
        inner = _inner(result)
        assert inner["Progress"] == "1 of 2 batches (50.0%) | Completed: 1"
        assert inner["progress_percentage"] == 50.0

    def test_progress_breaks_down_running_failed_and_skipped_batches(self):
        """Failed and Skipped batches count as finished and are listed in the breakdown."""
        result = _aggregate(
            [
                _batch(0, ExecutionStatus.COMPLETED),
                _batch(1, ExecutionStatus.RUNNING),
                _batch(2, ExecutionStatus.FAILED),
                _batch(3, ExecutionStatus.SKIPPED),
            ]
        )

        assert result.node_status == ExecutionStatus.RUNNING.value
        assert _inner(result)["Progress"] == "3 of 4 batches (75.0%) | Completed: 1, Running: 1, Failed: 1, Skipped: 1"


class TestDocumentListsAndTimes:
    """Document lists are unioned across batches; counts are derived from the unions."""

    def test_document_lists_are_unioned_and_counted(self):
        """Overlapping doc IDs are deduplicated; processed = completed + failed + skipped."""
        result = _aggregate(
            [
                _batch(
                    0,
                    ExecutionStatus.COMPLETED_WITH_ERRORS,
                    start_time=1_000,
                    end_time=1_100,
                    col_names=["content", "doc_id"],
                    total_docs=["d1", "d2", "d3"],
                    docs_completed=["d1"],
                    failed_docs=["d2"],
                    skipped_docs=["d3"],
                ),
                _batch(
                    1,
                    ExecutionStatus.COMPLETED,
                    start_time=1_050,
                    end_time=1_300,
                    col_names=["content", "doc_id"],
                    total_docs=["d3", "d4", "d5"],
                    docs_completed=["d4", "d5"],
                    skipped_docs=["d3"],
                ),
                # A batch that has not started has no timestamps; it must not drag start_time to 0.
                _batch(2, ExecutionStatus.RUNNING, total_docs=["d6"]),
            ]
        )

        assert result.col_names == ["content", "doc_id"]
        assert result.total_docs == ["d1", "d2", "d3", "d4", "d5", "d6"]
        assert result.docs_completed == ["d1", "d4", "d5"]
        assert result.failed_docs == ["d2"]
        assert result.skipped_docs == ["d3"]
        assert result.docs_completed_count == 3
        assert result.start_time == 1_000
        assert result.end_time == 1_300

        inner = _inner(result)
        assert inner["documents_in_scope"] == 6
        assert inner["completed_docs_count"] == 3
        assert inner["processed_docs"] == 5


class TestExtractionStageProgress:
    """Text/entity extraction progress fields for extraction operators."""

    def test_finished_batches_backfill_text_extraction_from_persistent_counts(self):
        """Without live stage detail, finished batches contribute documents_in_scope/processed_docs."""
        result = _aggregate(
            [
                # Old-style record that still carries the flat transient extraction counters.
                _batch(
                    0,
                    ExecutionStatus.COMPLETED,
                    total_docs=["d1", "d2", "d3"],
                    docs_completed=["d1", "d2", "d3"],
                    node_metadata=_payload(
                        {
                            "documents_in_scope": 3,
                            "processed_docs": 3,
                            "node_status": "Completed",
                            "extraction_running": 3,
                            "extraction_completed": 3,
                        }
                    ),
                ),
                _batch(
                    1,
                    ExecutionStatus.COMPLETED,
                    total_docs=["d4", "d5"],
                    docs_completed=["d4", "d5"],
                    node_metadata=_payload({"documents_in_scope": 2, "processed_docs": 2, "node_status": "Completed"}),
                ),
                # The operator reported the whole batch as failed.
                _batch(
                    2,
                    ExecutionStatus.FAILED,
                    total_docs=["d6"],
                    failed_docs=["d6"],
                    node_metadata=_payload(
                        {"documents_in_scope": 1, "processed_docs": 0, "failed_docs_count": 1, "node_status": "Failed"}
                    ),
                ),
                # An empty batch and a batch whose operator returned no metadata add nothing.
                _batch(
                    3,
                    ExecutionStatus.COMPLETED,
                    node_metadata=_payload({"documents_in_scope": 0, "processed_docs": 0, "node_status": "Completed"}),
                ),
                _batch(4, ExecutionStatus.COMPLETED),
                # A skipped batch is not a finished extraction batch.
                _batch(
                    5,
                    ExecutionStatus.SKIPPED,
                    total_docs=["d7"],
                    node_metadata=_payload({"documents_in_scope": 1, "node_status": "Skipped"}),
                ),
            ]
        )

        assert result.node_status == ExecutionStatus.COMPLETED_WITH_ERRORS.value
        inner = _inner(result)
        assert inner["Text Extracted"] == "5 of 6 (83.33%)"
        assert "Entities Extracted" not in inner
        assert inner["Progress"] == "6 of 6 batches (100.0%) | Completed: 4, Failed: 1, Skipped: 1"
        # The transient counters never reach the aggregated view.
        assert "extraction_running" not in inner
        assert "extraction_completed" not in inner
        assert "extraction_stage_progress" not in inner

    def test_live_stage_detail_is_combined_with_finished_batches(self):
        """Running stage detail discovers entity extraction; finished batches add to every active stage."""
        result = _aggregate(
            [
                _batch(
                    0,
                    ExecutionStatus.RUNNING,
                    total_docs=["d1", "d2"],
                    node_metadata=_payload(
                        {
                            "documents_in_scope": 2,
                            "node_status": "Running",
                            "extraction_stage_progress": {
                                "text_extraction": _stage(total=2, completed=1, status="running"),
                                "entity_extraction": _stage(total=2, completed=0, status="pending"),
                                "table_extraction": _stage(total=2, completed=2, status="completed"),
                            },
                        }
                    ),
                ),
                _batch(
                    1,
                    ExecutionStatus.COMPLETED,
                    total_docs=["d3", "d4", "d5"],
                    docs_completed=["d3", "d4", "d5"],
                    node_metadata=_payload({"documents_in_scope": 3, "processed_docs": 3, "node_status": "Completed"}),
                ),
                # A running batch without any metadata yet contributes nothing.
                _batch(2, ExecutionStatus.RUNNING),
            ]
        )

        assert result.node_status == ExecutionStatus.RUNNING.value
        inner = _inner(result)
        assert inner["Text Extracted"] == "4 of 5 (80.0%)"
        assert inner["Entities Extracted"] == "3 of 5 (60.0%)"
        # Stages other than text/entity extraction get a title-cased field name; finished
        # batches only back-fill text and entity extraction.
        assert inner["Table Extraction"] == "2 of 2 (100.0%)"
        assert "extraction_stage_progress" not in inner

    def test_stage_without_documents_is_not_reported_and_pending_batches_are_flagged(self):
        """A stage with no documents gets no field; queued batches turn the figure into '(more in queue)'."""
        result = _aggregate(
            [
                _batch(
                    0,
                    ExecutionStatus.RUNNING,
                    total_docs=["d1", "d2", "d3", "d4"],
                    node_metadata=_payload(
                        {
                            "documents_in_scope": 4,
                            "node_status": "Running",
                            "extraction_stage_progress": {
                                "text_extraction": _stage(total=4, completed=2, status="running"),
                                "entity_extraction": _stage(total=0, completed=0, status="pending"),
                            },
                        }
                    ),
                ),
                _batch(1, ExecutionStatus.PENDING, total_docs=["d5", "d6", "d7"]),
            ]
        )

        inner = _inner(result)
        assert inner["Text Extracted"] == "2 of 4 (more in queue)"
        assert "Entities Extracted" not in inner

    def test_non_dict_stage_progress_falls_back_to_persistent_counts(self):
        """A malformed (non-dict) extraction_stage_progress is ignored instead of crashing the read."""
        result = _aggregate(
            [
                _batch(
                    0,
                    ExecutionStatus.COMPLETED,
                    total_docs=["d1", "d2"],
                    docs_completed=["d1", "d2"],
                    node_metadata=_payload(
                        {
                            "documents_in_scope": 2,
                            "processed_docs": 2,
                            "node_status": "Completed",
                            "extraction_stage_progress": None,
                        }
                    ),
                ),
            ]
        )

        assert result.node_status == ExecutionStatus.COMPLETED.value
        inner = _inner(result)
        assert inner["Text Extracted"] == "2 of 2 (100.0%)"
        assert inner.get("extraction_stage_progress") is None

    def test_flat_legacy_counters_without_documents_give_no_stage_field(self):
        """Flat (un-nested) legacy counters mark an extraction node; with no counts there is no stage field."""
        result = _aggregate(
            [_batch(0, ExecutionStatus.RUNNING, node_metadata={"extraction_running": 0, "extraction_completed": 0})]
        )

        assert result.node_status == ExecutionStatus.RUNNING.value
        assert result.node_metadata is not None
        assert "extraction_running" not in result.node_metadata
        inner = _inner(result)
        assert "Text Extracted" not in inner
        assert "extraction_completed" not in inner
        assert inner["Progress"] == "0 of 1 batches (0.0%) | Completed: 0, Running: 1"


class TestClassificationProgress:
    """Documents Classified field for classification operators."""

    def test_transient_and_persistent_counts_are_summed(self):
        """Running batches report transient counters, finished ones their persistent counts."""
        result = _aggregate(
            [
                _batch(
                    0,
                    ExecutionStatus.COMPLETED,
                    total_docs=["d1", "d2", "d3"],
                    docs_completed=["d1", "d2", "d3"],
                    node_metadata=_payload(
                        {"documents_in_scope": 3, "processed_docs": 3, "node_status": "Completed"},
                        operator="Classifier",
                    ),
                ),
                _batch(
                    1,
                    ExecutionStatus.RUNNING,
                    total_docs=["d4", "d5"],
                    node_metadata=_payload(
                        {
                            "documents_in_scope": 2,
                            "node_status": "Running",
                            "classification_running": 2,
                            "classification_completed": 1,
                            "progress_percentage": "50.00%",
                        },
                        operator="Classifier",
                    ),
                ),
                # Just started (as written by start_node_execution), no progress reported yet.
                _batch(
                    2,
                    ExecutionStatus.RUNNING,
                    total_docs=["d6"],
                    node_metadata=_payload({"documents_in_scope": 1, "node_status": "Running"}, operator="Classifier"),
                ),
                # Queued batch without metadata yet.
                _batch(3, ExecutionStatus.PENDING, total_docs=["d7"]),
            ]
        )

        inner = _inner(result)
        assert inner["Documents Classified"] == "4 of 6 (more in queue)"
        assert "classification_running" not in inner
        assert "classification_completed" not in inner
        # The transient percentage string is replaced by the numeric batch progress.
        assert inner["progress_percentage"] == 25.0

    def test_no_documents_to_classify_gives_no_field(self):
        """A classification node with a zero total gets no Documents Classified field."""
        result = _aggregate(
            [
                _batch(
                    0,
                    ExecutionStatus.RUNNING,
                    node_metadata=_payload(
                        {"documents_in_scope": 0, "classification_running": 0, "classification_completed": 0},
                        operator="Classifier",
                    ),
                ),
            ]
        )

        inner = _inner(result)
        assert "Documents Classified" not in inner
        assert "classification_running" not in inner
