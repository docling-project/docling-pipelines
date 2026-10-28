"""Document Library management API routes.

This module provides REST API endpoints for document library management operations including
create, read, update, delete, and list libraries. It follows hexagonal architecture
with DTOs for API serialization and domain models for business logic.

Error Handling Strategy:
All endpoints delegate to service layer which raises custom DocpipeException subclasses:
- DocumentLibraryNotFoundException (404): Library not found
- DocumentLibraryAlreadyExistsException (409): Duplicate library name
- DocumentLibraryInvalidDataException (400): Invalid library data or validation failure
- DocumentLibraryStorageException (500): Database errors
- DocumentSetNotFoundException (404): Document set not found when managing relationships
- Error handler middleware converts DocpipeException to ErrorResponse DTO format
- All errors logged with transaction ID for request tracing
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response

from docpipe.api.dependencies import (
    get_document_library_service,
    get_document_set_service,
)
from docpipe.api.dto.document_library_dto import (
    DocumentLibrary as DocumentLibraryResponse,
)
from docpipe.api.dto.document_library_dto import (
    DocumentLibraryPatch,
    DocumentLibraryPrototype,
    DocumentSetsRetrieved,
)
from docpipe.api.dto.document_library_mapper import DocumentLibraryMapper
from docpipe.api.dto.error_dto import ErrorResponse
from docpipe.api.dto.field_definitions import (
    LIBRARY_NAME_MAX_LENGTH,
    LIBRARY_NAME_MIN_LENGTH,
    LIMIT_MAX,
    LIMIT_MIN,
    OFFSET_MAX,
    OFFSET_MIN,
    UUID_LENGTH,
    UUID_PATTERN,
)
from docpipe.core.assets.document_libraries.application.services.document_library_service import (
    DocumentLibraryService,
)
from docpipe.core.assets.document_sets.application.services.document_set_service import (
    DocumentSetService,
)

# Configure logging
logger = logging.getLogger(__name__)

# Create router
document_libraries_router = APIRouter(prefix="/document-libraries", tags=["document-libraries"])

# Path parameter type definitions
LibraryIdPath = Annotated[
    str,
    Path(
        description="Unique identifier for the document library",
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
        description="Maximum number of libraries to return",
        ge=LIMIT_MIN,
        le=LIMIT_MAX,
        examples=[100],
        json_schema_extra={"format": "int32"},
    ),
]

OffsetQuery = Annotated[
    int,
    Query(
        description="Number of libraries to skip",
        ge=OFFSET_MIN,
        le=OFFSET_MAX,
        examples=[0],
        json_schema_extra={"format": "int32"},
    ),
]

NameQuery = Annotated[
    str | None,
    Query(
        description="Filter libraries by name (partial match)",
        min_length=LIBRARY_NAME_MIN_LENGTH,
        max_length=LIBRARY_NAME_MAX_LENGTH,
        examples=["Research Papers"],
        json_schema_extra={
            "minLength": LIBRARY_NAME_MIN_LENGTH,
            "maxLength": LIBRARY_NAME_MAX_LENGTH,
        },
    ),
]


# Dependency functions for parameter extraction
def get_library_id(library_id: LibraryIdPath) -> str:
    """Extract and validate library ID from path parameter.

    Args:
        library_id: Library identifier from path

    Returns:
        Validated library ID

    Raises:
        400: If library_id is not a valid UUID format (handled by validation_exception_handler)
    """
    return library_id


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
) -> dict:
    """Extract and validate filter parameters.

    Args:
        name: Library name filter

    Returns:
        Dictionary of filter parameters
    """
    return {
        "name": name,
    }


PaginationDep = Annotated[tuple[int, int], Depends(get_pagination_params)]
FiltersDep = Annotated[dict, Depends(get_filter_params)]
DocumentLibraryServiceDep = Annotated[DocumentLibraryService, Depends(get_document_library_service)]
DocumentSetServiceDep = Annotated[DocumentSetService, Depends(get_document_set_service)]


@document_libraries_router.post(
    "",
    response_model=DocumentLibraryResponse,
    status_code=201,
    summary="Create a new document library",
    description="""
    Create a new document library with the provided name and optional description.

    The library will be assigned a unique UUID identifier and timestamp metadata.
    Library names must be unique across the system.

    **Request Body:**
    - `name` (required): Library name (3-128 characters, must be unique, must start with letter, can only contain letters/digits/spaces/underscores)
    - `description` (optional): Library description (max 2000 characters)
    - `purpose` (optional): Purpose or use case (max 1024 characters)
    - `original_size` (optional): Input size in bytes (non-negative integer)
    - `final_size` (optional): Processed size in bytes (non-negative integer)
    - `tags` (optional): List of tags (no limit on count or individual tag length)

    **Response:**
    - Returns the created library with generated metadata (library_id, created_at, updated_at)
    - Initial metrics are set to zero (total_document_sets, total_documents, total_size_bytes)

    **Error Responses:**
    - `400 Bad Request`: Invalid input data or validation failure
    - `409 Conflict`: Library with the same name already exists
    - `500 Internal Server Error`: Database or storage error
    """,
    responses={
        201: {
            "description": "Library created successfully",
            "model": DocumentLibraryResponse,
        },
        400: {
            "description": "Invalid request data",
            "model": ErrorResponse,
        },
        409: {
            "description": "Library with same name already exists",
            "model": ErrorResponse,
        },
        500: {
            "description": "Internal server error",
            "model": ErrorResponse,
        },
    },
)
def create_library(
    request: Request,
    library: DocumentLibraryPrototype,
    service: DocumentLibraryServiceDep,
) -> DocumentLibraryResponse:
    """Create a new document library.

    Args:
        request: FastAPI request object (for transaction ID)
        library: Library creation request data
        service: Injected document library service

    Returns:
        Created library response with metadata

    Raises:
        DocumentLibraryAlreadyExistsException: If library name already exists (409)
        DocumentLibraryInvalidDataException: If validation fails (400)
        DocumentLibraryStorageException: If storage operation fails (500)
    """
    logger.info("Creating library: %s", library.name)

    # Create library via service with fields from request
    domain_library = service.create_library(
        name=library.name,
        description=library.description,
        purpose=library.purpose,
        original_size=library.original_size,
        final_size=library.final_size,
        tags=library.tags or [],
    )

    # Convert to response DTO
    response = DocumentLibraryMapper.domain_to_response(domain=domain_library)

    logger.info("Library created successfully: %s", response.library_id)
    return response


@document_libraries_router.get(
    "/{library_id}",
    response_model=DocumentLibraryResponse,
    summary="Get a document library by ID",
    description="""
    Retrieve a specific document library by its unique identifier.

    **Path Parameters:**
    - `library_id` (required): UUID of the library to retrieve

    **Response:**
    - Returns the library with all metadata and metrics
    - Includes list of associated document set IDs

    **Error Responses:**
    - `400 Bad Request`: Invalid library ID format
    - `404 Not Found`: Library does not exist
    - `500 Internal Server Error`: Database or storage error
    """,
    responses={
        200: {
            "description": "Library retrieved successfully",
            "model": DocumentLibraryResponse,
        },
        400: {
            "description": "Invalid library ID format",
            "model": ErrorResponse,
        },
        404: {
            "description": "Library not found",
            "model": ErrorResponse,
        },
        500: {
            "description": "Internal server error",
            "model": ErrorResponse,
        },
    },
)
def get_library(
    service: DocumentLibraryServiceDep,
    library_id: Annotated[str, Depends(get_library_id)],
) -> DocumentLibraryResponse:
    """Get a document library by ID.

    Args:
        service: Injected document library service
        library_id: Library identifier from path

    Returns:
        Library response with metadata

    Raises:
        DocumentLibraryNotFoundException: If library not found (404)
        DocumentLibraryInvalidDataException: If library_id is invalid (400)
        DocumentLibraryStorageException: If storage operation fails (500)
    """
    logger.info("Retrieving library: %s", library_id)

    # Get library via service
    domain_library = service.get_library(library_id=library_id)

    # Convert to response DTO
    response = DocumentLibraryMapper.domain_to_response(domain=domain_library)

    logger.info("Library retrieved successfully: %s", library_id)
    return response


@document_libraries_router.get(
    "",
    response_model=list[DocumentLibraryResponse],
    summary="List document libraries",
    description="""
    Retrieve a list of document libraries.

    **Query Parameters:**
    - `limit` (optional): Maximum number of libraries to return (default: 100, max: 1000)
    - `offset` (optional): Number of libraries to skip (default: 0)

    **Response:**
    - Returns list of libraries with metadata

    **Error Responses:**
    - `400 Bad Request`: Invalid query parameters
    - `500 Internal Server Error`: Database or storage error
    """,
    responses={
        200: {
            "description": "Libraries retrieved successfully",
        },
        400: {
            "description": "Invalid query parameters",
            "model": ErrorResponse,
        },
        500: {
            "description": "Internal server error",
            "model": ErrorResponse,
        },
    },
)
def list_libraries(
    request: Request,
    service: DocumentLibraryServiceDep,
    pagination: PaginationDep,
    filters: FiltersDep,
) -> list[DocumentLibraryResponse]:
    """List document libraries.

    Args:
        request: FastAPI request object
        service: Injected document library service
        pagination: Tuple of (limit, offset)
        filters: Dictionary of filter parameters

    Returns:
        List of library responses

    Raises:
        DocumentLibraryStorageException: If storage operation fails (500)
    """
    limit, offset = pagination

    logger.info("Listing libraries: limit=%s, offset=%s", limit, offset)

    # Get libraries via service
    libraries = service.list_libraries(
        limit=limit,
        offset=offset,
    )

    # Convert to response DTOs
    responses = [DocumentLibraryMapper.domain_to_response(domain=lib) for lib in libraries]

    logger.info("Listed %s libraries", len(responses))
    return responses


@document_libraries_router.patch(
    "/{library_id}",
    response_model=DocumentLibraryResponse,
    summary="Update a document library",
    description="""
    Update specific fields of an existing document library.

    Only provided fields will be updated. Protected fields (library_id, created_at, document_set_ids)
    cannot be modified.

    **Path Parameters:**
    - `library_id` (required): UUID of the library to update

    **Request Body (all optional):**
    - `name`: New library name (3-128 characters, must be unique if changed, must start with letter, can only contain letters/digits/spaces/underscores)
    - `description`: New library description (max 2000 characters)
    - `purpose`: New purpose or use case (max 1024 characters)
    - `original_size`: New input size in bytes (non-negative integer)
    - `final_size`: New processed size in bytes (non-negative integer)
    - `tags`: New list of tags (no limit on count or individual tag length)

    **Response:**
    - Returns the updated library with all metadata
    - `updated_at` timestamp is automatically updated

    **Error Responses:**
    - `400 Bad Request`: Invalid input data or attempting to modify protected fields
    - `404 Not Found`: Library does not exist
    - `409 Conflict`: New name conflicts with existing library
    - `500 Internal Server Error`: Database or storage error
    """,
    responses={
        200: {
            "description": "Library updated successfully",
            "model": DocumentLibraryResponse,
        },
        400: {
            "description": "Invalid request data",
            "model": ErrorResponse,
        },
        404: {
            "description": "Library not found",
            "model": ErrorResponse,
        },
        409: {
            "description": "Library name already exists",
            "model": ErrorResponse,
        },
        500: {
            "description": "Internal server error",
            "model": ErrorResponse,
        },
    },
)
def update_library(
    updates: DocumentLibraryPatch,
    request: Request,
    service: DocumentLibraryServiceDep,
    library_id: Annotated[str, Depends(get_library_id)],
) -> DocumentLibraryResponse:
    """Update a document library.

    Args:
        updates: Library update request data
        request: FastAPI request object (for transaction ID)
        service: Injected document library service
        library_id: Library identifier from path

    Returns:
        Updated library response

    Raises:
        DocumentLibraryNotFoundException: If library not found (404)
        DocumentLibraryAlreadyExistsException: If new name conflicts (409)
        DocumentLibraryInvalidDataException: If validation fails (400)
        DocumentLibraryStorageException: If storage operation fails (500)
    """
    logger.info("Updating library: %s", library_id)

    # Convert DTO to update dict (exclude None values)
    update_dict = updates.model_dump(exclude_none=True)

    # Update library via service with all fields
    updated_library = service.update_library(
        library_id=library_id,
        name=update_dict.get("name"),
        description=update_dict.get("description"),
        purpose=update_dict.get("purpose"),
        original_size=update_dict.get("original_size"),
        final_size=update_dict.get("final_size"),
        tags=update_dict.get("tags"),
    )

    # Convert to response DTO
    response = DocumentLibraryMapper.domain_to_response(domain=updated_library)

    logger.info("Library updated successfully: %s", library_id)
    return response


@document_libraries_router.delete(
    "/{library_id}",
    status_code=204,
    summary="Delete a document library",
    description="""
    Delete a document library by its unique identifier.

    This operation removes the library metadata and all associations with document sets.
    Document sets themselves are NOT deleted - only the library-to-set relationships are removed.

    **Path Parameters:**
    - `library_id` (required): UUID of the library to delete

    **Response:**
    - `204 No Content`: Library deleted successfully (no response body)

    **Error Responses:**
    - `400 Bad Request`: Invalid library ID format
    - `404 Not Found`: Library does not exist
    - `500 Internal Server Error`: Database or storage error
    """,
    responses={
        204: {
            "description": "Library deleted successfully",
        },
        400: {
            "description": "Invalid library ID format",
            "model": ErrorResponse,
        },
        404: {
            "description": "Library not found",
            "model": ErrorResponse,
        },
        500: {
            "description": "Internal server error",
            "model": ErrorResponse,
        },
    },
)
def delete_library(
    request: Request,
    service: DocumentLibraryServiceDep,
    library_id: Annotated[str, Depends(get_library_id)],
) -> None:
    """Delete a document library.

    Args:
        request: FastAPI request object (for transaction ID)
        service: Injected document library service
        library_id: Library identifier from path

    Raises:
        DocumentLibraryNotFoundException: If library not found (404)
        DocumentLibraryInvalidDataException: If library_id is invalid (400)
        DocumentLibraryStorageException: If storage operation fails (500)
    """
    logger.info("Deleting library: %s", library_id)

    # Delete library via service
    service.delete_library(library_id=library_id)

    logger.info("Library deleted successfully: %s", library_id)


@document_libraries_router.put(
    "/{library_id}/document-sets",
    status_code=204,
    summary="Add document sets to a library",
    description="""
    Add multiple document sets to a document library in bulk.

    This creates many-to-many relationships between the library and document sets.
    Document sets can belong to multiple libraries, and a library can contain multiple document sets.

    **Path Parameters:**
    - `library_id` (required): UUID of the library

    **Query Parameters:**
    - `document_sets_ids` (required): Comma-separated list of document set UUIDs

    **Response:**
    - `204 No Content`: Document sets added successfully

    **Error Responses:**
    - `400 Bad Request`: Invalid ID format or document set already in library
    - `404 Not Found`: Library or document set does not exist
    - `500 Internal Server Error`: Database or storage error
    """,
    responses={
        204: {
            "description": "Document sets added successfully",
        },
        400: {
            "description": "Invalid request or duplicate association",
            "model": ErrorResponse,
        },
        404: {
            "description": "Library or document set not found",
            "model": ErrorResponse,
        },
        500: {
            "description": "Internal server error",
            "model": ErrorResponse,
        },
    },
)
def add_document_sets(
    request: Request,
    service: DocumentLibraryServiceDep,
    library_id: Annotated[str, Depends(get_library_id)],
    document_sets_ids: Annotated[
        str, Query(description="Comma-separated document set IDs", min_length=1, max_length=500)
    ],
) -> Response:
    """Add multiple document sets to a library.

    Args:
        request: FastAPI request object (for transaction ID)
        service: Injected document library service
        library_id: Library identifier from path
        document_sets_ids: Comma-separated document set IDs from query parameter

    Returns:
        204 No Content response

    Raises:
        DocumentLibraryNotFoundException: If library not found (404)
        DocumentSetNotFoundException: If document set not found (404)
        DocumentLibraryInvalidDataException: If validation fails or duplicate (400)
        DocumentLibraryStorageException: If storage operation fails (500)
    """
    # Parse comma-separated IDs
    doc_set_ids = [id.strip() for id in document_sets_ids.split(",") if id.strip()]

    logger.info("Adding %s document sets to library %s", len(doc_set_ids), library_id)

    # Add document sets via service
    service.add_document_sets_bulk(
        library_id=library_id,
        document_set_ids=doc_set_ids,
    )

    logger.info("Document sets added successfully to library: %s", library_id)
    return Response(status_code=204)


@document_libraries_router.delete(
    "/{library_id}/document-sets",
    status_code=204,
    summary="Remove document sets from a library",
    description="""
    Remove multiple document sets from a document library in bulk.

    This removes the many-to-many relationships but does NOT delete the document sets themselves.
    The document sets remain available and can still be associated with other libraries.

    **Path Parameters:**
    - `library_id` (required): UUID of the library

    **Query Parameters:**
    - `document_sets_ids` (required): Comma-separated list of document set UUIDs

    **Response:**
    - `204 No Content`: Document sets removed successfully

    **Error Responses:**
    - `400 Bad Request`: Invalid ID format or document set not in library
    - `404 Not Found`: Library or document set does not exist
    - `500 Internal Server Error`: Database or storage error
    """,
    responses={
        204: {
            "description": "Document sets removed successfully",
        },
        400: {
            "description": "Invalid request or document set not in library",
            "model": ErrorResponse,
        },
        404: {
            "description": "Library or document set not found",
            "model": ErrorResponse,
        },
        500: {
            "description": "Internal server error",
            "model": ErrorResponse,
        },
    },
)
def remove_document_sets(
    request: Request,
    service: DocumentLibraryServiceDep,
    library_id: Annotated[str, Depends(get_library_id)],
    document_sets_ids: Annotated[
        str, Query(description="Comma-separated document set IDs", min_length=1, max_length=500)
    ],
) -> Response:
    """Remove multiple document sets from a library.

    Args:
        request: FastAPI request object (for transaction ID)
        service: Injected document library service
        library_id: Library identifier from path
        document_sets_ids: Comma-separated document set IDs from query parameter

    Returns:
        204 No Content response

    Raises:
        DocumentLibraryNotFoundException: If library not found (404)
        DocumentSetNotFoundException: If document set not found (404)
        DocumentLibraryInvalidDataException: If validation fails (400)
        DocumentLibraryStorageException: If storage operation fails (500)
    """
    # Parse comma-separated IDs
    doc_set_ids = [id.strip() for id in document_sets_ids.split(",") if id.strip()]

    logger.info("Removing %s document sets from library %s", len(doc_set_ids), library_id)

    # Remove document sets via service
    service.remove_document_sets_bulk(
        library_id=library_id,
        document_set_ids=doc_set_ids,
    )

    logger.info("Document sets removed successfully from library: %s", library_id)
    return Response(status_code=204)


@document_libraries_router.get(
    "/{library_id}/document-sets",
    response_model=DocumentSetsRetrieved,
    summary="List document sets in a library",
    description="""
    Retrieve the document sets associated with a library.

    **Path Parameters:**
    - `library_id` (required): UUID of the library

    **Response:**
    - Returns DocumentSetsRetrieved with array of document set details
    - Empty array if library has no associated document sets

    **Error Responses:**
    - `400 Bad Request`: Invalid library ID format
    - `404 Not Found`: Library does not exist
    - `500 Internal Server Error`: Database or storage error
    """,
    responses={
        200: {
            "description": "Document sets retrieved successfully",
            "model": DocumentSetsRetrieved,
        },
        400: {
            "description": "Invalid library ID format",
            "model": ErrorResponse,
        },
        404: {
            "description": "Library not found",
            "model": ErrorResponse,
        },
        500: {
            "description": "Internal server error",
            "model": ErrorResponse,
        },
    },
)
def list_document_sets(
    library_service: DocumentLibraryServiceDep,
    document_set_service: DocumentSetServiceDep,
    library_id: Annotated[str, Depends(get_library_id)],
) -> DocumentSetsRetrieved:
    """List document sets in a library.

    Args:
        library_service: Injected document library service
        document_set_service: Injected document set service
        library_id: Library identifier from path

    Returns:
        DocumentSetsRetrieved with document set details

    Raises:
        DocumentLibraryNotFoundException: If library not found (404)
        DocumentLibraryInvalidDataException: If library_id is invalid (400)
        DocumentLibraryStorageException: If storage operation fails (500)
    """
    logger.info("Listing document sets for library: %s", library_id)

    # Get document set IDs via library service
    document_set_ids = library_service.get_document_sets(library_id=library_id)

    # Fetch full metadata for each document set
    document_sets_metadata = []
    for doc_set_id in document_set_ids:
        doc_set = document_set_service.get_document_set(document_set_id=doc_set_id)
        # Convert domain model to dict for mapper with all available fields
        doc_set_dict = {
            "id": doc_set.id,
            "name": doc_set.name,
            "description": doc_set.description,
            "container_id": doc_set.metadata.get("container_id") if doc_set.metadata else None,
            "container_type": doc_set.metadata.get("container_type") if doc_set.metadata else None,
            "documents": {"count": doc_set.total_documents, "size_bytes": doc_set.total_size_bytes}
            if doc_set.total_documents > 0
            else None,
            "tags": doc_set.metadata.get("tags", []) if doc_set.metadata else [],
            "propagate_source_acls": doc_set.metadata.get("propagate_source_acls") if doc_set.metadata else None,
            "is_derivative_available": doc_set.metadata.get("is_derivative_available") if doc_set.metadata else None,
            "created_at": doc_set.created_at,
            "updated_at": doc_set.updated_at,
        }
        document_sets_metadata.append(doc_set_dict)

    # Convert to DocumentSetsRetrieved DTO using full metadata
    response = DocumentLibraryMapper.create_document_sets_retrieved_response(document_sets=document_sets_metadata)

    logger.info("Found %s document sets in library: %s", len(document_set_ids), library_id)
    return response
