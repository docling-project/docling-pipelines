# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Document retrieval API routes with ACL enforcement."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from opensearchpy.exceptions import NotFoundError, RequestError

from docpipe.api.auth.config import get_auth_settings
from docpipe.api.auth.dependencies import LOCAL_PRINCIPAL_USERNAME, get_current_user
from docpipe.api.auth.models import User
from docpipe.api.dto.document_dto import (
    DocumentResponse,
    DocumentSearchRequest,
    DocumentSearchResponse,
)
from docpipe.api.dto.error_dto import ErrorResponse
from docpipe.api.services.acl_query_builder import ACLQueryBuilder
from docpipe.api.services.opensearch_service import (
    OpenSearchService,
    get_opensearch_service,
)

logger = logging.getLogger(__name__)

documents_router = APIRouter(prefix="/documents", tags=["documents"])


def _bypasses_acl(*, user: User) -> bool:
    """Return True when the caller is the local principal and authentication is disabled.

    No real user identity exists in that case, so the allowed_users filter is skipped.
    With authentication enabled the reserved name is never granted access.
    """
    return user.username == LOCAL_PRINCIPAL_USERNAME and not get_auth_settings().enabled


@documents_router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    status_code=200,
    operation_id="get_document_by_id",
    summary="Retrieve a document by ID with ACL enforcement",
    responses={
        200: {
            "description": "Document retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "id": "doc-123",
                        "content": "This is the document content...",
                        "metadata": {"category": "tech", "author": "John Doe"},
                        "created_at": "2026-05-01T10:00:00Z",
                        "updated_at": "2026-05-15T14:30:00Z",
                    }
                }
            },
        },
        401: {
            "model": ErrorResponse,
            "description": "Not authenticated - valid JWT token required",
        },
        404: {
            "model": ErrorResponse,
            "description": "Document not found or user not authorized to access it",
        },
        503: {
            "model": ErrorResponse,
            "description": "OpenSearch service unavailable",
        },
    },
)
async def get_document(
    document_id: Annotated[
        str,
        Path(
            description="Unique identifier for the document",
            examples=["doc-123"],
        ),
    ],
    current_user: Annotated[User, Depends(get_current_user)],
    opensearch_service: Annotated[
        OpenSearchService,
        Depends(get_opensearch_service),
    ],
) -> DocumentResponse:
    """Retrieve a single document by ID with ACL enforcement.

    Access is granted only if:
    - User is authenticated (valid JWT token)
    - Document exists in the index
    - User's username is present in the document's allowed_users field

    Security Note:
    Returns 404 for both "document not found" and "user not authorized"
    to prevent information leakage about document existence.

    Args:
        document_id: Document ID to retrieve
        current_user: Authenticated user from JWT token
        opensearch_service: OpenSearch service instance

    Returns:
        DocumentResponse with document data

    Raises:
        HTTPException: 401 if not authenticated, 404 if not found/authorized,
                      503 if OpenSearch unavailable
    """
    logger.info(
        "Document retrieval request: doc_id=%s, user=%s",
        document_id,
        current_user.username,
    )

    try:
        # Build ACL-enforced query
        query = ACLQueryBuilder.build_document_query(
            document_id=document_id,
            username=current_user.username,
            bypass_acl=_bypasses_acl(user=current_user),
        )

        # Execute query
        client = opensearch_service.get_client()
        response = client.search(
            index=opensearch_service.config.opensearch_default_index,
            body=query,
        )

        # Check if document was found
        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            # Return 404 for both "not found" and "not authorized"
            # This prevents information leakage about document existence
            logger.warning(
                "Document not found or user not authorized: doc_id=%s",
                document_id,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found",
            )

        # Extract and return document
        hit = hits[0]
        logger.info(
            "Document retrieved successfully: doc_id=%s, user=%s",
            document_id,
            current_user.username,
        )
        return DocumentResponse.from_opensearch_hit(hit=hit)

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except NotFoundError:
        # OpenSearch index not found
        logger.error(
            "OpenSearch index not found: %s",
            opensearch_service.config.opensearch_default_index,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document service unavailable",
        ) from None
    except RequestError as e:
        # OpenSearch request error
        logger.error("OpenSearch request error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid document request",
        ) from e
    except Exception as e:
        # Unexpected error
        logger.exception(
            "Unexpected error retrieving document: %s",
            e,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document service error",
        ) from e


@documents_router.post(
    "/search",
    response_model=DocumentSearchResponse,
    status_code=200,
    operation_id="search_documents",
    summary="Search documents with ACL enforcement",
    responses={
        200: {
            "description": "Search results retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "documents": [
                            {
                                "id": "doc-123",
                                "content": "Machine learning content...",
                                "metadata": {"category": "tech"},
                                "created_at": "2026-05-01T10:00:00Z",
                                "updated_at": "2026-05-15T14:30:00Z",
                            }
                        ],
                        "total": 42,
                        "limit": 10,
                        "offset": 0,
                        "has_more": True,
                    }
                }
            },
        },
        401: {
            "model": ErrorResponse,
            "description": "Not authenticated - valid JWT token required",
        },
        503: {
            "model": ErrorResponse,
            "description": "OpenSearch service unavailable",
        },
    },
)
async def search_documents(
    search_request: DocumentSearchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    opensearch_service: Annotated[
        OpenSearchService,
        Depends(get_opensearch_service),
    ],
) -> DocumentSearchResponse:
    """Search documents with full-text search and filters.

    All results are automatically filtered to only include documents
    where the authenticated user is present in the allowed_users field.

    Features:
    - Full-text search across content, title, and metadata
    - Field-based filtering (exact match)
    - Sorting by any field
    - Pagination with limit/offset

    Args:
        search_request: Search parameters (query, filters, sort, pagination)
        current_user: Authenticated user from JWT token
        opensearch_service: OpenSearch service instance

    Returns:
        DocumentSearchResponse with matching documents and pagination metadata

    Raises:
        HTTPException: 401 if not authenticated, 503 if OpenSearch unavailable
    """
    logger.info(
        "Document search request: user=%s, query=%s, filters=%s",
        current_user.username,
        search_request.query,
        search_request.filters,
    )

    try:
        # Build search query with ACL enforcement
        query = ACLQueryBuilder.build_search_query(
            username=current_user.username,
            query_text=search_request.query,
            filters=search_request.filters,
            sort=search_request.sort,
            bypass_acl=_bypasses_acl(user=current_user),
        )

        # Execute search
        client = opensearch_service.get_client()

        # Add pagination to query body
        query["size"] = search_request.limit
        query["from"] = search_request.offset

        response = client.search(
            index=opensearch_service.config.opensearch_default_index,
            body=query,
        )

        # Format response
        search_response = DocumentSearchResponse.from_opensearch_response(
            response=response,
            limit=search_request.limit,
            offset=search_request.offset,
        )

        logger.info(
            "Document search completed: user=%s, results=%d, total=%d",
            current_user.username,
            len(search_response.documents),
            search_response.total,
        )
        return search_response

    except NotFoundError:
        # OpenSearch index not found - return empty results
        logger.warning(
            "OpenSearch index not found: %s",
            opensearch_service.config.opensearch_default_index,
        )
        return DocumentSearchResponse(
            documents=[],
            total=0,
            limit=search_request.limit,
            offset=search_request.offset,
            has_more=False,
        )
    except RequestError as e:
        # OpenSearch request error
        logger.error("OpenSearch request error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid search request",
        ) from e
    except Exception as e:
        # Unexpected error
        logger.exception(
            "Unexpected error searching documents: %s",
            e,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document search service error",
        ) from e
