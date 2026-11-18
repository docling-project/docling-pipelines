"""
JobStats - Job-level statistics domain model.

This model is used within the core logic and storage layers.
It is a simplified version of JobStats, without API-specific metadata.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from docpipe.core.constants.constants import ExecutionStatus

if TYPE_CHECKING:
    from .node_stats import NodeStats


class JobStats(BaseModel):
    """
    Job-level statistics domain model.
    """

    # Core Identity & Status (Required)
    job_id: str
    job_run_id: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    message: str = ""

    # Timing Fields
    start_time: int = 0
    end_time: int = 0
    duration: int = 0
    heartbeat_timestamp: int | None = 0
    heartbeat_failure_count: int = 0
    progress_timestamp: int = 0

    # Document Counts
    total_docs: int = 0
    processed_docs: int = 0
    completed_docs: int = 0
    failed_docs: int = 0
    skipped_docs: int = 0
    deleted_doc_count: int = 0

    # Page Processing Stats
    total_pages_processed: int = 0
    page_type_stats: dict[str, int] | None = None
    execution_time: int | None = None

    # Execution Context
    orchestrator: str = "Python"
    container_kind: str | None = None
    container_id: str | None = ""
    flow_id: str | None = ""
    flow_name: str | None = None

    # User & Account Context
    user_id: str | None = None
    account_id: str | None = None
    user_entitlements: dict[str, Any] | None = Field(default_factory=dict)

    # Report Generation Status
    report_status: str | None = None  # "GENERATING", "COMPLETED", "FAILED"
    report_generation_started_at: int | None = None
    report_generation_completed_at: int | None = None

    # Nested Statistics (Populated by aggregation)
    node_stats: dict[str, NodeStats] = Field(default_factory=dict)
    batch_node_stats: dict[str, dict[str, NodeStats]] = Field(default_factory=dict)
