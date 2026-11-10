"""
Batch aggregation logic for node statistics.
This is the single source of truth for batch aggregation.
"""

from dataclasses import dataclass
from typing import Any

from docpipe.core.constants.constants import ExecutionStatus, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.job_management.domain.models import NodeStats

from .aggregator import MetadataAggregator


@dataclass
class DocumentStats:
    """Document-level statistics."""

    total_expected: int
    completed: int
    processed: int


@dataclass
class BatchProgress:
    """Batch progress information."""

    finished: int
    total: int
    has_pending: bool
    status_counts: dict[str, int]


@dataclass
class ExtractionInfo:
    """Extraction operator information."""

    total: int
    completed: int
    is_extraction_operator: bool
    weighted_progress: float = 0.0
    stage_progress: dict[str, Any] | None = None


@dataclass
class ClassificationInfo:
    """Classification operator information."""

    total: int
    completed: int
    is_classification_operator: bool


def _get_empty_node_stats(*, node_id: str) -> NodeStats:
    """Returns empty aggregated stats for a node with no batches."""
    return NodeStats(
        id=node_id,
        name="Unknown",
        start_time=0,
        end_time=0,
        node_status=ExecutionStatus.PENDING.value,
        time_taken=0,
        col_names=[],
        total_docs=[],
        failed_docs=[],
        skipped_docs=[],
        docs_completed=[],
        docs_completed_count=0,
        node_metadata={},
        error="",
    )


def count_batches_by_status(*, batch_records: list[NodeStats]) -> dict[str, int]:
    """Counts batches by their status."""
    status_counts = {
        ExecutionStatus.RUNNING.value: 0,
        ExecutionStatus.QUEUED.value: 0,
        ExecutionStatus.CANCELING.value: 0,
        ExecutionStatus.CANCELED.value: 0,
        ExecutionStatus.FAILED.value: 0,
        ExecutionStatus.COMPLETED_WITH_ERRORS.value: 0,
        ExecutionStatus.COMPLETED_WITH_WARNINGS.value: 0,
        ExecutionStatus.COMPLETED.value: 0,
        ExecutionStatus.SKIPPED.value: 0,
        ExecutionStatus.PENDING.value: 0,
    }

    for record in batch_records:
        node_status = record.node_status
        if node_status in status_counts:
            status_counts[node_status] += 1

    return status_counts


def _determine_aggregated_status(*, status_counts: dict[str, int], total_batches: int) -> str:
    """Determines the aggregated node status based on batch status counts."""
    active_states = (
        status_counts[ExecutionStatus.RUNNING.value]
        + status_counts[ExecutionStatus.QUEUED.value]
        + status_counts[ExecutionStatus.PENDING.value]
        + status_counts[ExecutionStatus.CANCELING.value]
    )

    if active_states > 0:
        return ExecutionStatus.RUNNING.value

    if status_counts[ExecutionStatus.CANCELED.value] == total_batches:
        return ExecutionStatus.CANCELED.value

    if status_counts[ExecutionStatus.FAILED.value] == total_batches:
        return ExecutionStatus.FAILED.value

    if status_counts[ExecutionStatus.SKIPPED.value] == total_batches:
        return ExecutionStatus.SKIPPED.value

    canceled = status_counts[ExecutionStatus.CANCELED.value]
    skipped = status_counts[ExecutionStatus.SKIPPED.value]
    failed = status_counts[ExecutionStatus.FAILED.value]

    if canceled > 0:
        has_completed_variants = (
            status_counts[ExecutionStatus.COMPLETED.value]
            + status_counts[ExecutionStatus.COMPLETED_WITH_WARNINGS.value]
            + status_counts[ExecutionStatus.COMPLETED_WITH_ERRORS.value]
        ) > 0

        # Canceled + Skipped only → Skipped (nothing actually executed)
        if (canceled + skipped) == total_batches:
            return ExecutionStatus.SKIPPED.value

        # Canceled + any Completed variant (±Skipped) → CompletedWithWarnings
        if has_completed_variants:
            return ExecutionStatus.COMPLETED_WITH_WARNINGS.value

        # Only Canceled + Failed remain — no completed variants, no active states
        return ExecutionStatus.FAILED.value

    has_failures = failed > 0
    has_successes = (
        status_counts[ExecutionStatus.COMPLETED.value]
        + status_counts[ExecutionStatus.COMPLETED_WITH_WARNINGS.value]
        + status_counts[ExecutionStatus.SKIPPED.value]
    ) > 0

    if has_failures and has_successes:
        return ExecutionStatus.COMPLETED_WITH_ERRORS.value

    if status_counts[ExecutionStatus.COMPLETED_WITH_ERRORS.value] > 0:
        return ExecutionStatus.COMPLETED_WITH_ERRORS.value

    if status_counts[ExecutionStatus.COMPLETED_WITH_WARNINGS.value] > 0:
        return ExecutionStatus.COMPLETED_WITH_WARNINGS.value

    all_completed_or_skipped = (
        status_counts[ExecutionStatus.COMPLETED.value] + status_counts[ExecutionStatus.SKIPPED.value]
    ) == total_batches

    if all_completed_or_skipped:
        return ExecutionStatus.COMPLETED.value

    return ExecutionStatus.RUNNING.value


def _aggregate_time_fields(*, batch_records: list[NodeStats]) -> tuple:
    """Aggregates start time, end time, and time taken from batch records."""
    start_times = [r.start_time for r in batch_records if r.start_time > 0]
    end_times = [r.end_time for r in batch_records if r.end_time > 0]

    aggregated_start_time = min(start_times) if start_times else 0
    aggregated_end_time = max(end_times) if end_times else 0
    aggregated_time_taken = (
        aggregated_end_time - aggregated_start_time if aggregated_start_time and aggregated_end_time else 0
    )

    return aggregated_start_time, aggregated_end_time, aggregated_time_taken


def _aggregate_document_lists(*, batch_records: list[NodeStats]) -> tuple:
    """Aggregates document lists (UNION - deduplicate) from batch records."""
    all_col_names = set()
    all_total_docs = set()
    all_failed_docs = set()
    all_skipped_docs = set()
    all_docs_completed = set()

    for record in batch_records:
        if record.col_names:
            all_col_names.update(record.col_names)
        if record.total_docs:
            all_total_docs.update(record.total_docs)
        if record.failed_docs:
            all_failed_docs.update(record.failed_docs)
        if record.skipped_docs:
            all_skipped_docs.update(record.skipped_docs)
        if record.docs_completed:
            all_docs_completed.update(record.docs_completed)

    return all_col_names, all_total_docs, all_failed_docs, all_skipped_docs, all_docs_completed


def _aggregate_errors(*, batch_records: list[NodeStats]) -> str:
    """Concatenates error messages from batch records."""
    errors = [record.error for record in batch_records if record.error and record.error.strip()]
    return " | ".join(errors) if errors else ""


def _get_nested_metadata(*, record: NodeStats) -> dict[str, Any] | None:
    """Extracts nested node_metadata from a record."""
    if not record.node_metadata or not isinstance(record.node_metadata, dict):
        return None

    metadata = record.node_metadata
    if OperatorConstants.Metadata.NODE_METADATA in metadata and isinstance(
        metadata[OperatorConstants.Metadata.NODE_METADATA], dict
    ):
        metadata = metadata[OperatorConstants.Metadata.NODE_METADATA]

    return metadata


def _is_extraction_operator(*, batch_records: list[NodeStats]) -> bool:
    """Checks if this is an extraction operator by looking for extraction-specific fields."""
    for record in batch_records:
        metadata = _get_nested_metadata(record=record)
        if metadata and (
            "extraction_running" in metadata
            or "extraction_completed" in metadata
            or OperatorConstants.Metadata.EXTRACTION_STAGE_PROGRESS in metadata
        ):
            return True
    return False


def _is_classification_operator(*, batch_records: list[NodeStats]) -> bool:
    """Checks if this is a classification operator by looking for classification-specific fields."""
    for record in batch_records:
        metadata = _get_nested_metadata(record=record)
        if metadata and ("classification_running" in metadata or "classification_completed" in metadata):
            return True
    return False


def _read_stage_based_progress(*, stage_progress: dict[str, Any]) -> tuple[int, int, float]:
    """
    Read progress out of the stage-based format.

    Totals use the MAX across stages, not the sum — every stage processes the
    same documents, so summing would multiply the document count by the number
    of stages.  Completed counts ARE summed, to weight partial progress.
    """
    stage_totals: list[int] = []
    total_completed = 0
    for stage_data in stage_progress.values():
        stage_totals.append(stage_data.get(OperatorConstants.Extraction.STAGE_DOCUMENTS_TOTAL, 0))
        total_completed += stage_data.get(OperatorConstants.Extraction.STAGE_DOCUMENTS_COMPLETED, 0)

    total_running = max(stage_totals) if stage_totals else 0
    return total_running, total_completed, float(total_completed)


def _read_legacy_extraction_progress(*, metadata: dict[str, Any]) -> tuple[int, int, float]:
    """Read progress out of the legacy flat extraction_* fields."""
    total_completed = int(metadata.get("extraction_completed", 0))
    return int(metadata.get("extraction_running", 0)), total_completed, float(total_completed)


def _read_persistent_extraction_progress(*, metadata: dict[str, Any]) -> tuple[int, int, float]:
    """Fall back to the persistent doc counts, which survive on terminal batches."""
    total_running = int(metadata.get(Metrics.External.TOTAL_DOCS, 0)) if Metrics.External.TOTAL_DOCS in metadata else 0
    if Metrics.External.PROCESSED_DOCS not in metadata:
        return total_running, 0, 0.0
    total_completed = int(metadata.get(Metrics.External.PROCESSED_DOCS, 0))
    return total_running, total_completed, float(total_completed)


def _pop_transient_extraction_fields(*, metadata: dict[str, Any]) -> None:
    """Drop the in-flight progress fields so they never reach the aggregated output."""
    for key in (
        OperatorConstants.Metadata.EXTRACTION_STAGE_PROGRESS,
        "extraction_running",
        "extraction_completed",
        "progress_percentage",
    ):
        metadata.pop(key, None)


def _extract_from_single_record(*, metadata: dict[str, Any]) -> tuple[int, int, float]:
    """
    Extracts extraction progress from a single record's metadata and removes transient fields.

    Sources are tried in priority order: stage-based progress, then the legacy
    flat fields, then the persistent doc counts. Only the first two are
    transient, so only they trigger field removal.

    Returns:
        tuple: (total_documents, completed_documents, weighted_progress)
    """
    transient: tuple[int, int, float] | None = None

    # Priority 1: Stage-based progress (new format)
    if OperatorConstants.Metadata.EXTRACTION_STAGE_PROGRESS in metadata:
        stage_progress = metadata.get(OperatorConstants.Metadata.EXTRACTION_STAGE_PROGRESS, {})
        # A non-dict value here is malformed: fall through to the persistent counts
        # and leave the field in place, matching the original behaviour.
        if isinstance(stage_progress, dict):
            transient = _read_stage_based_progress(stage_progress=stage_progress)

    # Priority 2: Legacy extraction fields (backward compatibility)
    elif "extraction_running" in metadata or "extraction_completed" in metadata:
        transient = _read_legacy_extraction_progress(metadata=metadata)

    if transient is not None:
        _pop_transient_extraction_fields(metadata=metadata)
        return transient

    # Priority 3: Persistent metadata as fallback (for COMPLETED batches)
    return _read_persistent_extraction_progress(metadata=metadata)


def _extract_classification_from_single_record(*, metadata: dict[str, Any]) -> tuple:
    """Extracts classification progress from a single record's metadata and removes transient fields."""
    total_running = 0
    total_completed = 0
    has_transient = False

    # Priority 1: Transient classification fields (present during RUNNING state)
    if "classification_running" in metadata:
        total_running = int(metadata.get("classification_running", 0))
        has_transient = True

    if "classification_completed" in metadata:
        total_completed = int(metadata.get("classification_completed", 0))
        has_transient = True

    # Remove transient fields after reading them
    # These fields should not appear in the final aggregated metadata
    if has_transient:
        metadata.pop("classification_running", None)
        metadata.pop("classification_completed", None)
        metadata.pop("progress_percentage", None)

    # Priority 2: Persistent metadata as fallback (for COMPLETED batches)
    if not has_transient:
        if Metrics.External.TOTAL_DOCS in metadata:
            total_running = int(metadata.get(Metrics.External.TOTAL_DOCS, 0))
        if Metrics.External.PROCESSED_DOCS in metadata:
            total_completed = int(metadata.get(Metrics.External.PROCESSED_DOCS, 0))

    return total_running, total_completed


def _get_extraction_progress(*, batch_records: list[NodeStats]) -> ExtractionInfo:
    """
    Extracts extraction progress from batch records if this is an extraction operator.

    ONLY extracts if extraction-specific fields are present (i.e., this is an extraction operator).
    Returns ExtractionInfo with stage_progress included.
    """
    # Check if this is an extraction operator FIRST
    if not _is_extraction_operator(batch_records=batch_records):
        return ExtractionInfo(
            total=0, completed=0, is_extraction_operator=False, weighted_progress=0.0, stage_progress=None
        )

    # Aggregate stage progress FIRST before transient fields are removed
    stage_progress = _aggregate_extraction_stage_progress(batch_records=batch_records)

    # Extract and sum values from all records (this removes transient fields)
    extraction_total = 0
    extraction_completed = 0
    weighted_progress_sum = 0.0

    for record in batch_records:
        metadata = _get_nested_metadata(record=record)
        if metadata:
            total, completed, weighted = _extract_from_single_record(metadata=metadata)
            extraction_total += total
            extraction_completed += completed
            weighted_progress_sum += weighted

    return ExtractionInfo(
        total=extraction_total,
        completed=extraction_completed,
        is_extraction_operator=True,
        weighted_progress=weighted_progress_sum,
        stage_progress=stage_progress if stage_progress else None,
    )


def _get_classification_progress(*, batch_records: list[NodeStats]) -> ClassificationInfo:
    """
    Extracts classification progress from batch records if this is a classification operator.

    ONLY extracts if classification-specific fields are present (i.e., this is a classification operator).
    Returns ClassificationInfo with zeros for non-classification operators.
    """
    # Check if this is a classification operator FIRST
    if not _is_classification_operator(batch_records=batch_records):
        return ClassificationInfo(total=0, completed=0, is_classification_operator=False)

    # Extract and sum values from all records
    classification_total = 0
    classification_completed = 0

    for record in batch_records:
        metadata = _get_nested_metadata(record=record)
        if metadata:
            running, completed = _extract_classification_from_single_record(metadata=metadata)
            classification_total += running
            classification_completed += completed

    return ClassificationInfo(
        total=classification_total, completed=classification_completed, is_classification_operator=True
    )


def _make_empty_stage_entry() -> dict[str, Any]:
    """Return a zeroed-out stage aggregate bucket."""
    return {
        OperatorConstants.Extraction.STAGE_DOCUMENTS_TOTAL: 0,
        OperatorConstants.Extraction.STAGE_DOCUMENTS_COMPLETED: 0,
        OperatorConstants.Extraction.STAGE_DOCUMENTS_FAILED: 0,
        "statuses": [],
    }


def _merge_stage_data_into_aggregates(
    *,
    stage_aggregates: dict[str, dict[str, Any]],
    stage_name: str,
    stage_data: dict[str, Any],
) -> None:
    """Merge one stage_data entry from a running batch into the running stage_aggregates dict."""
    if stage_name not in stage_aggregates:
        stage_aggregates[stage_name] = _make_empty_stage_entry()
    agg = stage_aggregates[stage_name]
    agg[OperatorConstants.Extraction.STAGE_DOCUMENTS_TOTAL] += stage_data.get(
        OperatorConstants.Extraction.STAGE_DOCUMENTS_TOTAL, 0
    )
    agg[OperatorConstants.Extraction.STAGE_DOCUMENTS_COMPLETED] += stage_data.get(
        OperatorConstants.Extraction.STAGE_DOCUMENTS_COMPLETED, 0
    )
    agg[OperatorConstants.Extraction.STAGE_DOCUMENTS_FAILED] += stage_data.get(
        OperatorConstants.Extraction.STAGE_DOCUMENTS_FAILED, 0
    )
    agg["statuses"].append(
        stage_data.get(OperatorConstants.Extraction.STAGE_STATUS, OperatorConstants.Extraction.STAGE_STATUS_PENDING)
    )


def _collect_stage_progress_from_running_batches(
    *, batch_records: list[NodeStats], stage_aggregates: dict[str, dict[str, Any]]
) -> None:
    """
    Scan running batches that carry fine-grained per-stage metadata
    (``extraction_stage_progress``) and merge each stage's numbers into
    ``stage_aggregates``.  This pass runs first so that all active stage
    names are discovered before terminal batches are processed.
    """
    for record in batch_records:
        metadata = _get_nested_metadata(record=record)
        if not metadata:
            continue
        stage_progress = metadata.get(OperatorConstants.Metadata.EXTRACTION_STAGE_PROGRESS, {})
        if not (isinstance(stage_progress, dict) and stage_progress):
            continue
        for stage_name, stage_data in stage_progress.items():
            _merge_stage_data_into_aggregates(
                stage_aggregates=stage_aggregates,
                stage_name=stage_name,
                stage_data=stage_data,
            )


_TERMINAL_BATCH_STATUSES = frozenset(
    {
        ExecutionStatus.COMPLETED.value,
        ExecutionStatus.COMPLETED_WITH_ERRORS.value,
        ExecutionStatus.COMPLETED_WITH_WARNINGS.value,
        ExecutionStatus.FAILED.value,
    }
)


def _add_batch_totals_to_stages(
    *,
    stage_aggregates: dict[str, dict[str, Any]],
    total_docs: int,
    processed_docs: int,
    status_label: str,
) -> None:
    """
    Add one finished batch's document counts to every active stage.

    ``text_extraction`` always gets the counts.  ``entity_extraction`` only
    gets them if a running batch already reported it, which means entity
    extraction is actually enabled for this operator.
    """
    stages_to_update = ["text_extraction"]
    if "entity_extraction" in stage_aggregates:
        stages_to_update.append("entity_extraction")
    for stage_name in stages_to_update:
        agg = stage_aggregates.setdefault(stage_name, _make_empty_stage_entry())
        agg[OperatorConstants.Extraction.STAGE_DOCUMENTS_TOTAL] += total_docs
        agg[OperatorConstants.Extraction.STAGE_DOCUMENTS_COMPLETED] += processed_docs
        agg["statuses"].append(status_label)


def _backfill_stage_totals_from_terminal_batches(
    *, batch_records: list[NodeStats], stage_aggregates: dict[str, dict[str, Any]]
) -> None:
    """
    For batches that have already finished (completed, completed-with-errors,
    completed-with-warnings, or failed), the fine-grained stage metadata is
    gone.  Back-fill each active stage with the persistent ``total_docs`` /
    ``processed_docs`` counts so that the aggregated totals stay accurate.

    Which stages get the counts is decided by :func:`_add_batch_totals_to_stages`,
    based on what :func:`_collect_stage_progress_from_running_batches` discovered.
    """
    for record in batch_records:
        if record.node_status not in _TERMINAL_BATCH_STATUSES:
            continue
        metadata = _get_nested_metadata(record=record)
        if not metadata:
            continue
        total_docs = metadata.get(Metrics.External.TOTAL_DOCS, 0)
        if total_docs <= 0:
            continue
        _add_batch_totals_to_stages(
            stage_aggregates=stage_aggregates,
            total_docs=total_docs,
            processed_docs=metadata.get(Metrics.External.PROCESSED_DOCS, 0),
            status_label=(
                OperatorConstants.Extraction.STAGE_STATUS_FAILED
                if record.node_status == ExecutionStatus.FAILED.value
                else OperatorConstants.Extraction.STAGE_STATUS_COMPLETED
            ),
        )


def _collect_stage_totals_from_legacy_running_batches(
    *, batch_records: list[NodeStats], stage_aggregates: dict[str, dict[str, Any]]
) -> None:
    """
    Handle running batches that started execution but have not yet emitted
    per-stage metadata (``extraction_stage_progress`` is absent).  These
    batches only expose a top-level ``total_docs`` field.  We record the
    document count under ``text_extraction`` so that progress reporting
    shows the correct denominator even before stage detail is available.
    """
    for record in batch_records:
        if record.node_status != ExecutionStatus.RUNNING.value:
            continue
        metadata = _get_nested_metadata(record=record)
        if not metadata:
            continue
        # Skip if this batch already reported per-stage detail (handled above)
        stage_progress = metadata.get(OperatorConstants.Metadata.EXTRACTION_STAGE_PROGRESS, {})
        if isinstance(stage_progress, dict) and stage_progress:
            continue
        total_docs = metadata.get("total_docs", 0)
        if total_docs <= 0:
            continue
        stage_name = "text_extraction"
        if stage_name not in stage_aggregates:
            stage_aggregates[stage_name] = _make_empty_stage_entry()
        stage_aggregates[stage_name][OperatorConstants.Extraction.STAGE_DOCUMENTS_TOTAL] += total_docs
        # Completed count is intentionally omitted — progress detail is not yet available
        stage_aggregates[stage_name]["statuses"].append(OperatorConstants.Extraction.STAGE_STATUS_RUNNING)


def _resolve_stage_status(*, statuses: list[str]) -> str:
    """
    Roll up a list of per-batch stage statuses into a single status.
    Priority order: running > failed > completed > pending.
    """
    if OperatorConstants.Extraction.STAGE_STATUS_RUNNING in statuses:
        return OperatorConstants.Extraction.STAGE_STATUS_RUNNING
    if OperatorConstants.Extraction.STAGE_STATUS_FAILED in statuses:
        return OperatorConstants.Extraction.STAGE_STATUS_FAILED
    if all(s == OperatorConstants.Extraction.STAGE_STATUS_COMPLETED for s in statuses):
        return OperatorConstants.Extraction.STAGE_STATUS_COMPLETED
    return OperatorConstants.Extraction.STAGE_STATUS_PENDING


def _aggregate_extraction_stage_progress(*, batch_records: list[NodeStats]) -> dict[str, Any]:
    """
    Aggregates per-stage extraction progress across all batches.

    Handles both:
    - Running batches: Have transient extraction_stage_progress metadata
    - Completed batches: Have persistent documents_in_scope/processed_docs metadata

    Returns dict with structure:
    {
        "text_extraction": {
            "status": "running",
            "documents_total": 100,
            "documents_completed": 86,
            "documents_failed": 0,
            "progress_percentage": 86.0
        },
        "entity_extraction": { ... }
    }
    """
    stage_aggregates: dict[str, dict[str, Any]] = {}

    # Step 1: collect fine-grained stage data from running batches (discovers all active stages)
    _collect_stage_progress_from_running_batches(batch_records=batch_records, stage_aggregates=stage_aggregates)
    # Step 2: back-fill totals for batches that already finished
    _backfill_stage_totals_from_terminal_batches(batch_records=batch_records, stage_aggregates=stage_aggregates)
    # Step 3: handle running batches that haven't emitted per-stage detail yet
    _collect_stage_totals_from_legacy_running_batches(batch_records=batch_records, stage_aggregates=stage_aggregates)

    result: dict[str, Any] = {}
    for stage_name, agg in stage_aggregates.items():
        total = agg[OperatorConstants.Extraction.STAGE_DOCUMENTS_TOTAL]
        completed = agg[OperatorConstants.Extraction.STAGE_DOCUMENTS_COMPLETED]
        status = _resolve_stage_status(statuses=agg["statuses"])
        result[stage_name] = {
            OperatorConstants.Extraction.STAGE_STATUS: status,
            OperatorConstants.Extraction.STAGE_DOCUMENTS_TOTAL: total,
            OperatorConstants.Extraction.STAGE_DOCUMENTS_COMPLETED: completed,
            OperatorConstants.Extraction.STAGE_DOCUMENTS_FAILED: agg[
                OperatorConstants.Extraction.STAGE_DOCUMENTS_FAILED
            ],
            OperatorConstants.Extraction.STAGE_PROGRESS_PERCENTAGE: round(completed / total * 100, 2)
            if total > 0
            else 0.0,
        }

    return result


def calculate_finished_batches(*, status_counts: dict[str, int]) -> int:
    """
    Calculates the number of finished batches.

    Finished = completed + failed + skipped + completed_with_warnings + completed_with_errors
    Excludes: running, pending, queued
    """
    return (
        status_counts[ExecutionStatus.COMPLETED.value]
        + status_counts[ExecutionStatus.SKIPPED.value]
        + status_counts[ExecutionStatus.COMPLETED_WITH_WARNINGS.value]
        + status_counts[ExecutionStatus.COMPLETED_WITH_ERRORS.value]
        + status_counts[ExecutionStatus.FAILED.value]
    )


def _add_progress_field(
    *, metadata: dict[str, Any], finished_batches: int, total_batches: int, status_counts: dict[str, int]
) -> None:
    """
    Adds batch-based Progress field to metadata with status breakdown.

    Format: "X of Y batches (Z%) | Completed: A, Running: B, Failed: C, Skipped: D"
    Only shows non-zero statuses (except Completed which is always shown).

    Note: COMPLETED_WITH_ERRORS and COMPLETED_WITH_WARNINGS are counted as "Completed".
    """
    if total_batches > 0:
        pct = round((finished_batches / total_batches) * 100, 2)
        base_progress = f"{finished_batches} of {total_batches} batches ({pct}%)"

        # Build status breakdown - only show non-zero counts
        status_parts = []

        # Completed count includes COMPLETED, COMPLETED_WITH_ERRORS, and COMPLETED_WITH_WARNINGS
        completed = (
            status_counts.get(ExecutionStatus.COMPLETED.value, 0)
            + status_counts.get(ExecutionStatus.COMPLETED_WITH_ERRORS.value, 0)
            + status_counts.get(ExecutionStatus.COMPLETED_WITH_WARNINGS.value, 0)
        )
        status_parts.append(f"Completed: {completed}")

        # Show Running if non-zero
        running = status_counts.get(ExecutionStatus.RUNNING.value, 0)
        if running > 0:
            status_parts.append(f"Running: {running}")

        # Show Failed if non-zero (only FAILED status, not CompletedWithErrors)
        failed = status_counts.get(ExecutionStatus.FAILED.value, 0)
        if failed > 0:
            status_parts.append(f"Failed: {failed}")

        # Show Skipped if non-zero
        skipped = status_counts.get(ExecutionStatus.SKIPPED.value, 0)
        if skipped > 0:
            status_parts.append(f"Skipped: {skipped}")

        # Combine base progress with status breakdown
        metadata[OperatorConstants.Metadata.FIELD_PROGRESS] = f"{base_progress} | {', '.join(status_parts)}"

        # Numeric progress percentage for programmatic UI consumption (float, 0-100)
        metadata[OperatorConstants.Metadata.PROGRESS_PERCENTAGE] = pct


def _add_extraction_stage_fields(
    *, metadata: dict[str, Any], extraction_info: ExtractionInfo, has_pending_batches: bool
) -> None:
    """Adds per-stage extraction fields for extraction operators."""
    if not extraction_info.stage_progress:
        return

    for stage_name, stage_data in extraction_info.stage_progress.items():
        total = stage_data.get("documents_total", 0)
        completed = stage_data.get("documents_completed", 0)

        if total > 0:
            # Determine field name based on stage
            if stage_name == "text_extraction":
                field_name = OperatorConstants.Metadata.FIELD_TEXT_EXTRACTED
            elif stage_name == "entity_extraction":
                field_name = OperatorConstants.Metadata.FIELD_ENTITIES_EXTRACTED
            else:
                # For any other stages, use a generic format
                field_name = stage_name.replace("_", " ").title()

            if has_pending_batches:
                # Batches still pending - show "(more in queue)" message
                metadata[field_name] = f"{completed} of {total} (more in queue)"
            else:
                # All batches started - show percentage
                pct = round((completed / total * 100), 2)
                metadata[field_name] = f"{completed} of {total} ({pct}%)"


def _add_classification_field(
    *, metadata: dict[str, Any], classification_info: ClassificationInfo, has_pending_batches: bool
) -> None:
    """Adds Documents Classified field for classification operators."""
    if classification_info.total > 0:
        if has_pending_batches:
            # Batches still pending - show "(more in queue)" message
            metadata[OperatorConstants.Metadata.FIELD_DOCS_CLASSIFIED] = (
                f"{classification_info.completed} of {classification_info.total} (more in queue)"
            )
        else:
            # All batches started - show percentage
            classification_pct = round((classification_info.completed / classification_info.total * 100), 2)
            metadata[OperatorConstants.Metadata.FIELD_DOCS_CLASSIFIED] = (
                f"{classification_info.completed} of {classification_info.total} ({classification_pct}%)"
            )


def _inject_metadata_fields(
    *,
    aggregated_metadata: dict[str, Any],
    aggregated_status: str,
    doc_stats: DocumentStats,
    batch_progress: BatchProgress,
    extraction_info: ExtractionInfo,
    classification_info: ClassificationInfo,
) -> None:
    """
    Injects progress and metadata fields into aggregated metadata.

    Uses data classes to group related parameters and reduce parameter count.
    """
    metadata = aggregated_metadata.setdefault(OperatorConstants.Metadata.NODE_METADATA, {})

    # Core document fields
    metadata[Metrics.External.TOTAL_DOCS] = doc_stats.total_expected
    metadata[Metrics.External.COMPLETED_DOCS_COUNT] = doc_stats.completed
    metadata[Metrics.External.PROCESSED_DOCS] = doc_stats.processed
    metadata[Metrics.External.NODE_STATUS] = aggregated_status

    # Add batch-based Progress field
    _add_progress_field(
        metadata=metadata,
        finished_batches=batch_progress.finished,
        total_batches=batch_progress.total,
        status_counts=batch_progress.status_counts,
    )

    # Add per-stage extraction fields for extraction operators
    if extraction_info.is_extraction_operator:
        _add_extraction_stage_fields(
            metadata=metadata, extraction_info=extraction_info, has_pending_batches=batch_progress.has_pending
        )

    # Add Documents Classified field for classification operators
    if classification_info.is_classification_operator:
        _add_classification_field(
            metadata=metadata,
            classification_info=classification_info,
            has_pending_batches=batch_progress.has_pending,
        )


def aggregate_batch_node_stats(
    *,
    node_id: str,
    batch_records: list[NodeStats],
    aggregator: MetadataAggregator,
) -> NodeStats:
    """
    Aggregates batch-level node statistics using ONLY node_stats table.

    Uses node_status field from node_stats to determine batch status and calculate progress.
    Pending/Queued batches are identified by node_status in node_stats records.
    Failed batches are considered as completed for progress calculation.

    Args:
        node_id: The node identifier
        batch_records: List of NodeStats records for this node from database
        aggregator: MetadataAggregator instance for intelligent field aggregation

    Returns:
        Dictionary with aggregated node statistics
    """
    total_batches = len(batch_records)

    if total_batches == 0:
        return _get_empty_node_stats(node_id=node_id)

    # Extract extraction and classification progress FIRST (for extraction/classification operators)
    # This must be done BEFORE metadata aggregation to remove transient fields
    extraction_info = _get_extraction_progress(batch_records=batch_records)
    classification_info = _get_classification_progress(batch_records=batch_records)

    # Aggregate status
    status_counts = count_batches_by_status(batch_records=batch_records)
    aggregated_status = _determine_aggregated_status(status_counts=status_counts, total_batches=total_batches)

    # Aggregate time fields
    aggregated_start_time, aggregated_end_time, aggregated_time_taken = _aggregate_time_fields(
        batch_records=batch_records
    )

    # Aggregate document lists
    all_col_names, all_total_docs, all_failed_docs, all_skipped_docs, all_docs_completed = _aggregate_document_lists(
        batch_records=batch_records
    )

    # Aggregate errors
    aggregated_error = _aggregate_errors(batch_records=batch_records)

    # Aggregate metadata using enterprise-compatible aggregator
    metadata_list = [record.node_metadata for record in batch_records if record.node_metadata]
    aggregated_metadata = aggregator.aggregate_metadata(metadata_list=metadata_list) if metadata_list else {}

    # Calculate statistics
    # Processed docs: sum of completed, failed, and skipped documents for the processed batches
    processed_docs = len(all_docs_completed) + len(all_failed_docs) + len(all_skipped_docs)
    # Completed docs: only successfully completed documents
    completed_docs_count = len(all_docs_completed)
    total_expected_docs = len(all_total_docs)

    # Check if there are pending batches
    has_pending_batches = (
        status_counts.get(ExecutionStatus.PENDING.value, 0) + status_counts.get(ExecutionStatus.QUEUED.value, 0)
    ) > 0

    # Calculate finished batches for progress
    finished_batches = calculate_finished_batches(status_counts=status_counts)

    # Create data class instances for cleaner parameter passing
    doc_stats = DocumentStats(
        total_expected=total_expected_docs, completed=completed_docs_count, processed=processed_docs
    )

    batch_progress = BatchProgress(
        finished=finished_batches, total=total_batches, has_pending=has_pending_batches, status_counts=status_counts
    )

    # Inject metadata fields using structured data
    _inject_metadata_fields(
        aggregated_metadata=aggregated_metadata,
        aggregated_status=aggregated_status,
        doc_stats=doc_stats,
        batch_progress=batch_progress,
        extraction_info=extraction_info,
        classification_info=classification_info,
    )

    node_name = batch_records[0].name

    return NodeStats(
        id=node_id,
        name=node_name,
        start_time=aggregated_start_time,
        end_time=aggregated_end_time,
        node_status=aggregated_status,
        time_taken=aggregated_time_taken,
        col_names=sorted(all_col_names),
        total_docs=sorted(all_total_docs),
        failed_docs=sorted(all_failed_docs),
        skipped_docs=sorted(all_skipped_docs),
        docs_completed=sorted(all_docs_completed),
        docs_completed_count=len(all_docs_completed),
        node_metadata=aggregated_metadata,
        error=aggregated_error,
    )
