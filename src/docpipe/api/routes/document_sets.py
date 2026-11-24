# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Document set management API routes."""

# Import to trigger adapter registration
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

import docpipe.core.assets.document_sets.adapters.duckdb  # noqa: F401
from docpipe.api.auth.guards import require_role
from docpipe.api.auth.roles import Role
from docpipe.api.dependencies import get_document_set_service
from docpipe.api.dto.document_set_dto import (
    DocumentSetCreateRequest,
    DocumentSetListResponse,
    DocumentSetPreviewResponse,
    DocumentSetResponse,
    DocumentSetUpdateRequest,
)
from docpipe.api.dto.error_dto import ErrorResponse
from docpipe.api.dto.field_definitions import (
    OFFSET_MAX,
    OFFSET_MIN,
    UUID_LENGTH,
    UUID_PATTERN,
)
from docpipe.api.routes.document_set_utils import (
    document_set_to_response,
    table_to_preview_response,
)
from docpipe.core.assets.document_sets.application.services.document_set_service import (
    DocumentSetService,
)
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

document_sets_router = APIRouter(prefix="/document-sets", tags=["document-sets"])

# Path parameter type definitions
DocumentSetIdPath = Annotated[
    str,
    Path(
        description="Unique identifier for the document set",
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
        description="Maximum number of items to return",
        ge=1,
        le=1000,
        examples=[100],
        json_schema_extra={"format": "int32"},
    ),
]

OffsetQuery = Annotated[
    int,
    Query(
        description="Number of items to skip",
        ge=OFFSET_MIN,
        le=OFFSET_MAX,
        examples=[0],
        json_schema_extra={"format": "int32"},
    ),
]

DeleteDataQuery = Annotated[
    bool,
    Query(
        description="Whether to delete the underlying stored document data as well as metadata",
        examples=[True],
    ),
]


def get_pagination_params(
    *,
    limit: LimitQuery = 100,
    offset: OffsetQuery = 0,
) -> tuple[int, int]:
    """Extract and validate pagination parameters."""
    return limit, offset


# Dependency injection now handled in api/dependencies.py
DocumentSetServiceDep = Annotated[DocumentSetService, Depends(get_document_set_service)]
PaginationDep = Annotated[tuple[int, int], Depends(get_pagination_params)]


@document_sets_router.post(
    "",
    dependencies=[Depends(require_role(Role.EDITOR))],
    response_model=DocumentSetResponse,
    status_code=201,
    operation_id="create_document_set",
    summary="Create or retrieve a document set (idempotent)",
    responses={
        201: {
            "description": "Document set created or retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "id": "550e8400-e29b-41d4-a716-446655440000",
                        "name": "Research Documents",
                        "description": "Collection of research papers and reports.",
                        "storage_backend": "duckdb",
                        "database_path": "document_sets.duckdb",
                        "table_name": "research_documents",
                        "total_documents": 0,
                        "total_size_bytes": 0,
                        "total_pages": 0,
                        "created_at": "2026-04-01T11:00:00Z",
                        "updated_at": "2026-04-01T11:00:00Z",
                        "metadata": {"source": "research_portal"},
                    }
                }
            },
        },
        400: {
            "model": ErrorResponse,
            "description": "Invalid request data or validation error",
        },
        500: {
            "model": ErrorResponse,
            "description": "Internal server error",
        },
    },
)
async def create_document_set(
    request: Request,
    payload: DocumentSetCreateRequest,
    service: DocumentSetServiceDep,
) -> DocumentSetResponse:
    """Create or retrieve a document set (idempotent operation).

    This endpoint implements a get-or-create pattern: if a document set with
    the given name already exists, it will be returned. Otherwise, a new one
    will be created. This makes the operation safe for repeated calls with
    the same name.
    """
    logger.debug("Creating or retrieving document set: %s", payload.name)
    document_set = service.create_document_set(
        name=payload.name,
        description=payload.description,
        metadata=payload.metadata,
    )
    attachment_ref = service.get_attachment_ref(document_set_id=document_set.asset_id)
    logger.info("Successfully created or retrieved document set %s", document_set.asset_id)
    return document_set_to_response(document_set=document_set, attachment_ref=attachment_ref)


@document_sets_router.get(
    "/{document_set_id}",
    response_model=DocumentSetResponse,
    operation_id="get_document_set",
    summary="Get document set by ID",
    responses={
        200: {
            "description": "Document set retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "id": "550e8400-e29b-41d4-a716-446655440000",
                        "name": "Research Documents",
                        "description": "Collection of research papers and reports.",
                        "storage_backend": "duckdb",
                        "database_path": "document_sets.duckdb",
                        "table_name": "research_documents",
                        "total_documents": 125,
                        "total_size_bytes": 1048576,
                        "total_pages": 820,
                        "created_at": "2026-04-01T11:00:00Z",
                        "updated_at": "2026-04-01T11:30:00Z",
                        "metadata": {"source": "research_portal", "team": "nlp"},
                    }
                }
            },
        },
        400: {"model": ErrorResponse, "description": "Validation error"},
        404: {"model": ErrorResponse, "description": "Document set not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def get_document_set(
    service: DocumentSetServiceDep,
    document_set_id: DocumentSetIdPath,
) -> DocumentSetResponse:
    """Retrieve a document set by ID."""
    logger.debug("Retrieving document set: %s", document_set_id)
    document_set = service.get_document_set(document_set_id=document_set_id)
    attachment_ref = service.get_attachment_ref(document_set_id=document_set_id)
    logger.info("Successfully retrieved document set %s", document_set_id)
    return document_set_to_response(document_set=document_set, attachment_ref=attachment_ref)


@document_sets_router.get(
    "",
    response_model=DocumentSetListResponse,
    operation_id="list_document_sets",
    summary="List document sets with pagination",
    responses={
        200: {
            "description": "Document sets retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "items": [
                            {
                                "id": "550e8400-e29b-41d4-a716-446655440000",
                                "name": "Research Documents",
                                "description": "Collection of research papers and reports.",
                                "storage_backend": "duckdb",
                                "database_path": "document_sets.duckdb",
                                "table_name": "research_documents",
                                "total_documents": 125,
                                "total_size_bytes": 1048576,
                                "total_pages": 820,
                                "created_at": "2026-04-01T11:00:00Z",
                                "updated_at": "2026-04-01T11:30:00Z",
                                "metadata": {"source": "research_portal", "team": "nlp"},
                            }
                        ],
                        "total": 1,
                        "limit": 100,
                        "offset": 0,
                    }
                }
            },
        },
        400: {"model": ErrorResponse, "description": "Validation error"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def list_document_sets(
    request: Request,
    service: DocumentSetServiceDep,
    pagination: PaginationDep,
) -> DocumentSetListResponse:
    """List document sets with offset-based pagination."""
    limit, offset = pagination
    logger.debug("Listing document sets: offset=%s limit=%s", offset, limit)
    items = service.list_document_sets(limit=limit, offset=offset)
    logger.info("Successfully retrieved %s document sets", len(items))
    return DocumentSetListResponse(
        items=[
            document_set_to_response(
                document_set=item,
                attachment_ref=service.get_attachment_ref(document_set_id=item.asset_id),
            )
            for item in items
        ],
        total=len(items),
        limit=limit,
        offset=offset,
    )


@document_sets_router.patch(
    "/{document_set_id}",
    dependencies=[Depends(require_role(Role.EDITOR))],
    response_model=DocumentSetResponse,
    operation_id="update_document_set",
    summary="Update document set metadata",
    responses={
        200: {
            "description": "Document set updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "id": "550e8400-e29b-41d4-a716-446655440000",
                        "name": "Research Documents",
                        "description": "Updated document set description.",
                        "storage_backend": "duckdb",
                        "database_path": "document_sets.duckdb",
                        "table_name": "research_documents",
                        "total_documents": 125,
                        "total_size_bytes": 1048576,
                        "total_pages": 820,
                        "created_at": "2026-04-01T11:00:00Z",
                        "updated_at": "2026-04-01T11:35:00Z",
                        "metadata": {"version": "2.0", "owner": "platform-team"},
                    }
                }
            },
        },
        400: {"model": ErrorResponse, "description": "Validation error"},
        404: {"model": ErrorResponse, "description": "Document set not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def update_document_set(
    payload: DocumentSetUpdateRequest,
    service: DocumentSetServiceDep,
    document_set_id: DocumentSetIdPath,
) -> DocumentSetResponse:
    """Update mutable document set metadata fields."""
    logger.debug("Updating document set: %s", document_set_id)
    updated_document_set = service.update_document_set(
        document_set_id=document_set_id,
        description=payload.description,
        metadata=payload.metadata,
    )
    attachment_ref = service.get_attachment_ref(document_set_id=document_set_id)
    logger.info("Successfully updated document set %s", document_set_id)
    return document_set_to_response(document_set=updated_document_set, attachment_ref=attachment_ref)


@document_sets_router.delete(
    "/{document_set_id}",
    dependencies=[Depends(require_role(Role.EDITOR))],
    status_code=204,
    operation_id="delete_document_set",
    summary="Delete a document set",
    responses={
        204: {
            "description": "Document set deleted successfully (no content returned)",
        },
        400: {"model": ErrorResponse, "description": "Validation error"},
        404: {"model": ErrorResponse, "description": "Document set not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def delete_document_set(
    request: Request,
    service: DocumentSetServiceDep,
    document_set_id: DocumentSetIdPath,
    delete_data: DeleteDataQuery = True,
) -> None:
    """Delete a document set and optionally its stored data.

    Returns HTTP 204 No Content on successful deletion following REST conventions.
    """
    logger.debug("Deleting document set: %s delete_data=%s", document_set_id, delete_data)
    service.delete_document_set(document_set_id=document_set_id, delete_data=delete_data)
    logger.info("Successfully deleted document set %s", document_set_id)


@document_sets_router.get(
    "/{document_set_id}/preview",
    response_model=DocumentSetPreviewResponse,
    operation_id="preview_document_set_data",
    summary="Preview document set data",
    responses={
        200: {
            "description": "Document set preview retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "columns": ["doc_id", "title", "content", "size_bytes"],
                        "data": [
                            {
                                "doc_id": "doc-001",
                                "title": "Research Paper A",
                                "content": "Abstract of research paper...",
                                "size_bytes": 15360,
                            },
                            {
                                "doc_id": "doc-002",
                                "title": "Research Paper B",
                                "content": "Abstract of another paper...",
                                "size_bytes": 18432,
                            },
                        ],
                        "total_rows": 2,
                    }
                }
            },
        },
        400: {"model": ErrorResponse, "description": "Validation error"},
        404: {"model": ErrorResponse, "description": "Document set not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def preview_document_set_data(
    request: Request,
    service: DocumentSetServiceDep,
    pagination: PaginationDep,
    document_set_id: DocumentSetIdPath,
) -> DocumentSetPreviewResponse:
    """Preview stored document set rows using offset-based pagination."""
    limit, offset = pagination
    logger.debug(
        "Previewing document set data: document_set_id=%s offset=%s limit=%s",
        document_set_id,
        offset,
        limit,
    )
    table = service.preview_data(document_set_id=document_set_id, limit=limit, offset=offset)
    logger.info(
        "Successfully retrieved preview for document set %s with %s rows",
        document_set_id,
        table.num_rows,
    )
    return table_to_preview_response(table=table)
