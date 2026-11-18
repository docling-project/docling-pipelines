"""Project management API routes.

Provides REST API endpoints for project CRUD operations:
POST   /api/v1/projects                  — create project
GET    /api/v1/projects                  — list projects (paginated)
GET    /api/v1/projects/{project_id}     — get project by ID
PUT    /api/v1/projects/{project_id}     — full replace
PATCH  /api/v1/projects/{project_id}     — partial update
DELETE /api/v1/projects/{project_id}     — delete project
GET    /api/v1/projects/{project_id}/flows — list flows for a project with job run status

Error handling is delegated to the service layer which raises typed
DocpipeException subclasses; the existing docpipe_exception_handler
middleware converts these to ErrorResponse DTOs automatically.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from docpipe.api.dependencies import get_project_service
from docpipe.api.dto.error_dto import ErrorResponse
from docpipe.api.dto.field_definitions import (
    LIMIT_MAX,
    LIMIT_MIN,
    NAME_MAX_LENGTH,
    NAME_MIN_LENGTH,
    OFFSET_MAX,
    OFFSET_MIN,
    TAG_MAX_LENGTH,
    TAG_MIN_LENGTH,
    TAG_PATTERN,
    UUID_LENGTH,
    UUID_PATTERN,
)
from docpipe.api.dto.mappers.project_flow_mapper import ProjectFlowMapper
from docpipe.api.dto.mappers.project_mapper import ProjectMapper
from docpipe.api.dto.project_dto import (
    PaginatedProjectResponse,
    ProjectCreateRequest,
    ProjectPatchRequest,
    ProjectResponse,
    ProjectUpdateRequest,
)
from docpipe.api.dto.project_flow_dto import PaginatedProjectFlowResponse
from docpipe.core.projects.application.services.project_service import ProjectService
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

projects_router = APIRouter(prefix="/projects", tags=["Projects"])

# ── Path / query parameter type aliases ─────────────────────────────────

ProjectIdPath = Annotated[
    str,
    Path(
        description="Unique identifier for the project",
        min_length=UUID_LENGTH,
        max_length=UUID_LENGTH,
        pattern=UUID_PATTERN,
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    ),
]

_LimitQuery = Annotated[
    int,
    Query(
        description="Maximum number of projects to return",
        ge=LIMIT_MIN,
        le=LIMIT_MAX,
        examples=[100],
        json_schema_extra={"format": "int32"},
    ),
]

_OffsetQuery = Annotated[
    int,
    Query(
        description="Number of projects to skip",
        ge=OFFSET_MIN,
        le=OFFSET_MAX,
        examples=[0],
        json_schema_extra={"format": "int32"},
    ),
]

_NameQuery = Annotated[
    str | None,
    Query(
        description="Filter projects by name (partial match, case-insensitive)",
        min_length=NAME_MIN_LENGTH,
        max_length=NAME_MAX_LENGTH,
        examples=["invoice"],
    ),
]

_TagsQuery = Annotated[
    list[str] | None,
    Query(
        description="Filter projects by tags (returns projects with any of these tags)",
        examples=[["finance", "ml"]],
        json_schema_extra={
            "minItems": 0,
            "maxItems": 36,
            "items": {
                "type": "string",
                "minLength": TAG_MIN_LENGTH,
                "maxLength": TAG_MAX_LENGTH,
                "pattern": TAG_PATTERN,
            },
        },
    ),
]

_IsElyraQuery = Annotated[
    bool | None,
    Query(
        description="Filter by format: true=Elyra only, false=Authoring only, null=All formats",
        examples=[True, False],
    ),
]

ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]


# ── Endpoints ───────────────────────────────────────────────────────────


@projects_router.post(
    "",
    response_model=ProjectResponse,
    status_code=201,
    operation_id="create_project",
    summary="Create a new project",
    responses={
        201: {"description": "Project created successfully"},
        400: {"model": ErrorResponse, "description": "Validation error"},
        409: {"model": ErrorResponse, "description": "Project name already exists"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def create_project(
    body: ProjectCreateRequest,
    service: ProjectServiceDep,
) -> ProjectResponse:
    """Create and persist a new project.

    Args:
        body: Validated project creation request.
        service: Injected ProjectService.

    Returns:
        The created project with flow_count=0.
    """
    logger.debug("Creating project: %s", body.name)
    domain = ProjectMapper.create_request_to_domain(body)
    created = service.create_project(project=domain)
    logger.info("Created project %s", created.project_id)
    return ProjectMapper.domain_to_dto(created)


@projects_router.get(
    "",
    response_model=PaginatedProjectResponse,
    operation_id="list_projects",
    summary="List projects with pagination and filtering",
    responses={
        200: {"description": "Projects retrieved successfully"},
        400: {"model": ErrorResponse, "description": "Invalid query parameters"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def list_projects(
    request: Request,
    service: ProjectServiceDep,
    limit: _LimitQuery = 100,
    offset: _OffsetQuery = 0,
    name: _NameQuery = None,
    tags: _TagsQuery = None,
) -> PaginatedProjectResponse:
    """Return a paginated list of projects with optional name/tag filtering.

    Args:
        request: FastAPI request (used to build pagination links).
        service: Injected ProjectService.
        limit: Max items per page.
        offset: Items to skip.
        name: Optional name substring filter.
        tags: Optional tag filter (any-match).

    Returns:
        Paginated project list with navigation links.
    """
    logger.debug("Listing projects: offset=%d limit=%d name=%s tags=%s", offset, limit, name, tags)
    projects = service.list_projects(skip=offset, limit=limit, name_filter=name, tags_filter=tags)
    total = service.count_projects(name_filter=name, tags_filter=tags)

    base_url = str(request.url).split("?")[0]
    name_param = f"&name={name}" if name else ""
    first_link = f"{base_url}?offset=0&limit={limit}{name_param}"
    next_link = (
        f"{base_url}?offset={offset + limit}&limit={limit}{name_param}" if (offset + len(projects)) < total else None
    )
    prev_link = f"{base_url}?offset={max(0, offset - limit)}&limit={limit}{name_param}" if offset > 0 else None

    logger.info("Listed %d projects (total=%d)", len(projects), total)
    return PaginatedProjectResponse(
        projects=[ProjectMapper.domain_to_dto(p) for p in projects],
        total_count=total,
        offset=offset,
        limit=limit,
        first=first_link,
        next=next_link,
        prev=prev_link,
    )


@projects_router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    operation_id="get_project",
    summary="Get project by ID",
    responses={
        200: {"description": "Project retrieved successfully"},
        400: {"model": ErrorResponse, "description": "Invalid project_id format"},
        404: {"model": ErrorResponse, "description": "Project not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def get_project(
    project_id: ProjectIdPath,
    service: ProjectServiceDep,
) -> ProjectResponse:
    """Retrieve a single project by its UUID.

    Args:
        project_id: UUID of the project (validated by path param).
        service: Injected ProjectService.

    Returns:
        Project with current flow_count.
    """
    logger.debug("Getting project: %s", project_id)
    project = service.get_project(project_id=project_id)
    logger.info("Retrieved project %s", project_id)
    return ProjectMapper.domain_to_dto(project)


@projects_router.put(
    "/{project_id}",
    response_model=ProjectResponse,
    operation_id="replace_project",
    summary="Fully replace a project",
    responses={
        200: {"description": "Project updated successfully"},
        400: {"model": ErrorResponse, "description": "Validation error or invalid project_id"},
        404: {"model": ErrorResponse, "description": "Project not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def replace_project(
    project_id: ProjectIdPath,
    body: ProjectUpdateRequest,
    service: ProjectServiceDep,
) -> ProjectResponse:
    """Fully replace a project's mutable fields.

    Immutable fields (project_id, created_on, created_by) are preserved from
    the existing record.

    Args:
        project_id: UUID of the project to update.
        body: Validated full-replace request body.
        service: Injected ProjectService.

    Returns:
        The updated project.
    """
    logger.debug("Replacing project: %s", project_id)
    existing = service.get_project(project_id=project_id)
    domain = ProjectMapper.update_request_to_domain(project_id=project_id, existing=existing, dto=body)
    updated = service.update_project(project=domain)
    logger.info("Replaced project %s", project_id)
    return ProjectMapper.domain_to_dto(updated)


@projects_router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    operation_id="update_project",
    summary="Partially update a project",
    responses={
        200: {"description": "Project partially updated successfully"},
        400: {"model": ErrorResponse, "description": "Validation error or invalid project_id"},
        404: {"model": ErrorResponse, "description": "Project not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def update_project(
    project_id: ProjectIdPath,
    body: ProjectPatchRequest,
    service: ProjectServiceDep,
) -> ProjectResponse:
    """Partially update a project — only provided fields are changed.

    Args:
        project_id: UUID of the project to update.
        body: Validated partial-update request body.
        service: Injected ProjectService.

    Returns:
        The updated project.
    """
    logger.debug("Partially updating project: %s", project_id)
    updated = service.partial_update_project(project_id=project_id, updates=body.model_dump(exclude_unset=True))
    logger.info("Partially updated project %s", project_id)
    return ProjectMapper.domain_to_dto(updated)


@projects_router.delete(
    "/{project_id}",
    status_code=204,
    operation_id="delete_project",
    summary="Delete a project",
    responses={
        204: {"description": "Project deleted successfully"},
        400: {"model": ErrorResponse, "description": "Invalid project_id format"},
        404: {"model": ErrorResponse, "description": "Project not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def delete_project(
    project_id: ProjectIdPath,
    service: ProjectServiceDep,
) -> None:
    """Delete a project and all flows linked to it via container_id.

    Cascade-deletes every flow whose container_id matches the project_id
    before removing the project record. Individual flow deletion failures
    are logged as warnings but do not block the project deletion.

    Args:
        project_id: UUID of the project to delete.
        service: Injected ProjectService.

    Returns:
        204 No Content on success.
    """
    logger.debug("Deleting project: %s", project_id)
    service.delete_project(project_id=project_id)
    logger.info("Deleted project %s", project_id)
    return


@projects_router.get(
    "/{project_id}/flows",
    response_model=PaginatedProjectFlowResponse,
    operation_id="list_project_flows",
    summary="List flows belonging to a project with job run status",
    responses={
        200: {
            "description": "Flows retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "flows": [
                            {
                                "flow_id": "7159c2c9-6058-4dad-98a4-e47bb1359ddc",
                                "name": "Invoice Processing Pipeline",
                                "tags": ["invoice", "extraction"],
                                "created_on": "2026-04-01T11:00:00Z",
                                "modified_on": "2026-04-01T12:30:00Z",
                                "created_by": "user@example.com",
                                "modified_by": "user@example.com",
                                "job_run_summary": {
                                    "total_runs": 3,
                                    "last_run_id": "9a5137a7-15d5-431c-b945-b147a3043694",
                                    "last_run_status": "Completed",
                                    "last_run_start_time": 1743508800000,
                                    "status_counts": {"Completed": 3},
                                },
                            },
                            {
                                "flow_id": "b4346642-a642-4b33-83e8-4ad9816d45c4",
                                "name": "Customer Support Triage",
                                "tags": ["support"],
                                "created_on": "2026-04-02T09:00:00Z",
                                "modified_on": "2026-04-02T09:00:00Z",
                                "created_by": "user@example.com",
                                "modified_by": None,
                                "job_run_summary": None,
                            },
                        ],
                        "total_count": 2,
                        "offset": 0,
                        "limit": 100,
                        "first": "http://localhost:8080/api/v1/projects/142a2ba2-d67a-439e-95e6-b718d715e1dd/flows?offset=0&limit=100",
                        "next": None,
                        "prev": None,
                    }
                }
            },
        },
        400: {"model": ErrorResponse, "description": "Invalid project_id or query parameters"},
        404: {"model": ErrorResponse, "description": "Project not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def list_project_flows(
    request: Request,
    project_id: ProjectIdPath,
    service: ProjectServiceDep,
    limit: _LimitQuery = 100,
    offset: _OffsetQuery = 0,
    name: _NameQuery = None,
    tags: _TagsQuery = None,
    is_hidden: bool | None = Query(default=None, description="Filter by visibility status"),
    is_elyra: _IsElyraQuery = None,
) -> PaginatedProjectFlowResponse:
    """List flows belonging to a project, each enriched with aggregated job run status.

    Delegates entirely to ProjectService — never calls FlowService or
    JobStatsService directly.  The service performs two queries (flows scoped by
    container_id=project_id, then a bulk job-run fetch) and returns both; this
    handler zips them via ProjectFlowMapper.to_dto() and wraps the result in
    PaginatedProjectFlowResponse with offset/limit navigation links.

    Each flow item (ProjectFlowSummary) contains identity, provenance, tags, and
    job_run_summary.  job_run_summary is null for flows never executed.
    The flow definition payload is intentionally excluded.

    Args:
        request:    FastAPI request — used to derive the base URL for pagination links.
        project_id: UUID of the project whose flows are listed.  400 if the value
                    is not a valid UUID; 404 if the project does not exist.
        service:    Injected ProjectService instance.
        limit:      Maximum number of flows to return (default 100).
        offset:     Number of flows to skip for pagination (default 0).
        name:       Case-insensitive substring filter on flow name.
        tags:       Any-match tag filter — flows must carry at least one of these tags.
        is_hidden:  Visibility filter; None returns flows regardless of visibility.

    Returns:
        PaginatedProjectFlowResponse with flows, total_count, offset, limit,
        and first/next/prev navigation links.
    """
    logger.debug("Listing flows for project %s (offset=%d limit=%d, is_elyra=%s)", project_id, offset, limit, is_elyra)

    flows, summaries, total = service.get_project_flows_with_run_summary(
        project_id=project_id,
        skip=offset,
        limit=limit,
        name_filter=name,
        tags_filter=tags,
        is_hidden=is_hidden,
        is_elyra=is_elyra,
    )

    first_link = str(request.url.include_query_params(offset=0, limit=limit))
    next_link = (
        str(request.url.include_query_params(offset=offset + limit, limit=limit))
        if (offset + len(flows)) < total
        else None
    )
    prev_link = (
        str(request.url.include_query_params(offset=max(0, offset - limit), limit=limit)) if offset > 0 else None
    )

    logger.info("Listed %d flows for project %s (total=%d)", len(flows), project_id, total)
    return PaginatedProjectFlowResponse(
        flows=[
            ProjectFlowMapper.to_dto(flow=f, summary=summaries.get(f.flow_id) if f.flow_id else None) for f in flows
        ],
        total_count=total,
        offset=offset,
        limit=limit,
        first=first_link,
        next=next_link,
        prev=prev_link,
    )
