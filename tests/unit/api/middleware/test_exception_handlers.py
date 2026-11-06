"""Tests for exception handlers."""

import errno
import json
from typing import Annotated
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from docpipe.api.middleware.error_handler import (
    docpipe_exception_handler,
    generic_exception_handler,
    get_trace_id,
    http_exception_handler,
    validation_exception_handler,
)
from docpipe.api.middleware.transaction_middleware import TransactionMiddleware
from docpipe.exceptions.docpipe_exceptions import (
    DOCLING_PIPELINES_DOCS_URL,
    TROUBLESHOOTING_DOCS_URL,
    DocpipeException,
    FlowAlreadyExistsException,
    FlowExecutionFailedException,
    FlowInvalidDataException,
    FlowNotFoundException,
    FlowStorageException,
    FlowValidationException,
    RepositoryConfigurationException,
)


@pytest.fixture
def mock_request():
    """Create a mock request with transaction ID."""
    request = MagicMock(spec=Request)
    request.state = MagicMock()
    request.state.transaction_id = "12345678-1234-4234-8234-123456789012"
    request.path_params = {}
    return request


@pytest.fixture
def mock_request_no_trace():
    """Create a mock request without transaction ID."""
    request = MagicMock(spec=Request)
    request.state = MagicMock()
    # No transaction_id attribute
    delattr(request.state, "transaction_id")
    request.path_params = {}
    return request


def test_get_trace_id_from_request_state(mock_request):
    """Test getting trace ID from request state."""
    trace_id = get_trace_id(mock_request)
    assert trace_id == "12345678-1234-4234-8234-123456789012"


def test_get_trace_id_generates_when_missing(mock_request_no_trace):
    """Test generating trace ID when not in request state."""
    trace_id = get_trace_id(mock_request_no_trace)

    # Should be a valid UUID string
    assert trace_id
    assert len(trace_id) == 36  # UUID format
    assert trace_id.count("-") == 4


@pytest.mark.anyio
async def test_http_exception_handler_404(mock_request):
    """Test HTTP exception handler for 404 errors."""
    exc = StarletteHTTPException(status_code=404, detail="Flow not found")

    response = http_exception_handler(mock_request, exc)

    assert response.status_code == 404
    content = json.loads(response.body)

    assert "errors" in content
    assert len(content["errors"]) == 1
    assert content["errors"][0]["code"] == "not_found"
    assert content["errors"][0]["message"] == "Flow not found"
    assert content["trace"] == "12345678-1234-4234-8234-123456789012"
    assert content["status_code"] == 404
    assert "more_info" not in content["errors"][0]


@pytest.mark.anyio
async def test_http_exception_handler_with_flow_id_target(mock_request):
    """Test HTTP exception handler adds target for flow_id parameter."""
    mock_request.path_params = {"flow_id": "123"}
    exc = StarletteHTTPException(status_code=404, detail="Flow not found")

    response = http_exception_handler(mock_request, exc)

    content = json.loads(response.body)
    assert content["errors"][0]["target"]["type"] == "parameter"
    assert content["errors"][0]["target"]["name"] == "flow_id"


@pytest.mark.anyio
async def test_http_exception_handler_500(mock_request):
    """Test HTTP exception handler for 500 errors."""
    exc = StarletteHTTPException(status_code=500, detail="Internal server error")

    response = http_exception_handler(mock_request, exc)

    assert response.status_code == 500
    content = json.loads(response.body)

    assert content["errors"][0]["code"] == "internal_error"
    assert content["trace"] == "12345678-1234-4234-8234-123456789012"


@pytest.mark.anyio
async def test_validation_exception_handler_single_error(mock_request):
    """Test validation exception handler with single error."""
    # Create a mock validation error
    validation_error = {
        "loc": ("body", "name"),
        "msg": "field required",
        "type": "value_error.missing",
    }

    exc = RequestValidationError([validation_error])

    response = validation_exception_handler(mock_request, exc)

    assert response.status_code == 400
    content = json.loads(response.body)

    assert "errors" in content
    assert len(content["errors"]) == 1
    assert content["errors"][0]["code"] == "validation_error"
    assert "Error in Field: name:" in content["errors"][0]["message"]
    assert content["errors"][0]["target"]["type"] == "field"
    assert content["errors"][0]["target"]["name"] == "name"
    assert content["trace"] == "12345678-1234-4234-8234-123456789012"


@pytest.mark.anyio
async def test_validation_exception_handler_nested_field(mock_request):
    """Test validation exception handler with nested field path."""
    validation_error = {
        "loc": ("body", "definition", "nodes", "0", "operator_type"),
        "msg": "field required",
        "type": "value_error.missing",
    }

    exc = RequestValidationError([validation_error])

    response = validation_exception_handler(mock_request, exc)

    content = json.loads(response.body)

    # Should use ' -> ' separator and skip 'body'
    assert "definition -> nodes -> 0 -> operator_type" in content["errors"][0]["message"]
    assert content["errors"][0]["target"]["name"] == "definition -> nodes -> 0 -> operator_type"


@pytest.mark.anyio
async def test_validation_exception_handler_multiple_errors(mock_request):
    """Test validation exception handler with multiple errors."""
    validation_errors = [
        {
            "loc": ("body", "name"),
            "msg": "field required",
            "type": "value_error.missing",
        },
        {
            "loc": ("body", "description"),
            "msg": "field required",
            "type": "value_error.missing",
        },
    ]

    exc = RequestValidationError(validation_errors)

    response = validation_exception_handler(mock_request, exc)

    content = json.loads(response.body)

    assert len(content["errors"]) == 2
    assert content["trace"] == "12345678-1234-4234-8234-123456789012"


@pytest.mark.anyio
async def test_validation_exception_handler_query_parameter(mock_request):
    """Test validation exception handler for query parameters."""
    validation_error = {
        "loc": ("query", "limit"),
        "msg": "value is not a valid integer",
        "type": "type_error.integer",
    }

    exc = RequestValidationError([validation_error])

    response = validation_exception_handler(mock_request, exc)

    content = json.loads(response.body)

    assert content["errors"][0]["target"]["type"] == "parameter"
    assert content["errors"][0]["target"]["name"] == "query -> limit"


@pytest.mark.anyio
async def test_generic_exception_handler_file_not_found(mock_request):
    """Test generic exception handler for FileNotFoundError."""
    exc = FileNotFoundError("File not found")

    response = generic_exception_handler(mock_request, exc)

    assert response.status_code == 404
    content = json.loads(response.body)

    assert content["errors"][0]["code"] == "not_found"
    assert content["errors"][0]["message"] == "File not found"
    assert content["trace"] == "12345678-1234-4234-8234-123456789012"


@pytest.mark.anyio
async def test_generic_exception_handler_permission_error(mock_request):
    """Test generic exception handler for PermissionError."""
    exc = PermissionError("Access denied")

    response = generic_exception_handler(mock_request, exc)

    assert response.status_code == 403
    content = json.loads(response.body)

    assert content["errors"][0]["code"] == "forbidden"
    assert content["trace"] == "12345678-1234-4234-8234-123456789012"


@pytest.mark.anyio
async def test_generic_exception_handler_value_error(mock_request):
    """Test generic exception handler for ValueError."""
    exc = ValueError("Invalid value")

    response = generic_exception_handler(mock_request, exc)

    assert response.status_code == 400
    content = json.loads(response.body)

    assert content["errors"][0]["code"] == "invalid_parameter"
    assert content["trace"] == "12345678-1234-4234-8234-123456789012"


@pytest.mark.anyio
async def test_generic_exception_handler_unknown_exception(mock_request):
    """Test generic exception handler for unknown exceptions."""
    exc = RuntimeError("Something went wrong")

    response = generic_exception_handler(mock_request, exc)

    assert response.status_code == 500
    content = json.loads(response.body)

    assert content["errors"][0]["code"] == "internal_error"
    assert content["errors"][0]["message"] == "An unexpected error occurred"
    assert content["trace"] == "12345678-1234-4234-8234-123456789012"


@pytest.mark.anyio
async def test_exception_handlers_log_errors(mock_request):
    """Test that exception handlers log errors with stack traces."""
    with patch("docpipe.api.middleware.error_handler.logger") as mock_logger:
        exc = StarletteHTTPException(status_code=500, detail="Test error")

        http_exception_handler(mock_request, exc)

        # Verify logger.error was called with exc_info and stack_info
        assert mock_logger.error.called
        call_kwargs = mock_logger.error.call_args[1]
        assert call_kwargs.get("exc_info") is True
        assert call_kwargs.get("stack_info") is True


# more_info defaults — exception class contract


@pytest.mark.parametrize(
    ("exc", "expected_more_info"),
    [
        (DocpipeException("base"), None),
        (FlowExecutionFailedException("failed"), f"{TROUBLESHOOTING_DOCS_URL}#issue-flow-execution-failed"),
        (FlowValidationException(), f"{TROUBLESHOOTING_DOCS_URL}#issue-flow-validation-failed"),
        (FlowNotFoundException("not found"), f"{TROUBLESHOOTING_DOCS_URL}#flow-crud-operation-errors"),
        (FlowAlreadyExistsException("exists"), f"{TROUBLESHOOTING_DOCS_URL}#flow-crud-operation-errors"),
        (FlowInvalidDataException("invalid"), f"{TROUBLESHOOTING_DOCS_URL}#flow-crud-operation-errors"),
        (FlowStorageException("error"), f"{TROUBLESHOOTING_DOCS_URL}#flow-crud-operation-errors"),
    ],
)
def test_exception_more_info_defaults(exc, expected_more_info):
    """Each exception class carries the expected more_info default."""
    assert exc.more_info == expected_more_info


# RepositoryConfigurationException Tests


@pytest.fixture
def repo_config_app():
    """Create test FastAPI app with error handler."""
    test_app = FastAPI()

    @test_app.get("/test-repo-config-error")
    async def test_endpoint():
        raise RepositoryConfigurationException(
            "Invalid repository type: 'invalid_type'. Must be one of: local",
            repository_type="invalid_type",
            valid_types=["local"],
        )

    # Register the exception handler
    test_app.add_exception_handler(RepositoryConfigurationException, docpipe_exception_handler)

    return test_app


@pytest.fixture
def repo_config_client(repo_config_app):
    """Create test client."""
    return TestClient(repo_config_app)


def test_repository_configuration_exception_returns_400(repo_config_client):
    """Test that RepositoryConfigurationException returns 400 status code."""
    response = repo_config_client.get("/test-repo-config-error")

    assert response.status_code == 400


def test_repository_configuration_exception_has_correct_error_code(repo_config_client):
    """Test that RepositoryConfigurationException returns correct error code."""
    response = repo_config_client.get("/test-repo-config-error")
    data = response.json()

    assert "errors" in data
    assert len(data["errors"]) == 1
    assert data["errors"][0]["code"] == "invalid_configuration"
    # RepositoryConfigurationException has more_info=None; handler falls back to the docs URL
    assert data["errors"][0]["more_info"] == DOCLING_PIPELINES_DOCS_URL


def test_repository_configuration_exception_has_message(repo_config_client):
    """Test that RepositoryConfigurationException includes error message."""
    response = repo_config_client.get("/test-repo-config-error")
    data = response.json()

    message = data["errors"][0]["message"]
    assert "Invalid repository type" in message
    assert "invalid_type" in message
    assert "local" in message


def test_repository_configuration_exception_has_trace_id(repo_config_client):
    """Test that RepositoryConfigurationException includes trace ID."""
    response = repo_config_client.get("/test-repo-config-error")
    data = response.json()

    assert "trace" in data
    assert len(data["trace"]) == 36  # UUID format


def test_repository_configuration_exception_has_status_code_in_response(
    repo_config_client,
):
    """Test that RepositoryConfigurationException includes status_code in response body."""
    response = repo_config_client.get("/test-repo-config-error")
    data = response.json()

    assert "status_code" in data
    assert data["status_code"] == 400


# ---------------------------------------------------------------------------
# Handlers registered on a real app (as in docpipe.api.main)
# ---------------------------------------------------------------------------

TRACE_ID = "9f1c2d3e-4b5a-4c6d-8e7f-0a1b2c3d4e5f"


@pytest.fixture
def handlers_client():
    """App with TransactionMiddleware and the four handlers registered like docpipe.api.main."""
    test_app = FastAPI()
    test_app.add_middleware(TransactionMiddleware)
    test_app.add_exception_handler(DocpipeException, docpipe_exception_handler)
    test_app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    test_app.add_exception_handler(RequestValidationError, validation_exception_handler)
    test_app.add_exception_handler(Exception, generic_exception_handler)

    @test_app.get("/versioned")
    async def versioned(x_api_version: Annotated[str, Header()]):
        return {"version": x_api_version}

    @test_app.get("/storage")
    async def storage():
        raise OSError(errno.ENOSPC, "No space left on device", "/srv/docpipe/flows/private.json")

    @test_app.get("/directory")
    async def directory():
        raise IsADirectoryError(errno.EISDIR, "Is a directory", "/srv/docpipe/flows")

    # The Exception handler runs in ServerErrorMiddleware, which re-raises after responding.
    return TestClient(test_app, raise_server_exceptions=False)


def test_missing_required_header_is_reported_with_header_target(handlers_client):
    response = handlers_client.get("/versioned", headers={"X-Global-Transaction-Id": TRACE_ID})

    assert response.status_code == 400
    data = response.json()
    assert data["status_code"] == 400
    assert data["trace"] == TRACE_ID
    assert len(data["errors"]) == 1
    error = data["errors"][0]
    assert error["code"] == "validation_error"
    assert error["target"] == {"type": "header", "name": "header -> x-api-version"}
    assert error["message"].startswith("Error in Field: header -> x-api-version: ")


def test_valid_header_passes_through_handlers(handlers_client):
    response = handlers_client.get("/versioned", headers={"X-API-Version": "2"})

    assert response.status_code == 200
    assert response.json() == {"version": "2"}


@pytest.mark.parametrize("path", ["/storage", "/directory"])
def test_os_error_returns_sanitized_internal_error(handlers_client, path):
    response = handlers_client.get(path, headers={"X-Global-Transaction-Id": TRACE_ID})

    assert response.status_code == 500
    data = response.json()
    assert data["status_code"] == 500
    assert data["trace"] == TRACE_ID
    assert data["errors"] == [{"code": "internal_error", "message": "An internal storage error occurred"}]
    assert "/srv/docpipe" not in response.text
