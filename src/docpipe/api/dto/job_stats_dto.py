"""
JobStatsDto - Job-level statistics model (enterprise-compatible)

Complete implementation with 27 fields as per specification.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from docpipe.api.dto.field_definitions import (
    ACCOUNT_ID_DESC,
    ACCOUNT_ID_MAX_LENGTH,
    ACCOUNT_ID_MIN_LENGTH,
    BATCH_NODE_STATS_DESC,
    COMPLETED_DOCS_DESC,
    CONTAINER_ID_DESC_JOB,
    CONTAINER_KIND_MAX_LENGTH,
    CONTAINER_KIND_MIN_LENGTH,
    CONTAINER_TYPE_DESC,
    DELETED_DOCS_DESC,
    DOCS_COUNT_MAX,
    DOCS_COUNT_MIN,
    DURATION_DESC,
    DURATION_MAX_SECONDS,
    DURATION_MIN,
    END_TIME_DESC,
    EXECUTION_TIME_DESC,
    EXECUTION_TIME_MAX,
    EXECUTION_TIME_MIN,
    FAILED_DOCS_DESC,
    FLOW_ID_DESC_JOB,
    FLOW_NAME_DESC_JOB,
    HEARTBEAT_DESC,
    JOB_ID_DESC,
    JOB_RUN_ID_DESC,
    JOB_STATUS_DESC,
    MESSAGE_DESC,
    MESSAGE_MAX_LENGTH,
    MESSAGE_MIN_LENGTH,
    MESSAGE_PATTERN,
    NAME_MAX_LENGTH,
    NODE_STATS_DESC,
    ORCHESTRATOR_DESC,
    ORCHESTRATOR_MAX_LENGTH,
    ORCHESTRATOR_MIN_LENGTH,
    ORCHESTRATOR_PATTERN,
    PAGE_TYPE_STATS_DESC,
    PAGES_COUNT_MAX,
    PAGES_COUNT_MIN,
    PROCESSED_DOCS_DESC,
    PROGRESS_TIMESTAMP_DESC,
    SKIPPED_DOCS_DESC,
    START_TIME_DESC,
    TIMESTAMP_MAX,
    TIMESTAMP_MIN,
    TOTAL_DOCS_DESC,
    TOTAL_PAGES_DESC,
    USER_ENTITLEMENTS_DESC,
    USER_ID_DESC,
    USER_ID_MAX_LENGTH,
    USER_ID_MIN_LENGTH,
    USER_ID_PATTERN,
    UUID_LENGTH,
    UUID_PATTERN,
)
from docpipe.core.constants.constants import ExecutionStatus

from .node_stats_dto import NodeStatsDto


class JobStatsDto(BaseModel):
    """
    Job-level statistics
    """

    # Core Identity & Status (Required)
    job_id: str = Field(
        ...,
        description=JOB_ID_DESC,
        min_length=UUID_LENGTH,
        max_length=UUID_LENGTH,
        pattern=UUID_PATTERN,
    )
    job_run_id: str = Field(
        ...,
        description=JOB_RUN_ID_DESC,
        min_length=UUID_LENGTH,
        max_length=UUID_LENGTH,
        pattern=UUID_PATTERN,
    )
    status: ExecutionStatus = Field(
        default=ExecutionStatus.PENDING,
        description=JOB_STATUS_DESC,
    )
    message: str = Field(
        default="",
        description=MESSAGE_DESC,
        min_length=MESSAGE_MIN_LENGTH,
        max_length=MESSAGE_MAX_LENGTH,
        pattern=MESSAGE_PATTERN,
    )

    # Timing Fields
    start_time: int = Field(
        default=0,
        description=START_TIME_DESC,
        ge=TIMESTAMP_MIN,
        le=TIMESTAMP_MAX,
        json_schema_extra={"format": "int64"},
    )
    end_time: int = Field(
        default=0, description=END_TIME_DESC, ge=TIMESTAMP_MIN, le=TIMESTAMP_MAX, json_schema_extra={"format": "int64"}
    )
    duration: int = Field(
        default=0,
        description=DURATION_DESC,
        ge=DURATION_MIN,
        le=DURATION_MAX_SECONDS,
        json_schema_extra={"format": "int32"},
    )
    heartbeat_timestamp: int | None = Field(
        default=0, description=HEARTBEAT_DESC, ge=TIMESTAMP_MIN, le=TIMESTAMP_MAX, json_schema_extra={"format": "int64"}
    )
    progress_timestamp: int = Field(
        default=0,
        description=PROGRESS_TIMESTAMP_DESC,
        ge=TIMESTAMP_MIN,
        le=TIMESTAMP_MAX,
        json_schema_extra={"format": "int64"},
    )

    # Document Counts
    total_docs: int = Field(
        default=0,
        description=TOTAL_DOCS_DESC,
        ge=DOCS_COUNT_MIN,
        le=DOCS_COUNT_MAX,
        json_schema_extra={"format": "int64"},
    )
    processed_docs: int = Field(
        default=0,
        description=PROCESSED_DOCS_DESC,
        ge=DOCS_COUNT_MIN,
        le=DOCS_COUNT_MAX,
        json_schema_extra={"format": "int64"},
    )
    completed_docs: int | None = Field(
        default=0,
        description=COMPLETED_DOCS_DESC,
        ge=DOCS_COUNT_MIN,
        le=DOCS_COUNT_MAX,
        json_schema_extra={"format": "int64"},
    )
    failed_docs: int = Field(
        default=0,
        description=FAILED_DOCS_DESC,
        ge=DOCS_COUNT_MIN,
        le=DOCS_COUNT_MAX,
        json_schema_extra={"format": "int64"},
    )
    skipped_docs: int = Field(
        default=0,
        description=SKIPPED_DOCS_DESC,
        ge=DOCS_COUNT_MIN,
        le=DOCS_COUNT_MAX,
        json_schema_extra={"format": "int64"},
    )
    deleted_doc_count: int = Field(
        default=0,
        description=DELETED_DOCS_DESC,
        ge=DOCS_COUNT_MIN,
        le=DOCS_COUNT_MAX,
        json_schema_extra={"format": "int64"},
    )

    # Page Processing Stats
    total_pages_processed: int = Field(
        default=0,
        description=TOTAL_PAGES_DESC,
        ge=PAGES_COUNT_MIN,
        le=PAGES_COUNT_MAX,
        json_schema_extra={"format": "int64"},
    )
    page_type_stats: dict[str, int] | None = Field(
        default=None,
        description=PAGE_TYPE_STATS_DESC,
        json_schema_extra={
            "additionalProperties": {
                "type": "integer",
                "format": "int64",
                "minimum": PAGES_COUNT_MIN,
                "maximum": PAGES_COUNT_MAX,
            }
        },
    )
    execution_time: int | None = Field(
        default=None,
        description=EXECUTION_TIME_DESC,
        ge=EXECUTION_TIME_MIN,
        le=EXECUTION_TIME_MAX,
        json_schema_extra={"format": "int32"},
    )

    # Execution Context
    orchestrator: str = Field(
        default="Python",
        description=ORCHESTRATOR_DESC,
        min_length=ORCHESTRATOR_MIN_LENGTH,
        max_length=ORCHESTRATOR_MAX_LENGTH,
        pattern=ORCHESTRATOR_PATTERN,
    )
    container_kind: str | None = Field(
        default=None,
        description=CONTAINER_TYPE_DESC,
        min_length=CONTAINER_KIND_MIN_LENGTH,
        max_length=CONTAINER_KIND_MAX_LENGTH,
    )
    container_id: str | None = Field(
        default="",
        description=CONTAINER_ID_DESC_JOB,
        min_length=0,
        max_length=UUID_LENGTH,
    )
    flow_id: str | None = Field(
        default="",
        description=FLOW_ID_DESC_JOB,
        min_length=0,
        max_length=UUID_LENGTH,
    )
    flow_name: str | None = Field(
        default=None,
        description=FLOW_NAME_DESC_JOB,
        max_length=NAME_MAX_LENGTH,
    )

    # User & Account Context
    user_id: str | None = Field(
        default=None,
        description=USER_ID_DESC,
        min_length=USER_ID_MIN_LENGTH,
        max_length=USER_ID_MAX_LENGTH,
        pattern=USER_ID_PATTERN,
    )
    account_id: str | None = Field(
        default=None,
        description=ACCOUNT_ID_DESC,
        min_length=ACCOUNT_ID_MIN_LENGTH,
        max_length=ACCOUNT_ID_MAX_LENGTH,
    )
    user_entitlements: dict[str, Any] | None = Field(default_factory=dict, description=USER_ENTITLEMENTS_DESC)

    # Report Generation Status
    report_status: str | None = Field(
        default=None, description="Report generation status: GENERATING, COMPLETED, FAILED, or NOT_AVAILABLE"
    )
    report_generation_started_at: int | None = Field(
        default=None, description="Timestamp when report generation started"
    )
    report_generation_completed_at: int | None = Field(
        default=None, description="Timestamp when report generation completed or failed"
    )

    # Nested Statistics (Populated by aggregation)
    node_stats: dict[str, NodeStatsDto] = Field(default_factory=dict, description=NODE_STATS_DESC)
    batch_node_stats: dict[str, dict[str, NodeStatsDto]] = Field(
        default_factory=dict, description=BATCH_NODE_STATS_DESC
    )

    class Config:
        json_schema_extra: ClassVar[dict[str, Any]] = {
            "example": {
                "job_id": "550e8400-e29b-41d4-a716-446655440000",
                "job_run_id": "9a5137a7-15d5-431c-b945-b147a3043694",
                "status": "RUNNING",
                "message": "Processing batch 2 of 5",
                "start_time": 1704067200,
                "end_time": 0,
                "duration": 0,
                "heartbeat_timestamp": 1704067260,
                "total_docs": 1000,
                "processed_docs": 450,
                "failed_docs": 5,
                "skipped_docs": 0,
                "orchestrator": "Python",
            }
        }
