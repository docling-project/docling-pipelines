"""Flow management API routes.

This module provides REST API endpoints for flow management operations including
create, read, update, delete, and list flows. It follows hexagonal architecture
with DTOs for API serialization and domain models for business logic.

Error Handling Strategy:
All endpoints delegate to service layer which raises custom DocpipeException subclasses:
- FlowNotFoundException (404): Flow not found
- FlowAlreadyExistsException (409): Duplicate flow name
- FlowInvalidDataException (400): Invalid flow data or validation failure
- FlowStorageException (500): File system errors
- Error handler middleware converts DocpipeException to ErrorResponse DTO format
- All errors logged with transaction ID for request tracing
"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request

from docpipe.api.dependencies import get_flow_service
from docpipe.api.dto.authoring_flow_dto import (
    AuthoringFlowCreateRequest,
    AuthoringFlowResponse,
    AuthoringFlowUpdateRequest,
    PaginatedAuthoringFlowResponse,
)
from docpipe.api.dto.error_dto import ErrorResponse
from docpipe.api.dto.field_definitions import (
    LIMIT_MAX,
    LIMIT_MIN,
    NAME_MAX_LENGTH,
    NAME_MIN_LENGTH,
    OFFSET_MAX,
    OFFSET_MIN,
    UUID_LENGTH,
    UUID_PATTERN,
)
from docpipe.api.dto.flow_dto import (
    BulkDeleteResponse,
    ElyraFlowCreateRequest,
    ElyraFlowUpdateRequest,
    FlowResponse,
    PaginatedFlowResponse,
)
from docpipe.api.dto.mappers.flow_mapper import FlowMapper
from docpipe.core.assets.flows.application.services.flow_service import FlowService
from docpipe.core.assets.flows.domain.models.authoring_flow import AuthoringFlow

# Configure logging
logger = logging.getLogger(__name__)

# Create router
flows_router = APIRouter(prefix="/flows", tags=["Flows"])

# Path parameter type definitions
FlowIdPath = Annotated[
    str,
    Path(
        description="Unique identifier for the flow",
        min_length=UUID_LENGTH,
        max_length=UUID_LENGTH,
        pattern=UUID_PATTERN,
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    ),
]

# Query parameter type definitions
LimitQuery = Annotated[
    int,
    Query(
        description="Maximum number of flows to return",
        ge=LIMIT_MIN,
        le=LIMIT_MAX,
        examples=[100],
        json_schema_extra={"format": "int32"},
    ),
]

OffsetQuery = Annotated[
    int,
    Query(
        description="Number of flows to skip",
        ge=OFFSET_MIN,
        le=OFFSET_MAX,
        examples=[0],
        json_schema_extra={"format": "int32"},
    ),
]

NameQuery = Annotated[
    str | None,
    Query(
        description="Filter flows by name (partial match)",
        min_length=NAME_MIN_LENGTH,
        max_length=NAME_MAX_LENGTH,
        examples=["my-flow"],
        json_schema_extra={
            "minLength": NAME_MIN_LENGTH,
            "maxLength": NAME_MAX_LENGTH,
        },
    ),
]

TagsQuery = Annotated[
    list[str] | None,
    Query(
        description="Filter flows by tags",
        examples=[["production", "ml-pipeline"]],
        json_schema_extra={
            "minItems": 0,
            "maxItems": 100,
            "items": {
                "type": "string",
                "minLength": 1,
                "maxLength": 64,
                "pattern": r"^[A-Za-z0-9._:/# -]+$",
            },
        },
    ),
]

IsHiddenQuery = Annotated[
    bool | None,
    Query(
        description="Filter by visibility status",
        examples=[False],
    ),
]

IsElyraQuery = Annotated[
    bool,
    Query(
        description="Indicates if the flow is in Elyra format. Defaults to False for DAG format.",
        examples=[False, True],
    ),
]

FlowIdsQuery = Annotated[
    str,
    Query(
        description="Comma-separated list of flow IDs to delete",
        pattern=r"^[a-zA-Z0-9_-]+(,[a-zA-Z0-9_-]+)*$",
        examples=["flow-id-1,flow-id-2,flow-id-3"],
    ),
]


# Dependency functions for parameter extraction
def get_flow_id(flow_id: FlowIdPath) -> str:
    """Extract and validate flow ID from path parameter.

    Args:
        flow_id: Flow identifier from path

    Returns:
        Validated flow ID

    Raises:
        400: If flow_id is not a valid UUID format (handled by validation_exception_handler)
    """
    return flow_id


def get_pagination_params(
    limit: LimitQuery = 100,
    offset: OffsetQuery = 0,
) -> tuple[int, int]:
    """Extract and validate pagination parameters.

    Args:
        limit: Maximum number of results
        offset: Number of results to skip

    Returns:
        Tuple of (limit, offset)

    Raises:
        400: If parameters are out of valid range (handled by validation_exception_handler)
    """
    return limit, offset


def get_filter_params(
    name: NameQuery = None,
    tags: TagsQuery = None,
    is_hidden: IsHiddenQuery = None,
) -> dict:
    """Extract and validate filter parameters.

    Args:
        name: Flow name filter
        tags: Flow tags filter
        is_hidden: Visibility filter

    Returns:
        Dictionary of filter parameters
    """
    return {
        "name": name,
        "tags": tags,
        "is_hidden": is_hidden,
    }


# Type alias for dependency injection
PaginationDep = Annotated[tuple[int, int], Depends(get_pagination_params)]
FiltersDep = Annotated[dict, Depends(get_filter_params)]
FlowServiceDep = Annotated[FlowService, Depends(get_flow_service)]


@flows_router.post(
    "",
    response_model=FlowResponse | AuthoringFlowResponse,
    status_code=201,
    operation_id="create_flow",
    summary="Create a new flow",
    responses={
        201: {
            "description": "Flow created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "flow_id": "550e8400-e29b-41d4-a716-446655440000",
                        "name": "Invoice Processing Pipeline",
                        "description": "Extracts entities from invoices",
                        "definition": {"doc_type": "pipeline", "pipelines": []},
                        "tags": ["invoice", "extraction"],
                        "container_kind": "project",
                        "container_id": "123e4567-e89b-12d3-a456-426614174000",
                        "is_hidden": False,
                        "flow_version": "2.0",
                        "created_on": "2026-04-01T11:00:00Z",
                        "modified_on": "2026-04-01T11:00:00Z",
                        "job_id": None,
                        "created_by": "user@example.com",
                        "modified_by": None,
                        "href": "/api/v1/flows/550e8400-e29b-41d4-a716-446655440000",
                    }
                }
            },
        },
        400: {
            "model": ErrorResponse,
            "description": "Invalid request data or validation error",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [
                            {
                                "code": "validation_error",
                                "message": "Field 'name' is required and cannot be empty",
                                "target": {"type": "field", "name": "name"},
                            },
                            {
                                "code": "validation_error",
                                "message": "Field 'definition' must be a valid JSON object",
                                "target": {"type": "field", "name": "definition"},
                            },
                        ],
                        "trace": "req-flow-create-400",
                        "status_code": 400,
                    }
                }
            },
        },
        409: {
            "model": ErrorResponse,
            "description": "Flow already exists",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [
                            {
                                "code": "conflict",
                                "message": "A flow named 'customer-onboarding' already exists",
                                "target": {"type": "field", "name": "name"},
                            }
                        ],
                        "trace": "req-flow-create-409",
                        "status_code": 409,
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
                        "errors": [
                            {
                                "code": "internal_error",
                                "message": "An unexpected error occurred while creating the flow",
                            }
                        ],
                        "trace": "req-flow-create-500",
                        "status_code": 500,
                    }
                }
            },
        },
    },
)
async def create_flow(
    request: Request,
    body: dict,
    service: FlowServiceDep,
    is_elyra: IsElyraQuery = False,
):
    """Create and store a new flow.

    Accepts either Elyra format (UI) or Authoring format (API) based on is_elyra parameter.

    Args:
        request: FastAPI request object
        body: Raw dict containing flow definition (validated based on is_elyra)
        service: Injected flow service instance
        is_elyra: Query parameter indicating if flow is in Elyra format (default: False)

    Returns:
        AuthoringFlowResponse | FlowResponse: The stored flow with generated metadata
            (format matches input format)

    Raises:
        HTTPException: If flow creation fails (400, 409, 500)
    """
    logger.debug("Creating flow, is_elyra: %s", is_elyra)

    if is_elyra:
        # Validate as Elyra format (UI)
        flow_dto = ElyraFlowCreateRequest(**body)
        domain_flow = FlowMapper.create_request_to_domain(flow_dto)
    else:
        # Validate as Authoring format (API)
        authoring_dto = AuthoringFlowCreateRequest(**body)

        # Parse and validate authoring format
        authoring_flow = AuthoringFlow.from_dict(data=authoring_dto.model_dump())
        authoring_flow.validate()

        # Conversion to runtime DAG will happen at execution time
        from docpipe.core.assets.flows.domain.models.flow import Flow

        domain_flow = Flow(
            asset_id=None,  # Will be generated
            name=authoring_flow.flow_name,
            description=authoring_dto.description,
            definition=authoring_dto.model_dump(),  # Store validated authoring format
            tags=authoring_dto.tags or [],
            is_hidden=False,
            container_kind=None,
            container_id=None,
        )

    logger.debug("Converted to domain model: %s", domain_flow.name)

    # Create flow using service - store in original format
    created_flow = service.create_flow(flow=domain_flow, is_elyra=is_elyra)

    logger.info("Successfully created flow %s", created_flow.flow_id)

    # Convert domain model back to appropriate DTO based on format
    if is_elyra:
        return FlowMapper.domain_to_dto(created_flow)
    return FlowMapper.domain_to_authoring_dto(domain=created_flow)


@flows_router.get(
    "/{flow_id}",
    response_model=FlowResponse | AuthoringFlowResponse,
    operation_id="get_flow",
    summary="Get flow by ID",
    responses={
        200: {
            "description": "Flow retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "flow_id": "550e8400-e29b-41d4-a716-446655440000",
                        "name": "Invoice Processing Pipeline",
                        "description": "Extracts entities from invoices",
                        "definition": {"doc_type": "pipeline", "pipelines": []},
                        "tags": ["invoice", "extraction"],
                        "container_kind": "project",
                        "container_id": "123e4567-e89b-12d3-a456-426614174000",
                        "is_hidden": False,
                        "flow_version": "2.0",
                        "created_on": "2026-04-01T11:00:00Z",
                        "modified_on": "2026-04-01T11:00:00Z",
                        "job_id": None,
                        "created_by": "user@example.com",
                        "modified_by": None,
                        "href": "/api/v1/flows/550e8400-e29b-41d4-a716-446655440000",
                    }
                }
            },
        },
        400: {
            "model": ErrorResponse,
            "description": "Validation error - invalid parameter format",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [
                            {
                                "code": "validation_error",
                                "message": "flow_id must be a valid UUID format",
                                "target": {"type": "parameter", "name": "flow_id"},
                            }
                        ],
                        "trace": "req-flow-get-400",
                        "status_code": 400,
                    }
                }
            },
        },
        404: {
            "model": ErrorResponse,
            "description": "Flow not found",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [
                            {
                                "code": "not_found",
                                "message": "Flow with ID '550e8400-e29b-41d4-a716-446655440000' not found",
                            }
                        ],
                        "trace": "req-flow-get-404",
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
                        "errors": [
                            {
                                "code": "internal_error",
                                "message": "An unexpected error occurred while retrieving the flow",
                            }
                        ],
                        "trace": "req-flow-get-500",
                        "status_code": 500,
                    }
                }
            },
        },
    },
)
async def get_flow(
    service: FlowServiceDep,
    flow_id: str = Depends(get_flow_id),
):
    """Retrieve a flow by ID.

    Returns the flow in its original format (authoring or Elyra) based on
    how it was created. Authoring format flows return flat structure with metadata,
    Elyra format flows return wrapped structure.

    Args:
        flow_id: UUID of the flow to retrieve (validated via dependency)
        service: Injected flow service instance

    Returns:
        AuthoringFlowResponse | FlowResponse: The requested flow in original format

    Raises:
        HTTPException: If flow not found or read fails (404, 400, 500)
    """
    from docpipe.core.constants.constants import DocpipeConstants

    logger.debug("Retrieving flow: %s", flow_id)

    # Get flow using service - service raises typed exceptions
    domain_flow = service.get_flow(flow_id)

    logger.info("Successfully retrieved flow %s", flow_id)

    # Detect format and return appropriate DTO
    if DocpipeConstants.FLOW_NAME in domain_flow.definition:
        # Authoring format - return flat structure with metadata
        return FlowMapper.domain_to_authoring_dto(domain=domain_flow)
    # Elyra format - return wrapped structure
    return FlowMapper.domain_to_dto(domain_flow)


@flows_router.get(
    "",
    response_model=PaginatedFlowResponse | PaginatedAuthoringFlowResponse,
    operation_id="list_flows",
    summary="List flows with pagination and format filtering",
    responses={
        200: {
            "description": "Flows retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "flows": [
                            {
                                "flow_id": "550e8400-e29b-41d4-a716-446655440000",
                                "name": "Invoice Processing Pipeline",
                                "description": "Extracts entities from invoices",
                                "definition": {"doc_type": "pipeline", "pipelines": []},
                                "tags": ["invoice", "extraction"],
                                "container_kind": "project",
                                "container_id": "123e4567-e89b-12d3-a456-426614174000",
                                "is_hidden": False,
                                "flow_version": "2.0",
                                "created_on": "2026-04-01T11:00:00Z",
                                "modified_on": "2026-04-01T11:00:00Z",
                                "job_id": None,
                                "created_by": "user@example.com",
                                "modified_by": None,
                                "href": "/api/v1/flows/550e8400-e29b-41d4-a716-446655440000",
                            }
                        ],
                        "total_count": 1,
                        "offset": 0,
                        "limit": 100,
                        "first": "/api/v1/flows?offset=0&limit=100",
                        "next": None,
                        "prev": None,
                    }
                }
            },
        },
        400: {
            "model": ErrorResponse,
            "description": "Validation error - invalid query parameters",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [
                            {
                                "code": "validation_error",
                                "message": "limit must be between 1 and 1000",
                                "target": {"type": "parameter", "name": "limit"},
                            }
                        ],
                        "trace": "req-flow-list-400",
                        "status_code": 400,
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
                        "errors": [
                            {
                                "code": "internal_error",
                                "message": "An unexpected error occurred while listing flows",
                            }
                        ],
                        "trace": "req-flow-list-500",
                        "status_code": 500,
                    }
                }
            },
        },
    },
)
async def list_flows(
    request: Request,
    service: FlowServiceDep,
    pagination: PaginationDep,
    filters: FiltersDep,
    is_elyra: bool | None = Query(
        default=None,
        description="Filter by format: true=Elyra only, false=Authoring only, null=Authoring only (default)",
    ),
):
    """List flows with pagination, filtering, and format selection.

    Format filtering behavior:
    - No parameter or is_elyra=false: Returns only authoring format flows
    - is_elyra=true: Returns only Elyra format flows

    Args:
        request: FastAPI request object
        service: Injected flow service instance
        pagination: Tuple of (limit, offset) from dependency
        filters: Dictionary of filter parameters from dependency
        is_elyra: Format filter (None or False=authoring, True=Elyra)

    Returns:
        PaginatedAuthoringFlowResponse | PaginatedFlowResponse: Paginated list based on format

    Raises:
        HTTPException: If list operation fails (400, 500)
    """
    limit, offset = pagination
    name = filters["name"]
    tags = filters["tags"]
    is_hidden = filters["is_hidden"]

    # Default to authoring format if not specified
    if is_elyra is None:
        is_elyra = False

    logger.debug(
        "Listing flows: offset=%s, limit=%s, name=%s, tags=%s, is_hidden=%s, is_elyra=%s",
        offset,
        limit,
        name,
        tags,
        is_hidden,
        is_elyra,
    )

    # Get flows and total — format filter applied inside the service before pagination
    flows = service.list_flows(
        skip=offset, limit=limit, name_filter=name, tags_filter=tags, is_hidden=is_hidden, is_elyra=is_elyra
    )
    total = service.count_flows(name_filter=name, tags_filter=tags, is_hidden=is_hidden, is_elyra=is_elyra)

    logger.info("Successfully retrieved %s flows (format: %s)", len(flows), "Elyra" if is_elyra else "Authoring")

    # Generate pagination links
    base_url = str(request.url).split("?")[0]
    format_param = f"&is_elyra={is_elyra}" if is_elyra else ""
    first_link = f"{base_url}?offset=0&limit={limit}{format_param}"
    next_link = (
        f"{base_url}?offset={offset + limit}&limit={limit}{format_param}" if (offset + len(flows)) < total else None
    )
    prev_link = f"{base_url}?offset={max(0, offset - limit)}&limit={limit}{format_param}" if offset > 0 else None

    # Convert domain models to appropriate DTOs based on format
    if is_elyra:
        return PaginatedFlowResponse(
            flows=[FlowMapper.domain_to_dto(flow) for flow in flows],
            total_count=total,
            offset=offset,
            limit=limit,
            first=first_link,
            next=next_link,
            prev=prev_link,
        )
    return PaginatedAuthoringFlowResponse(
        flows=[FlowMapper.domain_to_authoring_dto(domain=flow) for flow in flows],
        total_count=total,
        offset=offset,
        limit=limit,
        first=first_link,
        next=next_link,
        prev=prev_link,
    )


@flows_router.put(
    "/{flow_id}",
    response_model=FlowResponse | AuthoringFlowResponse,
    operation_id="replace_flow",
    summary="Update a flow",
    responses={
        200: {
            "description": "Flow updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "flow_id": "550e8400-e29b-41d4-a716-446655440000",
                        "name": "Updated Invoice Pipeline",
                        "description": "Updated description",
                        "definition": {"doc_type": "pipeline", "pipelines": []},
                        "tags": ["invoice", "extraction", "updated"],
                        "container_kind": "project",
                        "container_id": "123e4567-e89b-12d3-a456-426614174000",
                        "is_hidden": False,
                        "flow_version": "2.0",
                        "created_on": "2026-04-01T11:00:00Z",
                        "modified_on": "2026-04-01T12:00:00Z",
                        "job_id": None,
                        "created_by": "user@example.com",
                        "modified_by": "user@example.com",
                        "href": "/api/v1/flows/550e8400-e29b-41d4-a716-446655440000",
                    }
                }
            },
        },
        400: {
            "model": ErrorResponse,
            "description": "Invalid request data, validation error, or invalid parameter format",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [
                            {
                                "code": "validation_error",
                                "message": "Field 'definition' must contain at least one node",
                                "target": {"type": "field", "name": "definition"},
                            },
                        ],
                        "trace": "req-flow-update-400",
                        "status_code": 400,
                    }
                }
            },
        },
        404: {
            "model": ErrorResponse,
            "description": "Flow not found",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [
                            {
                                "code": "not_found",
                                "message": "Flow with ID '550e8400-e29b-41d4-a716-446655440000' not found",
                            }
                        ],
                        "trace": "req-flow-update-404",
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
                        "errors": [
                            {
                                "code": "internal_error",
                                "message": "An unexpected error occurred while updating the flow",
                            }
                        ],
                        "trace": "req-flow-update-500",
                        "status_code": 500,
                    }
                }
            },
        },
    },
)
async def update_flow(
    body: dict[str, Any],
    service: FlowServiceDep,
    flow_id: str = Depends(get_flow_id),
    is_elyra: IsElyraQuery = False,
):
    """Update an existing flow (full replacement).

    Accepts either Elyra format (UI) or Authoring format (API) based on is_elyra parameter.

    Args:
        body: Raw request body dict (validated based on is_elyra parameter)
        service: Injected flow service instance
        flow_id: UUID of the flow to update (validated via dependency)
        is_elyra: Query parameter indicating if flow is in Elyra format (default: False)

    Returns:
        AuthoringFlowResponse | FlowResponse: The updated flow
            (format matches input format)

    Raises:
        HTTPException: If flow not found or update fails (404, 400, 500)
    """
    logger.debug("Updating flow: %s, is_elyra: %s", flow_id, is_elyra)

    if is_elyra:
        # Validate as Elyra format (UI)
        flow = ElyraFlowCreateRequest(**body)
        domain_flow = FlowMapper.create_request_to_domain(flow)
    else:
        # Validate as Authoring format (API)
        flow = AuthoringFlowCreateRequest(**body)

        # Parse and validate authoring format
        authoring_flow = AuthoringFlow.from_dict(data=flow.model_dump())
        authoring_flow.validate()

        from docpipe.core.assets.flows.domain.models.flow import Flow

        domain_flow = Flow(
            asset_id=None,  # Will be set below
            name=authoring_flow.flow_name,
            description=flow.description,
            definition=flow.model_dump(),  # Store complete authoring format
            tags=flow.tags or [],
            is_hidden=False,
            container_kind=None,
            container_id=None,
        )

    # Ensure flow_id matches
    domain_flow.flow_id = flow_id

    # Update flow using service - service raises typed exceptions
    updated_flow = service.update_flow(domain_flow)

    logger.info("Successfully updated flow %s", flow_id)

    # Convert domain model back to appropriate DTO based on format
    if is_elyra:
        return FlowMapper.domain_to_dto(updated_flow)
    return FlowMapper.domain_to_authoring_dto(domain=updated_flow)


@flows_router.patch(
    "/{flow_id}",
    response_model=FlowResponse | AuthoringFlowResponse,
    operation_id="update_flow",
    summary="Partially update a flow",
    responses={
        200: {
            "description": "Flow partially updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "flow_id": "550e8400-e29b-41d4-a716-446655440000",
                        "name": "Invoice Processing Pipeline",
                        "description": "Extracts entities from invoices",
                        "definition": {"doc_type": "pipeline", "pipelines": []},
                        "tags": ["invoice", "extraction", "updated"],
                        "container_kind": "project",
                        "container_id": "123e4567-e89b-12d3-a456-426614174000",
                        "is_hidden": False,
                        "flow_version": "2.0",
                        "created_on": "2026-04-01T11:00:00Z",
                        "modified_on": "2026-04-01T12:30:00Z",
                        "job_id": None,
                        "created_by": "user@example.com",
                        "modified_by": "user@example.com",
                        "href": "/api/v1/flows/550e8400-e29b-41d4-a716-446655440000",
                    }
                }
            },
        },
        400: {
            "model": ErrorResponse,
            "description": "Invalid request data, validation error, or invalid parameter format",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [
                            {
                                "code": "validation_error",
                                "message": "Field 'tags' must be an array of strings",
                                "target": {"type": "field", "name": "tags"},
                            },
                        ],
                        "trace": "req-flow-patch-400",
                        "status_code": 400,
                    }
                }
            },
        },
        404: {
            "model": ErrorResponse,
            "description": "Flow not found",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [
                            {
                                "code": "not_found",
                                "message": "Flow with ID '550e8400-e29b-41d4-a716-446655440000' not found",
                            }
                        ],
                        "trace": "req-flow-patch-404",
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
                        "errors": [
                            {
                                "code": "internal_error",
                                "message": "An unexpected error occurred while partially updating the flow",
                            }
                        ],
                        "trace": "req-flow-patch-500",
                        "status_code": 500,
                    }
                }
            },
        },
    },
)
async def partial_update_flow(
    request: Request,
    body: dict[str, Any],
    service: FlowServiceDep,
    flow_id: str = Depends(get_flow_id),
    is_elyra: IsElyraQuery = False,
):
    """Partially update a flow (only provided fields).

    Accepts either Elyra format (UI) or Authoring format (API) based on is_elyra parameter.

    Args:
        request: FastAPI request object
        body: Raw request body dict (validated based on is_elyra parameter)
        service: Injected flow service instance
        flow_id: UUID of the flow to update (validated via dependency)
        is_elyra: Query parameter indicating if flow is in Elyra format (default: False)

    Returns:
        AuthoringFlowResponse | FlowResponse: The updated flow
            (format matches input format)

    Raises:
        HTTPException: If flow not found or update fails (404, 400, 500)
    """
    logger.debug("Partially updating flow: %s, is_elyra: %s", flow_id, is_elyra)

    # Validate based on format
    if is_elyra:
        updates = ElyraFlowUpdateRequest(**body)
    else:
        updates = AuthoringFlowUpdateRequest(**body)

    # Pass dict directly to service - service handles transformation
    updated_flow = service.partial_update_flow(flow_id, updates.dict(exclude_unset=True))

    logger.info("Successfully partially updated flow %s", flow_id)

    # Convert domain model back to appropriate DTO based on format
    if is_elyra:
        return FlowMapper.domain_to_dto(updated_flow)
    return FlowMapper.domain_to_authoring_dto(domain=updated_flow)


@flows_router.delete(
    "/{flow_id}",
    status_code=204,
    operation_id="delete_flow",
    summary="Delete a flow",
    responses={
        204: {"description": "Flow deleted successfully"},
        400: {
            "model": ErrorResponse,
            "description": "Validation error - invalid parameter format",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [
                            {
                                "code": "validation_error",
                                "message": "flow_id must be a valid UUID format",
                                "target": {"type": "parameter", "name": "flow_id"},
                            }
                        ],
                        "trace": "req-flow-delete-400",
                        "status_code": 400,
                    }
                }
            },
        },
        404: {
            "model": ErrorResponse,
            "description": "Flow not found",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [
                            {
                                "code": "not_found",
                                "message": "Flow with ID '550e8400-e29b-41d4-a716-446655440000' not found",
                            }
                        ],
                        "trace": "req-flow-delete-404",
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
                        "errors": [
                            {
                                "code": "internal_error",
                                "message": "An unexpected error occurred while deleting the flow",
                            }
                        ],
                        "trace": "req-flow-delete-500",
                        "status_code": 500,
                    }
                }
            },
        },
    },
)
async def delete_flow(
    request: Request,
    service: FlowServiceDep,
    flow_id: str = Depends(get_flow_id),
):
    """Delete a flow by ID.

    Args:
        request: FastAPI request object
        flow_id: UUID of the flow to delete (validated via dependency)
        service: Injected flow service instance

    Returns:
        No content on success

    Raises:
        HTTPException: If flow not found or delete fails (404, 400, 500)
    """
    logger.debug("Deleting flow: %s", flow_id)

    # Delete flow using service - service raises typed exceptions
    service.delete_flow(flow_id)

    logger.info("Successfully deleted flow %s", flow_id)

    # Return 204 No Content on success
    return


@flows_router.delete(
    "",
    response_model=BulkDeleteResponse,
    status_code=200,
    operation_id="bulk_delete_flows",
    summary="Delete multiple flows",
    responses={
        200: {
            "description": "Bulk delete completed",
            "content": {
                "application/json": {
                    "example": {
                        "deleted": ["550e8400-e29b-41d4-a716-446655440000"],
                        "failed": [{"flow_id": "123e4567-e89b-12d3-a456-426614174000", "error": "Flow not found"}],
                        "total_requested": 2,
                        "total_deleted": 1,
                        "total_failed": 1,
                    }
                }
            },
        },
        400: {
            "model": ErrorResponse,
            "description": "Invalid request data, validation error, or invalid parameter format",
            "content": {
                "application/json": {
                    "example": {
                        "errors": [
                            {
                                "code": "invalid_request",
                                "message": "The 'flow_ids' list cannot be empty",
                                "target": {"type": "parameter", "name": "flow_ids"},
                            },
                            {
                                "code": "validation_error",
                                "message": "Each value in 'flow_ids' must be a valid UUID",
                                "target": {"type": "parameter", "name": "flow_ids"},
                            },
                        ],
                        "trace": "req-flow-bulk-delete-400",
                        "status_code": 400,
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
                        "errors": [
                            {
                                "code": "internal_error",
                                "message": "An unexpected error occurred while deleting flows",
                            }
                        ],
                        "trace": "req-flow-bulk-delete-500",
                        "status_code": 500,
                    }
                }
            },
        },
    },
)
async def bulk_delete_flows(
    request: Request,
    service: FlowServiceDep,
    flow_ids: FlowIdsQuery,
):
    """Delete multiple flows by their IDs.

    Args:
        request: FastAPI request object
        flow_ids: Comma-separated string of flow UUIDs to delete
        service: Injected flow service instance

    Returns:
        Dictionary with deletion results:
            - deleted: List of successfully deleted flow_ids
            - failed: List of dicts with flow_id and error for failures
            - total_requested: Total number of flows requested for deletion
            - total_deleted: Count of successfully deleted flows
            - total_failed: Count of failed deletions

    Raises:
        HTTPException: If bulk delete operation fails (400, 500)
    """
    # Convert comma-separated string to list
    flow_id_list = [fid.strip() for fid in flow_ids.split(",") if fid.strip()]

    logger.debug("Bulk deleting %s flows", len(flow_id_list))

    # Architectural refactoring: Validation moved to service layer
    # Service layer now validates empty flow_ids list and raises FlowInvalidDataException
    result = service.bulk_delete_flows(flow_id_list)

    logger.info(
        "Bulk delete completed: %s deleted, %s failed out of %s requested",
        result["total_deleted"],
        result["total_failed"],
        result["total_requested"],
    )

    return result
