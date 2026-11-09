# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Custom exception handler for REST API standard error responses.

This module provides FastAPI exception handlers that convert all exceptions
to REST API standard error format as defined in error_dto.py.
"""

import logging
import uuid
from collections.abc import Mapping

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from docpipe.api.dto.error_dto import (
    ErrorCode,
    ErrorDetail,
    ErrorResponse,
    ErrorTarget,
    TargetType,
)
from docpipe.core.constants.constants import DocpipeConstants
from docpipe.exceptions.docpipe_exceptions import DOCLING_PIPELINES_DOCS_URL, DocpipeException

logger = logging.getLogger(__name__)


def get_trace_id(request: Request) -> str:
    """Get trace ID from request state or generate new one.

    Args:
        request: FastAPI request object

    Returns:
        str: Trace ID from request.state.transaction_id or new UUID
    """
    return getattr(request.state, "transaction_id", None) or str(uuid.uuid4())


def create_error_response(
    status_code: int,
    error_code: ErrorCode,
    message: str,
    trace_id: str,
    more_info: str | None = None,
    target: ErrorTarget | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Create REST API standard error response.

    Args:
        status_code: HTTP status code
        error_code: Machine-readable error code from ErrorCode enum
        message: Human-readable error message
        trace_id: Trace ID for debugging (required)
        more_info: Optional URL to error documentation
        target: Optional target information
        headers: Optional response headers (for example ``Retry-After``)

    Returns:
        JSONResponse: REST API standard error response
    """
    error_detail = ErrorDetail(
        code=error_code,
        message=message,
        more_info=more_info,
        target=target,
    )

    error_response = ErrorResponse(
        errors=[error_detail],
        trace=trace_id,
        status_code=status_code,
    )

    # Log error with stack trace
    logger.error(
        "Error response: status=%s, code=%s, trace=%s",
        status_code,
        error_code,
        trace_id,
        exc_info=True,
        stack_info=True,
    )

    return JSONResponse(
        status_code=status_code,
        content=error_response.model_dump(exclude_none=True),
        headers=dict(headers) if headers else None,
    )


def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Handle HTTP exceptions and convert to REST API standard format.

    Args:
        request: FastAPI request object
        exc: HTTP exception

    Returns:
        JSONResponse: REST API standard error response
    """
    trace_id = get_trace_id(request)

    # Map HTTP status codes to error codes
    error_code_map: dict[int, ErrorCode] = {
        400: "invalid_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        422: "validation_error",
        425: "too_early",
        429: "too_many_requests",
        500: "internal_error",
        503: "service_unavailable",
    }

    error_code = error_code_map.get(exc.status_code, "unknown_error")

    # Extract target information from path parameters if available
    target = None
    if exc.status_code == 404 and DocpipeConstants.FLOW_ID in request.path_params:
        target = ErrorTarget(type=TargetType.PARAMETER, name=DocpipeConstants.FLOW_ID)

    return create_error_response(
        status_code=exc.status_code,
        error_code=error_code,
        message=str(exc.detail),
        trace_id=trace_id,
        target=target,
        headers=exc.headers,
    )


def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle validation errors and convert to REST API standard format.

    Args:
        request: FastAPI request object
        exc: Request validation error

    Returns:
        JSONResponse: REST API standard error response with multiple errors
    """
    trace_id = get_trace_id(request)
    errors = []

    for error in exc.errors():
        # Format field path: skip 'body' prefix, use ' -> ' separator
        field_path = [str(loc) for loc in error["loc"] if loc != "body"]
        field_name = " -> ".join(field_path) if field_path else "unknown"

        # Determine target type based on location
        target_type = TargetType.FIELD
        if error["loc"] and error["loc"][0] == "path":
            target_type = TargetType.PARAMETER
        elif error["loc"] and error["loc"][0] == "query":
            target_type = TargetType.PARAMETER
        elif error["loc"] and error["loc"][0] == "header":
            target_type = TargetType.HEADER

        error_detail = ErrorDetail(
            code="validation_error",
            message=f"Error in Field: {field_name}: {error['msg']}",
            target=ErrorTarget(type=target_type, name=field_name),
        )
        errors.append(error_detail)

    error_response = ErrorResponse(
        errors=errors,
        trace=trace_id,
        status_code=status.HTTP_400_BAD_REQUEST,
    )

    # Log error with stack trace
    logger.error(
        "Validation error: trace=%s, error_count=%d",
        trace_id,
        len(errors),
        exc_info=True,
        stack_info=True,
    )

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=error_response.model_dump(exclude_none=True),
    )


def _resolve_exception_target(exc: DocpipeException) -> ErrorTarget | None:
    """Resolve an ErrorTarget from well-known attributes on a DocpipeException."""
    for attr, target_type in (
        (DocpipeConstants.FLOW_ID, TargetType.PARAMETER),
        (DocpipeConstants.FIELD_NAME, TargetType.FIELD),
        (DocpipeConstants.FLOW_NAME, TargetType.FIELD),
    ):
        value = getattr(exc, attr, None)
        if value:
            return ErrorTarget(type=target_type, name=value)
    return None


def docpipe_exception_handler(request: Request, exc: DocpipeException) -> JSONResponse:
    """Handle DocpipeException and convert to REST API standard format.

    Args:
        request: FastAPI request object
        exc: DocpipeException or subclass

    Returns:
        JSONResponse: REST API standard error response
    """
    from docpipe.exceptions.docpipe_exceptions import FlowValidationException

    trace_id = get_trace_id(request)

    # Map specific HTTP status codes to their standard API error codes.
    # This takes precedence over the domain error code so the response body
    # matches the REST API contract (e.g. 425 → "too_early").
    status_code_error_map: dict[int, str] = {
        403: "forbidden",
        425: "too_early",
    }
    domain_error_code = str(exc.error_code.value) if exc.error_code else None
    api_error_code = status_code_error_map.get(exc.status_code) or domain_error_code or "internal_error"

    # FlowValidationException carries a structured errors list — unpack each
    # alert as a separate ErrorDetail so the caller gets actionable per-error detail.
    if isinstance(exc, FlowValidationException) and exc.errors:
        errors = []
        for alert in exc.errors:
            message = getattr(alert, "message", str(alert))
            message_code = getattr(alert, "message_code", None)
            errors.append(
                ErrorDetail(
                    code=api_error_code,  # type: ignore[arg-type]
                    message=f"{message_code}: {message}" if message_code else message,
                )
            )
        error_response = ErrorResponse(
            errors=errors,
            trace=trace_id,
            status_code=exc.status_code,
        )
        logger.error(
            "FlowValidationException: trace=%s, errors=%d",
            trace_id,
            len(errors),
            exc_info=True,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=error_response.model_dump(exclude_none=True),
        )

    # Extract target information if available (for flow-specific exceptions)
    target = _resolve_exception_target(exc)

    return create_error_response(
        status_code=exc.status_code,
        error_code=api_error_code,  # type: ignore[arg-type]
        message=str(exc),
        trace_id=trace_id,
        more_info=exc.more_info if exc.more_info is not None else DOCLING_PIPELINES_DOCS_URL,
        target=target,
    )


def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle generic exceptions and convert to REST API standard format.

    This handler is a last-resort fallback for exceptions not caught by
    more specific handlers. Service layers should raise typed DocpipeException
    subclasses instead of built-in exceptions.

    Args:
        request: FastAPI request object
        exc: Generic exception

    Returns:
        JSONResponse: REST API standard error response
    """
    trace_id = get_trace_id(request)

    # Handle FileNotFoundError - return 404
    if isinstance(exc, FileNotFoundError):
        return create_error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="not_found",
            message=str(exc),
            trace_id=trace_id,
        )

    # Handle ValueError - return 400
    if isinstance(exc, ValueError):
        return create_error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="invalid_parameter",
            message=str(exc),
            trace_id=trace_id,
        )

    # Handle PermissionError - may come from filesystem or other system operations
    if isinstance(exc, PermissionError):
        return create_error_response(
            status_code=status.HTTP_403_FORBIDDEN,
            error_code="forbidden",
            message="Permission denied",
            trace_id=trace_id,
        )

    # Handle OSError and subclasses - sanitize message to avoid leaking internal paths
    if isinstance(exc, OSError):
        return create_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="internal_error",
            message="An internal storage error occurred",
            trace_id=trace_id,
        )

    # Default to internal server error for unknown exceptions
    # Log full exception details but return sanitized message
    logger.error(
        "Unhandled exception: %s: %s",
        type(exc).__name__,
        exc,
        exc_info=True,
        extra={"trace_id": trace_id},
    )

    return create_error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_code="internal_error",
        message="An unexpected error occurred",
        trace_id=trace_id,
    )
