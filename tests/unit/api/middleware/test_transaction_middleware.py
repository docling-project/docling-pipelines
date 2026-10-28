"""Tests for transaction middleware."""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import Response

from docpipe.api.middleware.transaction_middleware import TransactionMiddleware, get_transaction_id


@pytest.fixture
def mock_request():
    """Create a mock request."""
    request = MagicMock(spec=Request)
    request.state = MagicMock()
    request.headers = {}
    return request


@pytest.fixture
def mock_call_next():
    """Create a mock call_next function."""

    async def call_next(request):
        return Response(content="test", status_code=200)

    return call_next


@pytest.mark.anyio
async def test_transaction_middleware_generates_id_when_not_provided(mock_request, mock_call_next):
    """Test that middleware generates transaction ID when not provided in header."""
    middleware = TransactionMiddleware(app=MagicMock())

    response = await middleware.dispatch(mock_request, mock_call_next)

    # Verify transaction ID was set in request state
    assert hasattr(mock_request.state, "transaction_id")
    transaction_id = mock_request.state.transaction_id

    # Verify it's a valid UUID
    uuid.UUID(transaction_id)

    # Verify transaction ID was added to response headers
    assert "X-Transaction-ID" in response.headers
    assert response.headers["X-Transaction-ID"] == transaction_id


@pytest.mark.anyio
async def test_transaction_middleware_uses_global_transaction_id(mock_request, mock_call_next):
    """Test that middleware uses X-Global-Transaction-Id from request header."""
    provided_id = "test-transaction-123"
    mock_request.headers = {"X-Global-Transaction-Id": provided_id}

    middleware = TransactionMiddleware(app=MagicMock())

    response = await middleware.dispatch(mock_request, mock_call_next)

    # Verify provided transaction ID was used
    assert mock_request.state.transaction_id == provided_id

    # Verify same ID was added to response headers as X-Transaction-ID
    assert response.headers["X-Transaction-ID"] == provided_id


@pytest.mark.anyio
async def test_transaction_middleware_preserves_response_content(mock_request, mock_call_next):
    """Test that middleware preserves response content and status."""
    middleware = TransactionMiddleware(app=MagicMock())

    response = await middleware.dispatch(mock_request, mock_call_next)

    # Verify response content and status are preserved
    assert response.status_code == 200
    assert response.body == b"test"


@pytest.mark.anyio
async def test_transaction_middleware_handles_empty_header(mock_request, mock_call_next):
    """Test that middleware handles empty X-Global-Transaction-Id header."""
    mock_request.headers = {"X-Global-Transaction-Id": ""}

    middleware = TransactionMiddleware(app=MagicMock())

    await middleware.dispatch(mock_request, mock_call_next)

    # Verify new transaction ID was generated (empty string is falsy)
    assert mock_request.state.transaction_id
    assert mock_request.state.transaction_id != ""

    # Verify it's a valid UUID
    uuid.UUID(mock_request.state.transaction_id)


@pytest.mark.anyio
async def test_transaction_middleware_unique_ids_per_request(mock_call_next):
    """Test that each request gets a unique transaction ID."""
    middleware = TransactionMiddleware(app=MagicMock())

    # Create two separate requests
    request1 = MagicMock(spec=Request)
    request1.state = MagicMock()
    request1.headers = {}

    request2 = MagicMock(spec=Request)
    request2.state = MagicMock()
    request2.headers = {}

    # Process both requests
    response1 = await middleware.dispatch(request1, mock_call_next)
    response2 = await middleware.dispatch(request2, mock_call_next)

    # Verify each request got a unique transaction ID
    id1 = request1.state.transaction_id
    id2 = request2.state.transaction_id

    assert id1 != id2
    assert response1.headers["X-Transaction-ID"] == id1
    assert response2.headers["X-Transaction-ID"] == id2


@pytest.mark.anyio
async def test_transaction_middleware_response_header_format(mock_request, mock_call_next):
    """Test that middleware returns transaction ID in X-Transaction-ID response header."""
    global_id = "global-trace-456"
    mock_request.headers = {"X-Global-Transaction-Id": global_id}

    middleware = TransactionMiddleware(app=MagicMock())

    response = await middleware.dispatch(mock_request, mock_call_next)

    # Verify global transaction ID was used
    assert mock_request.state.transaction_id == global_id

    # Verify response uses X-Transaction-ID header (not X-Global-Transaction-Id)
    assert response.headers["X-Transaction-ID"] == global_id
    assert "X-Global-Transaction-Id" not in response.headers


@pytest.mark.anyio
async def test_transaction_middleware_generated_id_in_response(mock_request, mock_call_next):
    """Test that generated transaction ID is returned in X-Transaction-ID response header."""
    middleware = TransactionMiddleware(app=MagicMock())

    response = await middleware.dispatch(mock_request, mock_call_next)

    # Verify transaction ID was generated
    transaction_id = mock_request.state.transaction_id
    uuid.UUID(transaction_id)  # Verify it's a valid UUID

    # Verify response uses X-Transaction-ID header
    assert response.headers["X-Transaction-ID"] == transaction_id
    assert "X-Global-Transaction-Id" not in response.headers


class TestTransactionMiddlewareMetrics:
    """Test that TransactionMiddleware records HTTP request metrics."""

    @pytest.fixture
    def mock_request(self):
        request = MagicMock(spec=Request)
        request.state = MagicMock()
        request.headers = {}
        request.url.path = "/api/v1/operators"
        request.method = "GET"
        return request

    @pytest.mark.anyio
    async def test_record_http_request_called_on_success(self, mock_request):
        """record_http_request should be called with correct args after a 200 response."""

        async def call_next(request):
            return Response(content="ok", status_code=200)

        mock_telemetry = MagicMock()
        mock_telemetry.start_span.return_value = None

        with patch(
            "docpipe.api.middleware.transaction_middleware.get_telemetry_service",
            return_value=mock_telemetry,
        ):
            middleware = TransactionMiddleware(app=MagicMock())
            await middleware.dispatch(mock_request, call_next)

        mock_telemetry.record_http_request.assert_called_once()
        call_kwargs = mock_telemetry.record_http_request.call_args.kwargs
        assert call_kwargs["method"] == "GET"
        assert call_kwargs["path"] == "/api/v1/operators"
        assert call_kwargs["status_code"] == 200
        assert call_kwargs["duration_ms"] >= 0

    @pytest.mark.anyio
    async def test_record_http_request_called_on_server_error(self, mock_request):
        """record_http_request should be called even on 500 responses."""

        async def call_next(request):
            return Response(content="err", status_code=500)

        mock_telemetry = MagicMock()
        mock_telemetry.start_span.return_value = None

        with patch(
            "docpipe.api.middleware.transaction_middleware.get_telemetry_service",
            return_value=mock_telemetry,
        ):
            middleware = TransactionMiddleware(app=MagicMock())
            await middleware.dispatch(mock_request, call_next)

        call_kwargs = mock_telemetry.record_http_request.call_args.kwargs
        assert call_kwargs["status_code"] == 500

    @pytest.mark.anyio
    async def test_duration_is_positive(self, mock_request):
        """duration_ms passed to record_http_request must be >= 0."""
        import asyncio

        async def call_next(request):
            await asyncio.sleep(0.01)
            return Response(content="ok", status_code=200)

        mock_telemetry = MagicMock()
        mock_telemetry.start_span.return_value = None

        with patch(
            "docpipe.api.middleware.transaction_middleware.get_telemetry_service",
            return_value=mock_telemetry,
        ):
            middleware = TransactionMiddleware(app=MagicMock())
            await middleware.dispatch(mock_request, call_next)

        duration_ms = mock_telemetry.record_http_request.call_args.kwargs["duration_ms"]
        assert duration_ms >= 0

    @pytest.mark.anyio
    async def test_span_ended_in_finally(self, mock_request):
        """end_span must be called in the finally block even if call_next raises."""

        async def call_next(request):
            raise RuntimeError("handler crashed")

        mock_telemetry = MagicMock()
        mock_span = MagicMock()
        mock_telemetry.start_span.return_value = mock_span

        with patch(
            "docpipe.api.middleware.transaction_middleware.get_telemetry_service",
            return_value=mock_telemetry,
        ):
            middleware = TransactionMiddleware(app=MagicMock())
            with pytest.raises(RuntimeError):
                await middleware.dispatch(mock_request, call_next)

        mock_telemetry.end_span.assert_called_once_with(mock_span)


class TestTransactionIdContext:
    """get_transaction_id() exposes the middleware's ID to code running inside the request."""

    @pytest.fixture
    def client(self):
        app = FastAPI()
        app.add_middleware(TransactionMiddleware)

        @app.get("/whoami")
        async def whoami(request: Request):
            return {"context": get_transaction_id(), "state": request.state.transaction_id}

        return TestClient(app)

    def test_context_holds_the_global_transaction_id_header(self, client):
        response = client.get("/whoami", headers={"X-Global-Transaction-Id": "caller-trace-42"})

        assert response.json() == {"context": "caller-trace-42", "state": "caller-trace-42"}
        assert response.headers["X-Transaction-ID"] == "caller-trace-42"

    def test_context_holds_the_generated_id_when_header_missing(self, client):
        response = client.get("/whoami")

        body = response.json()
        uuid.UUID(body["context"])
        assert body["context"] == body["state"] == response.headers["X-Transaction-ID"]
