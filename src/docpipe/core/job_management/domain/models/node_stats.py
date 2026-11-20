# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
NodeStats - Node-level statistics domain model.

This model is used within the core logic and storage layers.
It is a simplified version of NodeStats, without API-specific metadata.
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator

from docpipe.core.constants.constants import ExecutionStatus


class NodeStatsFields:
    """Field names for NodeStats domain model and database columns."""

    NODE_ID = "node_id"  # DB column name — keep as "node_id"
    JOB_RUN_ID = "job_run_id"
    NAME = "name"
    NODE_STATUS = "node_status"
    ERROR = "error"
    START_TIME = "start_time"
    END_TIME = "end_time"
    TIME_TAKEN = "time_taken"
    COL_NAMES = "col_names"
    TOTAL_DOCS = "total_docs"
    FAILED_DOCS = "failed_docs"
    SKIPPED_DOCS = "skipped_docs"
    DEFERRED_EXECUTION_DOCS = "deferred_execution_docs"
    DOCS_COMPLETED = "docs_completed"
    DOCS_COMPLETED_COUNT = "docs_completed_count"
    BATCH_ID = "batch_id"
    BATCH_NUM = "batch_num"
    NODE_METADATA = "node_metadata"


class NodeMetadataItem(BaseModel):
    """
    Node metadata item with proper nested structure.
    """

    id: str
    operator: str
    node_metadata: dict[str, Any] | None = None


class NodeStats(BaseModel):
    """
    Node-level statistics domain model.
    """

    # Identity Fields
    id: str
    name: str

    # Status & Error
    node_status: str = ExecutionStatus.PENDING.value
    error: str = ""

    # Timing Fields
    start_time: int = 0
    end_time: int = 0
    time_taken: int = 0

    # Schema Information
    col_names: list[str] = Field(default_factory=list)

    # Document Tracking (Lists of document IDs)
    total_docs: list[str] = Field(default_factory=list)
    failed_docs: list[str] = Field(default_factory=list)
    skipped_docs: list[str] = Field(default_factory=list)
    # Documents scheduled for resumption at a downstream node (counted in scope, not yet processed)
    deferred_execution_docs: list[str] = Field(default_factory=list)
    docs_completed: list[str] = Field(default_factory=list)
    docs_completed_count: int = 0

    # Operator Metadata (Custom per operator)
    node_metadata: dict[str, Any] | None = None

    # Batch Processing Fields (Micro-batching)
    batch_id: str | None = None
    batch_num: int | None = None

    @field_validator("deferred_execution_docs", mode="before")
    @classmethod
    def _none_to_empty_list(cls, value: Any) -> Any:
        """Rows written before this field existed come back as NULL; treat them as an empty list."""
        return [] if value is None else value
