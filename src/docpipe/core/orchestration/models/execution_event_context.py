"""Lifecycle execution event contexts passed to ExecutionLifecycleObserverPort."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pyarrow as pa


@dataclass
class NodeTableSummary:
    """Lightweight snapshot of a PyArrow table's schema and size.

    Replaces passing full ``pa.Table`` objects through context objects so
    live Arrow data is not held in memory after an operator finishes.
    """

    schema_fields: list[tuple[str, str]]  # [(col_name, col_type), ...]
    row_count: int

    @classmethod
    def from_table(cls, table: pa.Table) -> "NodeTableSummary":
        """Build a summary from a live PyArrow table."""
        return cls(
            schema_fields=[(f.name, str(f.type)) for f in table.schema],
            row_count=table.num_rows,
        )


@dataclass
class SinkDatasetInfo:
    """External sink dataset written during a flow, with a summary of what was written to it.

    One entry exists per distinct ``(namespace, name)``. When a sink runs once per micro-batch,
    ``summary.row_count`` is the total across batches.
    """

    namespace: str
    name: str
    summary: NodeTableSummary


@dataclass
class FlowStartContext:
    """Context delivered when flow execution is starting."""

    flow_id: str
    flow_name: str
    job_run_id: str
    flow_def: dict[str, Any]
    operator_names: list[str] = field(default_factory=list)
    start_time: datetime | str | None = None


@dataclass
class FlowRunningContext:
    """Context delivered when the ingest stage completes and active processing begins."""

    flow_id: str
    flow_name: str
    job_run_id: str
    ingested_table: pa.Table | None = None
    ingest_node_id: str | None = None
    ingest_source_name: str | None = None
    ingest_source_namespace: str | None = None
    progress: dict[str, Any] = field(default_factory=dict)
    event_time: datetime | str | None = None


@dataclass
class FlowCompleteContext:
    """Context delivered when flow execution completes."""

    flow_id: str
    flow_name: str
    job_run_id: str
    flow_def: dict[str, Any]
    status: str = "Completed"
    output_tables: list[pa.Table] = field(default_factory=list)
    output_metadata: dict[str, Any] = field(default_factory=dict)
    ingest_dataset_name: str | None = None
    sink_datasets: list[SinkDatasetInfo] = field(default_factory=list)
    completed_docs: int = 0
    failed_docs: int = 0
    skipped_docs: int = 0
    total_docs: int = 0
    start_time: datetime | str | None = None
    end_time: datetime | str | None = None


@dataclass
class FlowFailContext:
    """Context delivered when flow execution fails."""

    flow_id: str
    flow_name: str
    job_run_id: str
    error_message: str
    exception: Exception | None = None
    flow_def: dict[str, Any] = field(default_factory=dict)
    status: str = "Failed"
    start_time: datetime | str | None = None
    end_time: datetime | str | None = None


@dataclass
class FlowAbortContext:
    """Context delivered when flow execution is aborted/cancelled."""

    flow_id: str
    flow_name: str
    job_run_id: str
    reason: str | None = None
    flow_def: dict[str, Any] = field(default_factory=dict)
    status: str = "Canceled"
    start_time: datetime | str | None = None
    end_time: datetime | str | None = None


@dataclass
class NodeStartContext:
    """Context delivered when a DAG node step begins execution."""

    flow_id: str
    flow_name: str
    job_run_id: str
    node_id: str
    node_name: str
    operator_type: str
    operator_category: str | None = None
    input_summary: NodeTableSummary | None = None
    predecessor_node_ids: list[str] = field(default_factory=list)
    parent_run_id: str | None = None
    start_time: datetime | str | None = None
    ingest_source_dataset_name: str | None = None
    ingest_source_dataset_namespace: str | None = None


@dataclass
class NodeCompleteContext:
    """Context delivered when a DAG node step finishes execution."""

    flow_id: str
    flow_name: str
    job_run_id: str
    node_id: str
    node_name: str
    operator_type: str
    operator_category: str | None = None
    output_summaries: list[NodeTableSummary] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    predecessor_node_ids: list[str] = field(default_factory=list)
    sink_dataset_namespace: str | None = None
    sink_dataset_name: str | None = None
    has_downstream: bool = False
    start_time: datetime | str | None = None
    end_time: datetime | str | None = None
    batch_id: str | None = None
    batch_num: int | None = None


@dataclass
class NodeFailContext:
    """Context delivered when a DAG node step execution fails."""

    flow_id: str
    flow_name: str
    job_run_id: str
    node_id: str
    node_name: str
    operator_type: str
    error_message: str
    exception: Exception | None = None
    input_summary: NodeTableSummary | None = None
    predecessor_node_ids: list[str] = field(default_factory=list)
    start_time: datetime | str | None = None
    end_time: datetime | str | None = None


@dataclass
class NodeSkipContext:
    """Context delivered when a DAG node step is skipped."""

    flow_id: str
    flow_name: str
    job_run_id: str
    node_id: str
    node_name: str
    operator_type: str
    reason: str
    operator_category: str | None = None
    start_time: datetime | str | None = None
    end_time: datetime | str | None = None
