"""Job run API DTOs for request/response validation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from docpipe.api.dto.field_definitions import (
    ASSET_REF_TYPE_MAX_LENGTH,
    ASSET_REF_TYPE_MIN_LENGTH,
    ASSET_REF_TYPE_PATTERN,
    COMPLETED_DOCS_DESC,
    CONFIG_VALUE_MAX_LENGTH,
    CONFIG_VALUE_MIN_LENGTH,
    DESCRIPTION_MAX_LENGTH,
    DESCRIPTION_MIN_LENGTH,
    DESCRIPTION_PATTERN,
    DOCS_COUNT_MAX,
    DOCS_COUNT_MIN,
    DURATION_DESC,
    DURATION_MAX_SECONDS,
    DURATION_MIN,
    END_TIME_DESC,
    FAILED_DOCS_DESC,
    JOB_ID_DESC,
    JOB_PARAMS_MAX_ITEMS,
    # Array Limits
    JOB_PARAMS_MIN_ITEMS,
    # Descriptions
    JOB_RUN_ID_DESC,
    JOB_RUNS_LIST_MAX_ITEMS,
    JOB_RUNS_LIST_MIN_ITEMS,
    JOB_STATUS_DESC,
    JOB_STATUS_MAX_LENGTH,
    JOB_STATUS_MIN_LENGTH,
    JOB_STATUS_PATTERN,
    LIST_COUNT_MAX,
    LIST_COUNT_MIN,
    LIST_TOTAL_MAX,
    LIST_TOTAL_MIN,
    MESSAGE_DESC,
    MESSAGE_MAX_LENGTH,
    MESSAGE_MIN_LENGTH,
    MESSAGE_PATTERN,
    METADATA_VALUE_MAX_LENGTH,
    METADATA_VALUE_MIN_LENGTH,
    NAME_MAX_LENGTH,
    NAME_MIN_LENGTH,
    NAME_PATTERN,
    NODE_METADATA_DESC,
    NODE_METADATA_MAX_ITEMS,
    NODE_METADATA_MIN_ITEMS,
    NODE_SEQUENCE_DESC,
    NODE_SEQUENCE_MAX_ITEMS,
    NODE_SEQUENCE_MIN_ITEMS,
    ORCHESTRATOR_DESC,
    ORCHESTRATOR_MAX_LENGTH,
    ORCHESTRATOR_MIN_LENGTH,
    ORCHESTRATOR_PATTERN,
    PARAM_NAME_MAX_LENGTH,
    PARAM_NAME_MIN_LENGTH,
    PARAM_NAME_PATTERN,
    PARAM_VALUE_MAX_LENGTH,
    PARAM_VALUE_MIN_LENGTH,
    PARAM_VALUE_PATTERN,
    PROCESSED_DOCS_DESC,
    SKIPPED_DOCS_DESC,
    START_TIME_DESC,
    TIMESTAMP_MAX,
    # Integer Constraints
    TIMESTAMP_MIN,
    TOTAL_DOCS_DESC,
    USER_ID_DESC,
    USER_ID_MAX_LENGTH,
    USER_ID_MIN_LENGTH,
    USER_ID_PATTERN,
    # Length Constraints
    UUID_LENGTH,
    # Patterns
    UUID_PATTERN,
)
from docpipe.core.constants.constants import ExecutionStatus
from docpipe.core.constants.operator_constants import OperatorConstants

from .job_stats_dto import JobStatsDto
from .node_stats_dto import NodeMetadataItem


class JobRunConfigurationModel(BaseModel):
    """Execution-time configuration overrides for a job run."""

    user_id: str | None = Field(
        default=None,
        description=USER_ID_DESC,
        examples=["user123"],
        min_length=USER_ID_MIN_LENGTH,
        max_length=USER_ID_MAX_LENGTH,
        pattern=USER_ID_PATTERN,
    )
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Additional string metadata attached to the job run request",
        json_schema_extra={
            "additionalProperties": {
                "type": "string",
                "minLength": METADATA_VALUE_MIN_LENGTH,
                "maxLength": METADATA_VALUE_MAX_LENGTH,
            },
        },
        examples=[{"source": "legacy"}],
    )

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "user_id": "user123",
                "metadata": {"source": "legacy"},
            }
        },
    )


class JobParameterModel(BaseModel):
    """Named job parameter."""

    name: str = Field(
        ...,
        description="Parameter name",
        examples=["batch_size"],
        min_length=PARAM_NAME_MIN_LENGTH,
        max_length=PARAM_NAME_MAX_LENGTH,
        pattern=PARAM_NAME_PATTERN,
    )
    value: str = Field(
        ...,
        description="Parameter value serialized as a string",
        examples=["100"],
        min_length=PARAM_VALUE_MIN_LENGTH,
        max_length=PARAM_VALUE_MAX_LENGTH,
        pattern=PARAM_VALUE_PATTERN,
    )


class JobModel(BaseModel):
    """Job definition metadata used to create a job run."""

    asset_ref: str | None = Field(
        default=None,
        description="Identifier of the job or flow asset to execute",
        examples=["ac0ce3ce-a83d-49d8-ad03-33364731e6be"],
        min_length=UUID_LENGTH,
        max_length=UUID_LENGTH,
        pattern=UUID_PATTERN,
    )
    asset_ref_type: str | None = Field(
        default=None,
        description="Type of asset referenced by asset_ref",
        examples=["ibm_udp_flow"],
        min_length=ASSET_REF_TYPE_MIN_LENGTH,
        max_length=ASSET_REF_TYPE_MAX_LENGTH,
        pattern=ASSET_REF_TYPE_PATTERN,
    )
    name: str | None = Field(
        default=None,
        description="Human-readable job name",
        examples=["Test Flow"],
        min_length=NAME_MIN_LENGTH,
        max_length=NAME_MAX_LENGTH,
        pattern=NAME_PATTERN,
    )
    description: str | None = Field(
        default=None,
        description="Detailed job description",
        examples=["Runs the invoice extraction pipeline"],
        min_length=DESCRIPTION_MIN_LENGTH,
        max_length=DESCRIPTION_MAX_LENGTH,
        pattern=DESCRIPTION_PATTERN,
    )
    configuration: dict[str, str] = Field(
        default_factory=dict,
        description="Job configuration values serialized as strings",
        json_schema_extra={
            "additionalProperties": {
                "type": "string",
                "minLength": CONFIG_VALUE_MIN_LENGTH,
                "maxLength": CONFIG_VALUE_MAX_LENGTH,
            },
        },
        examples=[{"batch_size": "100"}],
    )
    job_parameters: list[JobParameterModel] = Field(
        default_factory=list,
        description="List of named job parameters",
        min_length=JOB_PARAMS_MIN_ITEMS,
        max_length=JOB_PARAMS_MAX_ITEMS,
        json_schema_extra={"minItems": JOB_PARAMS_MIN_ITEMS, "maxItems": JOB_PARAMS_MAX_ITEMS},
    )
    parameter_sets: list[JobParameterModel] = Field(
        default_factory=list,
        description="List of reusable parameter entries for this job",
        min_length=JOB_PARAMS_MIN_ITEMS,
        max_length=JOB_PARAMS_MAX_ITEMS,
        json_schema_extra={"minItems": JOB_PARAMS_MIN_ITEMS, "maxItems": JOB_PARAMS_MAX_ITEMS},
    )


class JobRunModel(BaseModel):
    """Job run override values applied at execution time."""

    name: str | None = Field(
        default=None,
        description="Override name for this specific job run",
        examples=["Nightly invoice run"],
        min_length=NAME_MIN_LENGTH,
        max_length=NAME_MAX_LENGTH,
        pattern=NAME_PATTERN,
    )
    description: str | None = Field(
        default=None,
        description="Override description for this specific job run",
        examples=["Triggered by nightly scheduler"],
        min_length=DESCRIPTION_MIN_LENGTH,
        max_length=DESCRIPTION_MAX_LENGTH,
        pattern=DESCRIPTION_PATTERN,
    )
    configuration: JobRunConfigurationModel | None = None
    job_parameters: list[JobParameterModel] = Field(
        default_factory=list,
        description="Run-specific parameter overrides",
        min_length=JOB_PARAMS_MIN_ITEMS,
        max_length=JOB_PARAMS_MAX_ITEMS,
        json_schema_extra={"minItems": JOB_PARAMS_MIN_ITEMS, "maxItems": JOB_PARAMS_MAX_ITEMS},
    )
    parameter_sets: list[JobParameterModel] = Field(
        default_factory=list,
        description="Run-specific parameter entries",
        min_length=JOB_PARAMS_MIN_ITEMS,
        max_length=JOB_PARAMS_MAX_ITEMS,
        json_schema_extra={"minItems": JOB_PARAMS_MIN_ITEMS, "maxItems": JOB_PARAMS_MAX_ITEMS},
    )


class EntityModel(BaseModel):
    """Entity wrapper containing job definition and optional run overrides."""

    job: JobModel | None = None
    job_run: JobRunModel | None = None


class JobsAPIExecuteModel(BaseModel):
    """Request model for POST /job-runs/create."""

    entity: EntityModel

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_payload(cls, data: Any) -> Any:
        """Support legacy top-level request format while preserving enterprise schema."""

        if not isinstance(data, dict) or "entity" in data:
            return data

        job_id = data.get("job_id") or data.get("flow_id")
        flow_name = data.get("flow_name") or job_id
        flow_config = data.get("flow_config")
        if flow_config is None:
            flow_config = data.get("configuration") or {}

        entity: dict[str, Any] = {
            "job": {
                "asset_ref": job_id,
                "asset_ref_type": "ibm_udp_flow",
                "name": flow_name,
                "configuration": flow_config,
            },
            "job_run": {
                "configuration": {},
            },
        }

        if data.get("metadata") is not None:
            entity["job_run"]["configuration"] = {"metadata": data.get("metadata")}

        return {"entity": entity}

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "entity": {
                    "job": {
                        "asset_ref": "550e8400-e29b-41d4-a716-446655440000",
                        "asset_ref_type": "ibm_udp_flow",
                        "name": "Test Flow",
                        "configuration": {"batch_size": "100"},
                    },
                    "job_run": {
                        "configuration": {
                            "user_id": "user123",
                            "metadata": {"source": "legacy"},
                        }
                    },
                }
            }
        }
    )


class JobRunCreateResponse(BaseModel):
    """Response model for POST /job-runs/create."""

    job_run_id: str = Field(
        ...,
        description=JOB_RUN_ID_DESC,
        examples=["9a5137a7-15d5-431c-b945-b147a3043694"],
        min_length=UUID_LENGTH,
        max_length=UUID_LENGTH,
        pattern=UUID_PATTERN,
    )
    status: str = Field(
        ...,
        description=JOB_STATUS_DESC,
        examples=[ExecutionStatus.RUNNING.value, ExecutionStatus.STARTING.value],
        min_length=JOB_STATUS_MIN_LENGTH,
        max_length=JOB_STATUS_MAX_LENGTH,
        pattern=JOB_STATUS_PATTERN,
    )
    message: str = Field(
        ...,
        description="Response message",
        examples=["Job run created successfully"],
        min_length=MESSAGE_MIN_LENGTH,
        max_length=MESSAGE_MAX_LENGTH,
        pattern=MESSAGE_PATTERN,
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "job_run_id": "9a5137a7-15d5-431c-b945-b147a3043694",
                "status": "Running",
                "message": "Job run created successfully",
            }
        }
    )


class JobRunStatusResponse(BaseModel):
    """Response model for GET /job_runs/{job_run_id}."""

    node_sequence: list[str] = Field(
        ...,
        description=NODE_SEQUENCE_DESC,
        min_length=NODE_SEQUENCE_MIN_ITEMS,
        max_length=NODE_SEQUENCE_MAX_ITEMS,
        json_schema_extra={"minItems": NODE_SEQUENCE_MIN_ITEMS, "maxItems": NODE_SEQUENCE_MAX_ITEMS},
    )
    job_stats: JobStatsDto = Field(..., description="Job-level statistics")
    node_metadata: list[NodeMetadataItem] = Field(
        ...,
        description=NODE_METADATA_DESC,
        min_length=NODE_METADATA_MIN_ITEMS,
        max_length=NODE_METADATA_MAX_ITEMS,
        json_schema_extra={"minItems": NODE_METADATA_MIN_ITEMS, "maxItems": NODE_METADATA_MAX_ITEMS},
    )

    # Dynamic fields for individual node logs (added at runtime)
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "node_sequence": ["node1", "node2"],
                "job_stats": {
                    "job_run_id": "9a5137a7-15d5-431c-b945-b147a3043694",
                    "job_id": "550e8400-e29b-41d4-a716-446655440000",
                    "status": "Completed",
                    "message": "Job completed successfully",
                    "start_time": 1776667641,
                    "end_time": 1776667670,
                    "duration": 29,
                    "heartbeat_timestamp": 0,
                    "total_docs": 10,
                    "processed_docs": 10,
                    "completed_docs": 10,
                    "failed_docs": 0,
                    "skipped_docs": 0,
                    "deleted_doc_count": 0,
                    "total_pages_processed": 0,
                    "page_type_stats": None,
                    "execution_time": None,
                    "orchestrator": "Python",
                    "container_kind": None,
                    "container_id": "",
                    "flow_id": "550e8400-e29b-41d4-a716-446655440000",
                    "user_id": None,
                    "account_id": None,
                    "user_entitlements": {},
                    "node_stats": {},
                    "batch_node_stats": {},
                },
                OperatorConstants.Metadata.NODE_METADATA: [],
            }
        },
    )


class JobRunListItemResponse(BaseModel):
    """Summary representation of a job run in list responses."""

    job_run_id: str = Field(
        ...,
        description=JOB_RUN_ID_DESC,
        examples=["9a5137a7-15d5-431c-b945-b147a3043694"],
        min_length=UUID_LENGTH,
        max_length=UUID_LENGTH,
        pattern=UUID_PATTERN,
    )
    job_id: str = Field(
        ...,
        description=JOB_ID_DESC,
        examples=["550e8400-e29b-41d4-a716-446655440000"],
        min_length=UUID_LENGTH,
        max_length=UUID_LENGTH,
        pattern=UUID_PATTERN,
    )
    flow_name: str | None = Field(
        default=None,
        description="Name of the flow being executed",
        examples=["Invoice Extraction Pipeline"],
    )
    status: str = Field(
        ...,
        description=JOB_STATUS_DESC,
        examples=[ExecutionStatus.RUNNING.value, ExecutionStatus.COMPLETED.value, ExecutionStatus.FAILED.value],
        min_length=JOB_STATUS_MIN_LENGTH,
        max_length=JOB_STATUS_MAX_LENGTH,
        pattern=JOB_STATUS_PATTERN,
    )
    message: str = Field(
        default="",
        description=MESSAGE_DESC,
        examples=["Job completed successfully"],
        min_length=MESSAGE_MIN_LENGTH,
        max_length=MESSAGE_MAX_LENGTH,
        pattern=MESSAGE_PATTERN,
    )
    start_time: int = Field(
        default=0,
        description=START_TIME_DESC,
        ge=TIMESTAMP_MIN,
        le=TIMESTAMP_MAX,
        json_schema_extra={"format": "int64"},
    )
    end_time: int = Field(
        default=0,
        description=END_TIME_DESC,
        ge=TIMESTAMP_MIN,
        le=TIMESTAMP_MAX,
        json_schema_extra={"format": "int64"},
    )
    duration: int = Field(
        default=0,
        description=DURATION_DESC,
        ge=DURATION_MIN,
        le=DURATION_MAX_SECONDS,
        json_schema_extra={"format": "int32"},
    )
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
    completed_docs: int = Field(
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
    orchestrator: str = Field(
        default="Python",
        description=ORCHESTRATOR_DESC,
        examples=["Python", "Prefect"],
        min_length=ORCHESTRATOR_MIN_LENGTH,
        max_length=ORCHESTRATOR_MAX_LENGTH,
        pattern=ORCHESTRATOR_PATTERN,
    )
    user_id: str | None = Field(
        default=None,
        description=USER_ID_DESC,
        min_length=USER_ID_MIN_LENGTH,
        max_length=USER_ID_MAX_LENGTH,
        pattern=USER_ID_PATTERN,
    )


class JobRunListResponse(BaseModel):
    """Response model for GET /job_runs/list."""

    job_runs: list[JobRunListItemResponse] = Field(
        ...,
        alias="list",
        serialization_alias="list",
        description="List of job runs returned for the current request",
        min_length=JOB_RUNS_LIST_MIN_ITEMS,
        max_length=JOB_RUNS_LIST_MAX_ITEMS,
        json_schema_extra={"minItems": JOB_RUNS_LIST_MIN_ITEMS, "maxItems": JOB_RUNS_LIST_MAX_ITEMS},
    )
    count: int = Field(
        ...,
        description="Number of items returned",
        ge=LIST_COUNT_MIN,
        le=LIST_COUNT_MAX,
        json_schema_extra={"format": "int32"},
        examples=[1],
    )
    total: int = Field(
        ...,
        description="Total number of items matching the current filters",
        ge=LIST_TOTAL_MIN,
        le=LIST_TOTAL_MAX,
        json_schema_extra={"format": "int32"},
        examples=[1],
    )

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "list": [
                    {
                        "job_run_id": "9a5137a7-15d5-431c-b945-b147a3043694",
                        "job_id": "550e8400-e29b-41d4-a716-446655440000",
                        "status": "Completed",
                    }
                ],
                "count": 1,
                "total": 1,
            }
        },
    )


class JobRunCancelResponse(BaseModel):
    """Response model for POST /job-runs/{job_run_id}/cancel."""

    job_run_id: str = Field(
        ...,
        description=JOB_RUN_ID_DESC,
        examples=["9a5137a7-15d5-431c-b945-b147a3043694"],
        min_length=UUID_LENGTH,
        max_length=UUID_LENGTH,
        pattern=UUID_PATTERN,
    )
    status: str = Field(
        ...,
        description="Current job run status after the cancellation request",
        examples=[ExecutionStatus.CANCELING.value, ExecutionStatus.CANCELED.value],
        min_length=JOB_STATUS_MIN_LENGTH,
        max_length=JOB_STATUS_MAX_LENGTH,
        pattern=JOB_STATUS_PATTERN,
    )
    message: str = Field(
        ...,
        description="Cancellation status message",
        examples=["Cancellation requested for job run: 9a5137a7-15d5-431c-b945-b147a3043694"],
        min_length=MESSAGE_MIN_LENGTH,
        max_length=MESSAGE_MAX_LENGTH,
        pattern=MESSAGE_PATTERN,
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "job_run_id": "9a5137a7-15d5-431c-b945-b147a3043694",
                "status": "Canceling",
                "message": "Cancellation requested for job run: 9a5137a7-15d5-431c-b945-b147a3043694",
            }
        }
    )
