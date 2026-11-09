# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Job run management API routes.

This module provides REST API endpoints for job run operations including
create, list, get status, cancel, and delete job runs.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, status
from fastapi.responses import JSONResponse, Response

from docpipe.api.auth.actor import get_actor
from docpipe.api.dependencies import get_job_management_service, get_job_stats_service
from docpipe.api.dto.error_dto import ErrorResponse
from docpipe.api.dto.field_definitions import (
    JOB_STATUS_MAX_LENGTH,
    JOB_STATUS_MIN_LENGTH,
    JOB_STATUS_PATTERN,
    LIMIT_MAX,
    LIMIT_MIN,
    USER_ID_MAX_LENGTH,
    USER_ID_MIN_LENGTH,
    USER_ID_PATTERN,
    UUID_LENGTH,
    UUID_PATTERN,
)
from docpipe.api.dto.job_run_dto import (
    JobRunCancelResponse,
    JobRunCreateResponse,
    JobRunListResponse,
    JobRunStatusResponse,
    JobsAPIExecuteModel,
)
from docpipe.core.constants import ExecutionStatus
from docpipe.core.job_management.application.services import JobManagementService
from docpipe.core.job_management.domain.ports import JobStatsService
from docpipe.core.models.actor_context import ActorContext
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

job_runs_router = APIRouter(prefix="/job_runs", tags=["job-runs"])

JobRunIdPath = Annotated[
    str,
    Path(
        description="Unique identifier for the job run",
        min_length=UUID_LENGTH,
        max_length=UUID_LENGTH,
        pattern=UUID_PATTERN,
        examples=["9a5137a7-15d5-431c-b945-b147a3043694"],
    ),
]

JobIdQuery = Annotated[
    str,
    Query(
        description="Filter job runs by job or flow identifier",
        min_length=UUID_LENGTH,
        max_length=UUID_LENGTH,
        pattern=UUID_PATTERN,
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    ),
]

UserIdQuery = Annotated[
    str,
    Query(
        description="Filter job runs by requesting user identifier",
        min_length=USER_ID_MIN_LENGTH,
        max_length=USER_ID_MAX_LENGTH,
        pattern=USER_ID_PATTERN,
        examples=["user123"],
    ),
]

JobStatusQuery = Annotated[
    ExecutionStatus,
    Query(
        description="Filter job runs by current execution status",
        examples=[ExecutionStatus.RUNNING, ExecutionStatus.COMPLETED, ExecutionStatus.FAILED],
        min_length=JOB_STATUS_MIN_LENGTH,
        max_length=JOB_STATUS_MAX_LENGTH,
        pattern=JOB_STATUS_PATTERN,
        alias="status",
    ),
]

LimitQuery = Annotated[
    int,
    Query(
        description="Maximum number of job runs to return",
        ge=LIMIT_MIN,
        le=LIMIT_MAX,
        examples=[100],
        json_schema_extra={"format": "int32"},
    ),
]

IncludeLogsQuery = Annotated[
    bool,
    Query(
        description="Include execution logs in the job run status response",
        examples=[False, True],
    ),
]

JobStatsServiceDep = Annotated[JobStatsService, Depends(get_job_stats_service)]
JobManagementServiceDep = Annotated[JobManagementService, Depends(get_job_management_service)]
ActorDep = Annotated[ActorContext | None, Depends(get_actor)]


@job_runs_router.post(
    "",
    response_model=JobRunCreateResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_job_run",
    summary="Create a job run",
    responses={
        201: {
            "description": "Job run created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "job_run_id": "99ecd646-bb8e-494a-a0c5-86b40c1d4f90",
                        "status": "Starting",
                        "message": "Job run created successfully",
                    }
                }
            },
        },
        500: {
            "model": ErrorResponse,
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [{"code": "internal_error", "message": "Failed to create job run"}],
                        "trace": "12345678-1234-4234-9234-123456789012",
                        "status_code": 500,
                    }
                }
            },
        },
    },
)
async def create_job_run(
    request: Request,
    body: JobsAPIExecuteModel,
    service: JobManagementServiceDep,
    actor: ActorDep,
) -> JobRunCreateResponse:
    """Create and start a new job run.

    Args:
        request: FastAPI request object
        body: Job run creation request with job and configuration details
        service: Injected job management service
        actor: Authenticated caller, or None when auth is disabled

    Returns:
        JobRunCreateResponse: Created job run details with unique ID

    Raises:
        HTTPException: If creation fails (400, 404, 500)
    """
    logger.debug("Creating job run")
    result = service.create_job_run_from_request(request_body=body, actor=actor)
    job_run_id = result.get("job_run_id")

    logger.info("Successfully created job run: %s", job_run_id)
    return JobRunCreateResponse(
        job_run_id=job_run_id,
        status=ExecutionStatus.STARTING.value,
        message="Job run created successfully",
    )


@job_runs_router.get(
    "",
    response_model=JobRunListResponse,
    operation_id="list_job_runs",
    summary="List job runs",
    responses={
        200: {
            "description": "Job runs retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "list": [
                            {
                                "job_run_id": "99ecd646-bb8e-494a-a0c5-86b40c1d4f90",
                                "job_id": "99fa9b78-09d3-4c9f-a179-dd688ef8e899",
                                "status": "Completed",
                                "message": "Job completed successfully",
                                "start_time": 1704067200,
                                "end_time": 1704067260,
                                "duration": 60,
                                "total_docs": 10,
                                "processed_docs": 10,
                                "completed_docs": 10,
                                "failed_docs": 0,
                                "skipped_docs": 0,
                                "orchestrator": "Python",
                                "user_id": "user123",
                            }
                        ],
                        "count": 1,
                        "total": 1,
                    }
                }
            },
        },
        500: {
            "model": ErrorResponse,
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [{"code": "internal_error", "message": "Failed to list job runs"}],
                        "trace": "12345678-1234-4234-9234-123456789012",
                        "status_code": 500,
                    }
                }
            },
        },
    },
)
async def list_job_runs(
    request: Request,
    service: JobManagementServiceDep,
    job_id: JobIdQuery | None = None,
    job_status: JobStatusQuery | None = None,
    limit: LimitQuery = 100,
) -> JobRunListResponse:
    """List job runs with optional filters.

    Args:
        request: FastAPI request object
        service: Injected job management service
        current_user: Authenticated user from token
        job_id: Optional job/flow ID filter
        job_status: Optional status filter
        limit: Maximum results to return

    Returns:
        JobRunListResponse: List of job runs

    Raises:
        HTTPException: If list operation fails (400, 500)
    """
    logger.debug("Listing job runs: job_id=%s, status=%s", job_id, job_status)

    result = service.list_job_runs(
        job_id=job_id,
        status=job_status,
        limit=limit,
    )

    logger.info("Listed %s job runs", result["count"])
    return JobRunListResponse(**result)


@job_runs_router.get(
    "/{job_run_id}",
    response_model=JobRunStatusResponse,
    operation_id="get_job_run",
    summary="Get job run status",
    responses={
        200: {
            "description": "Job run status retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "node_sequence": ["30953cfb-a3a2-4688-9aea-ff9fff10f7bd"],
                        "job_stats": {
                            "job_id": "99fa9b78-09d3-4c9f-a179-dd688ef8e899",
                            "job_run_id": "99ecd646-bb8e-494a-a0c5-86b40c1d4f90",
                            "status": "Completed",
                            "message": "",
                            "start_time": 1777399919,
                            "end_time": 1777399957,
                            "duration": 38,
                            "total_docs": 200,
                            "processed_docs": 200,
                            "completed_docs": 200,
                            "failed_docs": 0,
                            "skipped_docs": 0,
                            "orchestrator": "Python",
                            "user_id": "USER999",
                            "node_stats": {
                                "30953cfb-a3a2-4688-9aea-ff9fff10f7bd": {
                                    "node_id": "30953cfb-a3a2-4688-9aea-ff9fff10f7bd",
                                    "name": "ingest",
                                    "node_status": "Completed",
                                    "start_time": 1777399919,
                                    "end_time": 1777399920,
                                    "time_taken": 1,
                                }
                            },
                        },
                        "node_metadata": [
                            {
                                "id": "30953cfb-a3a2-4688-9aea-ff9fff10f7bd",
                                "operator": "ingest",
                                "node_metadata": {
                                    "node_status": "Completed",
                                    "processed_docs": 200,
                                    "documents_in_scope": 200,
                                },
                            }
                        ],
                        "30953cfb-a3a2-4688-9aea-ff9fff10f7bd": "Starting execution: Step Name: ingest\n\nSchema:\nid: string\npath: string\n\nCompleted execution: ingest, time= 1.00 seconds",
                    }
                }
            },
        },
        404: {
            "model": ErrorResponse,
            "description": "Job run not found",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [
                            {"code": "not_found", "message": "Job run not found: 99ecd646-bb8e-494a-a0c5-86b40c1d4f90"}
                        ],
                        "trace": "12345678-1234-4234-9234-123456789012",
                        "status_code": 404,
                    }
                }
            },
        },
        500: {
            "model": ErrorResponse,
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [{"code": "internal_error", "message": "Failed to retrieve job run"}],
                        "trace": "12345678-1234-4234-9234-123456789012",
                        "status_code": 500,
                    }
                }
            },
        },
    },
)
async def get_job_run_status(
    request: Request,
    job_run_id: JobRunIdPath,
    service: JobStatsServiceDep,
    include_logs: bool = Query(
        default=False,
        description="Include execution logs in the job run status response",
        examples=[False, True],
    ),
) -> JobRunStatusResponse:
    """
    Retrieve job run status and statistics.

    Args:
        request: FastAPI request object
        job_run_id: Job run identifier
        service: Injected job stats service
        include_logs: Whether to include execution logs

    Returns:
        JobRunStatusResponse: Comprehensive job run status with node details

    Raises:
        HTTPException: If job run not found or retrieval fails (404, 500)
    """
    logger.debug("Retrieving job run status: %s, include_logs=%s", job_run_id, include_logs)

    return service.get_formatted_job_stats(job_run_id=job_run_id, include_logs=include_logs)


@job_runs_router.post(
    "/{job_run_id}/cancel",
    response_model=JobRunCancelResponse,
    status_code=202,
    operation_id="cancel_job_run",
    summary="Cancel a running job",
    responses={
        202: {
            "description": "Job cancellation requested",
            "content": {
                "application/json": {
                    "example": {
                        "job_run_id": "99ecd646-bb8e-494a-a0c5-86b40c1d4f90",
                        "status": "Canceling",
                        "message": "Cancellation requested for job run: 99ecd646-bb8e-494a-a0c5-86b40c1d4f90",
                    }
                }
            },
        },
        404: {
            "model": ErrorResponse,
            "description": "Job run not found",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [{"code": "not_found", "message": "Job run not found"}],
                        "trace": "12345678-1234-4234-9234-123456789012",
                        "status_code": 404,
                    }
                }
            },
        },
        500: {
            "model": ErrorResponse,
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [{"code": "internal_error", "message": "Failed to cancel job run"}],
                        "trace": "12345678-1234-4234-9234-123456789012",
                        "status_code": 500,
                    }
                }
            },
        },
    },
)
async def cancel_job_run(
    request: Request,
    job_run_id: JobRunIdPath,
    service: JobManagementServiceDep,
    actor: ActorDep,
) -> JobRunCancelResponse:
    """Request cancellation of a running job.

    Args:
        request: FastAPI request object
        job_run_id: Job run identifier
        service: Injected job management service
        actor: Authenticated caller, or None when auth is disabled

    Returns:
        JobRunCancelResponse: Cancellation confirmation

    Raises:
        HTTPException: If job run not found or cancellation fails (404, 500)
    """
    logger.debug("Requesting cancellation for job run: %s", job_run_id)

    # Service raises JobRunNotFoundException if not found
    service.cancel_job_run(job_run_id=job_run_id, actor=actor)

    logger.info("Successfully requested cancellation: %s", job_run_id)
    return JobRunCancelResponse(
        job_run_id=job_run_id,
        status=ExecutionStatus.CANCELING.value,
        message=f"Cancellation requested for job run: {job_run_id}",
    )


@job_runs_router.delete(
    "/{job_run_id}",
    status_code=204,
    operation_id="delete_job_run",
    summary="Delete a job run",
    responses={
        204: {"description": "Job run deleted successfully"},
        404: {
            "model": ErrorResponse,
            "description": "Job run not found",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [{"code": "not_found", "message": "Job run not found"}],
                        "trace": "12345678-1234-4234-9234-123456789012",
                        "status_code": 404,
                    }
                }
            },
        },
        500: {
            "model": ErrorResponse,
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [{"code": "internal_error", "message": "Failed to delete job run"}],
                        "trace": "12345678-1234-4234-9234-123456789012",
                        "status_code": 500,
                    }
                }
            },
        },
    },
)
async def delete_job_run(
    request: Request,
    job_run_id: JobRunIdPath,
    service: JobManagementServiceDep,
    actor: ActorDep,
):
    """Delete a job run and its associated data.

    Args:
        request: FastAPI request object
        job_run_id: Job run identifier
        service: Injected job management service
        actor: Authenticated caller, or None when auth is disabled

    Returns:
        None: 204 No Content on success

    Raises:
        HTTPException: If job run not found or deletion fails (404, 500)
    """
    logger.debug("Deleting job run: %s", job_run_id)

    # Service raises JobRunNotFoundException if not found
    service.delete_job_run(job_run_id=job_run_id, actor=actor)

    logger.info("Successfully deleted job run: %s", job_run_id)
    return


@job_runs_router.get(
    "/{job_run_id}/report",
    response_class=Response,
    operation_id="download_job_report",
    summary="Download job run report",
    description="Download a CSV report containing document processing details for a completed job run",
    responses={
        200: {
            "description": "CSV report file",
            "content": {
                "text/csv": {
                    "example": "GUID,File name,Status,Status reason,Time stamp,Pages,Processing time (in seconds)\n..."
                }
            },
        },
        404: {
            "model": ErrorResponse,
            "description": "Job run not found",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [{"code": "not_found", "message": "Job run not found"}],
                        "trace": "12345678-1234-4234-9234-123456789012",
                        "status_code": 404,
                    }
                }
            },
        },
        425: {
            "model": ErrorResponse,
            "description": "Job not yet completed",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [{"code": "too_early", "message": "Job run is not yet completed"}],
                        "trace": "12345678-1234-4234-9234-123456789012",
                        "status_code": 425,
                    }
                }
            },
        },
        500: {
            "model": ErrorResponse,
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [{"code": "internal_error", "message": "Failed to generate report"}],
                        "trace": "12345678-1234-4234-9234-123456789012",
                        "status_code": 500,
                    }
                }
            },
        },
    },
)
async def download_job_report(
    request: Request,
    job_run_id: JobRunIdPath,
    job_stats_service: Annotated[JobStatsService, Depends(get_job_stats_service)],
):
    """Download the job run report as a CSV file.

    The report includes document-level details:
    - GUID: Document identifier
    - File name: Document name
    - Status: Ingested/Failed/Skipped
    - Status reason: Reason for failure or skipping
    - Time stamp: Processing timestamp
    - Pages: Number of pages processed
    - Processing time: Time taken to process (in seconds)

    Args:
        request: FastAPI request object
        job_run_id: Job run identifier
        job_stats_service: Injected job stats service

    Returns:
        StreamingResponse: CSV file download

    Raises:
        HTTPException: If job run not found (404), not completed (425), or report generation fails (500)
    """
    from docpipe.core.job_management.application.services.report_generator import JobReportGenerator

    logger.debug("Downloading job report for job run: %s", job_run_id)

    return JobReportGenerator.download_report(job_run_id=job_run_id, job_stats_service=job_stats_service)


@job_runs_router.get(
    "/{job_run_id}/flow_definition",
    response_class=JSONResponse,
    operation_id="get_flow_definition_snapshot",
    summary="Get flow definition snapshot for a job run",
    responses={
        200: {
            "description": "Flow definition retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "flow_name": "Sample Flow",
                        "description": "Flow description",
                        "flow": [{"name": "node1", "type": "ingest", "config": {}}],
                    }
                }
            },
        },
        404: {
            "model": ErrorResponse,
            "description": "Flow definition not found",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [{"code": "not_found", "message": "Flow definition not found for job run"}],
                        "trace": "12345678-1234-4234-9234-123456789012",
                        "status_code": 404,
                    }
                }
            },
        },
        500: {
            "model": ErrorResponse,
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [{"code": "internal_error", "message": "Failed to retrieve flow definition"}],
                        "trace": "12345678-1234-4234-9234-123456789012",
                        "status_code": 500,
                    }
                }
            },
        },
    },
)
async def get_flow_definition_snapshot(
    job_run_id: JobRunIdPath,
    stats_service: JobStatsServiceDep,
) -> JSONResponse:
    """
    Retrieve the flow definition snapshot for a specific job run.

    This endpoint returns the exact flow definition (in compiled DAG format) that was
    used for the specified job run execution. The flow definition is stored at the
    time of job run creation for audit and reproducibility purposes.

    Args:
        job_run_id: Job run identifier
        stats_service: Job statistics service (injected)

    Returns:
        JSONResponse: Flow definition JSON

    Raises:
        DocpipeException: If flow definition not found (404) or retrieval fails (500)
    """
    logger.debug("Retrieving flow definition for job_run_id=%s", job_run_id)

    # Service raises JobRunNotFoundException if not found
    flow_definition = stats_service.get_flow_definition(job_run_id=job_run_id)

    logger.info("Successfully retrieved flow definition for job_run_id=%s", job_run_id)
    return JSONResponse(content=flow_definition)
