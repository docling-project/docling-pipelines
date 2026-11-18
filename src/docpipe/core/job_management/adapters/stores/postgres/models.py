"""
SQLModel database models for PostgreSQL job stats storage.

These models define the database schema for job_run_stats and node_stats tables.
Adapted from enterprise models for open-source use.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlmodel import Field, SQLModel

POSTGRES_SCHEMA = os.getenv("DOCPIPE_POSTGRES_SCHEMA", "docpipe_oss")


if TYPE_CHECKING:
    pass


class JobStatsModel(SQLModel, table=True):  # type: ignore[call-arg]
    """
    Job-level statistics model for PostgreSQL storage.

    Maps to job_run_stats table with all fields from JobStats.
    """

    __tablename__ = "job_run_stats"
    __table_args__ = {"schema": POSTGRES_SCHEMA}

    # Primary Key
    job_run_id: str = Field(
        primary_key=True,
        title="Job Run ID",
        description="Unique identifier for this specific run of the job",
        min_length=36,
        max_length=36,
    )

    # Core Identity & Status
    job_id: str = Field(
        index=True,
        title="Job ID",
        description="Unique identifier for the job",
        min_length=36,
        max_length=36,
    )
    status: str = Field(
        default="PENDING",
        title="Job Status",
        description="Current status of the job run",
        min_length=1,
        max_length=50,
    )
    message: str = Field(
        default="",
        title="Status Message",
        description="Optional message providing additional context",
        min_length=0,
        max_length=10000,
    )

    # Timing Fields
    start_time: int = Field(
        default=0,
        title="Start Time",
        description="Epoch timestamp (in seconds) when the job run started",
    )
    end_time: int = Field(
        default=0,
        title="End Time",
        description="Epoch timestamp (in seconds) when the job run ended",
    )
    duration: int = Field(
        default=0,
        title="Duration",
        description="Total duration of the job run in seconds",
    )
    heartbeat_timestamp: int | None = Field(
        default=0,
        title="Heartbeat Timestamp",
        description="Timestamp to ascertain if job run is currently in execution",
    )
    progress_timestamp: int = Field(
        default=0,
        title="Progress Timestamp",
        description="Timestamp of the last measurable unit of forward progress (epoch seconds)",
    )

    # Document Counts
    total_docs: int = Field(
        default=0,
        title="Total Documents",
        description="Total number of documents to be processed",
    )
    processed_docs: int = Field(
        default=0,
        title="Processed Documents",
        description="Number of documents processed (completed + failed + skipped)",
    )
    completed_docs: int | None = Field(
        default=0,
        title="Completed Documents",
        description="Number of documents successfully completed",
    )
    failed_docs: int = Field(
        default=0,
        title="Failed Documents",
        description="Number of documents that failed during processing",
    )
    skipped_docs: int = Field(
        default=0,
        title="Skipped Documents",
        description="Number of documents that were skipped",
    )
    deleted_doc_count: int = Field(
        default=0,
        title="Deleted Documents Count",
        description="Number of documents deleted in current flow run",
    )

    # Page Processing Stats
    total_pages_processed: int = Field(
        default=0,
        title="Total Pages Processed",
        description="Total number of pages processed in the job run",
    )
    page_type_stats: dict[str, int] | None = Field(
        default=None,
        sa_column=Column(JSONB),
        title="Page Type Statistics",
        description="Breakdown of pages processed by type",
    )
    execution_time: int | None = Field(
        default=None,
        title="Execution Time",
        description="Execution time in seconds when pages were processed",
    )

    # Execution Context
    orchestrator: str = Field(
        default="Python",
        title="Orchestrator",
        description="The orchestrator used to run the job",
        min_length=1,
        max_length=50,
    )
    container_kind: str | None = Field(
        default=None,
        title="Container Kind",
        description="Type of container where job run was created",
        min_length=0,
        max_length=50,
    )
    container_id: str | None = Field(
        default="",
        title="Container ID",
        description="ID of the container where job run was created",
        min_length=0,
        max_length=255,
    )
    flow_id: str | None = Field(
        default="",
        title="Flow ID",
        description="ID of the Docpipe flow for which job run was created",
        min_length=0,
        max_length=255,
    )
    flow_name: str | None = Field(
        default=None,
        title="Flow Name",
        description="Human-readable name of the flow at run creation time",
        max_length=255,
    )

    # User & Account Context (optional in open-source)
    user_id: str | None = Field(
        default=None,
        title="User ID",
        description="ID of the user who started the job run",
        min_length=0,
        max_length=255,
    )
    account_id: str | None = Field(
        default=None,
        title="Account ID",
        description="Account/Tenant from which job run was started",
        min_length=0,
        max_length=255,
    )
    user_entitlements: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
        title="User Entitlements",
        description="User entitlements and metadata",
    )

    # Report Generation Status
    report_status: str | None = Field(
        default=None,
        title="Report Status",
        description="Status of background report generation: GENERATING, COMPLETED, FAILED",
    )
    report_generation_started_at: int | None = Field(
        default=None,
        title="Report Started At",
        description="Epoch timestamp when report generation started",
    )
    report_generation_completed_at: int | None = Field(
        default=None,
        title="Report Completed At",
        description="Epoch timestamp when report generation completed or failed",
    )


class NodeStatsModel(SQLModel, table=True):  # type: ignore[call-arg]
    """
    Node-level statistics model for PostgreSQL storage.

    Maps to node_stats table with support for micro-batching.
    Uses auto-incrementing primary key with unique constraints on (node_id, job_run_id, batch_id).
    """

    __tablename__ = "node_stats"
    __table_args__ = {"schema": POSTGRES_SCHEMA}

    # Auto-incrementing Primary Key
    id: int | None = Field(default=None, primary_key=True)

    # Node Identification
    node_id: str = Field(
        title="Node ID",
        description="Unique identifier for the node",
        min_length=36,
        max_length=36,
    )
    name: str = Field(
        title="Node Name",
        description="Name of the node",
        min_length=1,
        max_length=256,
    )

    # Batch Context (for micro-batching)
    batch_id: str | None = Field(
        default=None,
        title="Batch ID",
        description="Unique identifier for the batch execution of the node",
        max_length=256,
    )
    batch_num: int | None = Field(
        default=None,
        title="Batch Number",
        description="Sequence number for the batch execution (0-indexed)",
    )

    # Foreign Key to job_run_stats with CASCADE delete
    job_run_id: str = Field(
        sa_column=Column(
            String(36),
            ForeignKey(f"{POSTGRES_SCHEMA}.job_run_stats.job_run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        title="Job Run ID",
        description="Reference to the job run",
    )

    # Status & Error
    node_status: str = Field(
        default="PENDING",
        title="Node Status",
        description="Execution status of the node",
        min_length=1,
        max_length=100,
    )
    error: str | None = Field(
        default=None,
        title="Error Message",
        description="Error message if any",
        min_length=0,
        max_length=10000,
    )

    # Timing Fields
    start_time: int = Field(
        default=0,
        title="Start Time",
        description="Epoch timestamp when node execution started",
    )
    end_time: int = Field(
        default=0,
        title="End Time",
        description="Epoch timestamp when node execution ended",
    )
    time_taken: int | None = Field(
        default=None,
        title="Time Taken",
        description="Execution time in seconds",
    )

    # Schema Information
    col_names: list[str] | None = Field(
        default_factory=list,
        sa_column=Column(ARRAY(String)),
        title="Column Names",
        description="List of column names produced by the node",
    )

    # Document Tracking (Lists of document IDs)
    total_docs: list[str] | None = Field(
        default_factory=list,
        sa_column=Column(ARRAY(String)),
        title="Total Documents",
        description="List of total documents processed",
    )
    failed_docs: list[str] | None = Field(
        default_factory=list,
        sa_column=Column(ARRAY(String)),
        title="Failed Documents",
        description="List of failed documents",
    )
    skipped_docs: list[str] | None = Field(
        default_factory=list,
        sa_column=Column(ARRAY(String)),
        title="Skipped Documents",
        description="List of skipped documents",
    )
    docs_completed: list[str] | None = Field(
        default_factory=list,
        sa_column=Column(ARRAY(String)),
        title="Completed Documents",
        description="List of successfully completed documents",
    )
    docs_completed_count: int = Field(
        default=0,
        title="Completed Documents Count",
        description="Count of completed documents",
    )

    # Operator Metadata (Custom per operator)
    node_metadata: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSONB),
        title="Node Metadata",
        description="Operator-specific metadata",
    )
