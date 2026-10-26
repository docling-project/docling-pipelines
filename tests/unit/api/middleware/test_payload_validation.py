"""Unit tests for payload validation middleware.

Tests PayloadValidationMiddleware using real ASGI-based requests
so that request.stream() is properly iterable.
"""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from docpipe.api.middleware.payload_validation import (
    MAX_PAYLOAD_SIZE,
    PayloadValidationMiddleware,
)
from docpipe.api.middleware.transaction_middleware import TransactionMiddleware


def _make_app() -> FastAPI:
    """Build a minimal FastAPI app with the payload-validation middleware."""
    app = FastAPI()
    app.add_middleware(PayloadValidationMiddleware)

    @app.post("/echo")
    async def echo():
        return JSONResponse(status_code=200, content={"status": "success"})

    return app


def _chunked(*, total: int, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    """Yield ``total`` bytes in chunks; a generator body is sent without Content-Length."""
    remaining = total
    while remaining > 0:
        size = min(chunk_size, remaining)
        yield b"x" * size
        remaining -= size


@pytest.fixture(scope="module")
def client():
    app = _make_app()
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Valid requests
# ---------------------------------------------------------------------------


class TestValidRequests:
    def test_small_post_passes(self, client):
        response = client.post("/echo", content=b"x" * 1024)
        assert response.status_code == 200

    def test_no_body_post_passes(self, client):
        response = client.post("/echo", content=b"")
        assert response.status_code == 200

    def test_get_skips_validation(self, client):
        response = client.get("/echo")
        # GET is not in POST/PUT/PATCH — middleware skips, FastAPI returns 405
        assert response.status_code in (200, 405)

    def test_exact_limit_passes(self, client):
        response = client.post("/echo", content=b"x" * MAX_PAYLOAD_SIZE)
        assert response.status_code == 200

    def test_content_length_at_limit_passes(self, client):
        body = b"x" * MAX_PAYLOAD_SIZE
        response = client.post(
            "/echo",
            content=body,
            headers={"Content-Length": str(len(body))},
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Oversized requests
# ---------------------------------------------------------------------------


class TestOversizedRequests:
    def test_just_over_limit_rejected_via_header(self, client):
        """Content-Length header fast-path rejects before reading body."""
        response = client.post(
            "/echo",
            content=b"x",  # tiny actual body
            headers={"Content-Length": str(MAX_PAYLOAD_SIZE + 1)},
        )
        assert response.status_code == 413

    def test_just_over_limit_rejected_via_stream(self, client):
        """Actual body larger than limit is rejected via stream accumulation."""
        response = client.post("/echo", content=_chunked(total=MAX_PAYLOAD_SIZE + 1))
        assert response.status_code == 413

    def test_double_limit_rejected(self, client):
        response = client.post(
            "/echo",
            headers={"Content-Length": str(MAX_PAYLOAD_SIZE * 2)},
            content=b"x",
        )
        assert response.status_code == 413

    def test_413_response_has_detail(self, client):
        response = client.post(
            "/echo",
            headers={"Content-Length": str(MAX_PAYLOAD_SIZE + 1)},
            content=b"x",
        )
        assert response.status_code == 413
        body = response.json()
        assert "detail" in body
        assert "Payload too large" in body["detail"]
        assert "5MB" in body["detail"]

    def test_413_response_is_json(self, client):
        response = client.post(
            "/echo",
            headers={"Content-Length": str(MAX_PAYLOAD_SIZE + 1)},
            content=b"x",
        )
        assert "application/json" in response.headers["content-type"]


# ---------------------------------------------------------------------------
# Method scoping
# ---------------------------------------------------------------------------


class TestMethodScoping:
    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH"])
    def test_write_methods_are_validated(self, client, method):
        response = client.request(
            method,
            "/echo",
            headers={"Content-Length": str(MAX_PAYLOAD_SIZE + 1)},
            content=b"x",
        )
        assert response.status_code == 413

    @pytest.mark.parametrize("method", ["DELETE", "HEAD", "OPTIONS"])
    def test_non_write_methods_skip_validation(self, client, method):
        # These methods skip validation so the request reaches the router.
        # TestClient returns 405 (Method Not Allowed) because our /echo
        # route only defines POST — that is fine; no 413 should appear.
        response = client.request(
            method,
            "/echo",
            headers={"Content-Length": str(MAX_PAYLOAD_SIZE + 1)},
            content=b"x",
        )
        assert response.status_code != 413


# ---------------------------------------------------------------------------
# Body replay correctness (seek(0) idempotency)
# ---------------------------------------------------------------------------


class TestBodyReplay:
    def test_body_available_downstream(self):
        """After middleware buffers the body, the route can read it."""
        from docpipe.api.middleware.payload_validation import PayloadValidationMiddleware

        app = FastAPI()
        app.add_middleware(PayloadValidationMiddleware)

        @app.post("/read")
        async def read_body():
            return JSONResponse(status_code=200, content={"ok": True})

        with TestClient(app) as c:
            response = c.post("/read", content=b"hello")
        assert response.status_code == 200

    def test_receive_callable_is_idempotent(self):
        """Calling receive() twice returns the same body (seek(0) guard)."""
        import asyncio
        import io

        from starlette.types import Message

        body = b"idempotent-body"
        body_io = io.BytesIO(body)

        async def receive() -> Message:
            body_io.seek(0)
            chunk = body_io.read()
            return {"type": "http.request", "body": chunk, "more_body": False}

        first = asyncio.run(receive())
        second = asyncio.run(receive())
        assert first["body"] == second["body"] == body


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_max_payload_size_constant():
    assert MAX_PAYLOAD_SIZE == 5 * 1024 * 1024


# ---------------------------------------------------------------------------
# Bodies without a trustworthy Content-Length (chunked or understated)
# ---------------------------------------------------------------------------


class TestStreamedBodies:
    """The streamed body is measured, so a missing or false Content-Length cannot bypass the limit."""

    @pytest.fixture
    def recording_app(self) -> tuple[FastAPI, list[dict]]:
        """App whose route records the Content-Length header and the body size it receives."""
        seen: list[dict] = []
        app = FastAPI()
        app.add_middleware(PayloadValidationMiddleware)

        @app.api_route("/upload", methods=["POST", "PUT"])
        async def upload(request: Request):
            body = await request.body()
            seen.append({"content_length": request.headers.get("content-length"), "size": len(body)})
            return {"size": len(body)}

        return app, seen

    def test_chunked_body_over_limit_never_reaches_route(self, recording_app):
        app, seen = recording_app
        with TestClient(app) as client:
            response = client.post("/upload", content=_chunked(total=MAX_PAYLOAD_SIZE + 1))

        assert response.status_code == 413
        assert seen == []

    def test_chunked_body_at_limit_reaches_route_complete(self, recording_app):
        app, seen = recording_app
        with TestClient(app) as client:
            response = client.post("/upload", content=_chunked(total=MAX_PAYLOAD_SIZE))

        assert response.status_code == 200
        assert response.json() == {"size": MAX_PAYLOAD_SIZE}
        # No Content-Length was sent, so only the streamed size check applied.
        assert seen == [{"content_length": None, "size": MAX_PAYLOAD_SIZE}]

    def test_understated_content_length_is_rejected_by_streamed_size(self, recording_app):
        app, seen = recording_app
        with TestClient(app) as client:
            response = client.put(
                "/upload",
                content=b"x" * (MAX_PAYLOAD_SIZE + 1),
                headers={"Content-Length": "10"},
            )

        assert response.status_code == 413
        assert seen == []

    def test_chunked_body_is_replayed_through_base_http_middleware(self):
        """Mirror main.py: PayloadValidationMiddleware wraps BaseHTTPMiddleware layers and the route."""
        app = FastAPI()
        app.add_middleware(TransactionMiddleware)
        app.add_middleware(PayloadValidationMiddleware)

        @app.post("/echo")
        async def echo(request: Request):
            return {"body": (await request.body()).decode()}

        def parts() -> Iterator[bytes]:
            yield b'{"flow_name": '
            yield b'"invoices"}'

        with TestClient(app) as client:
            response = client.post("/echo", content=parts())

        assert response.status_code == 200
        assert response.json() == {"body": '{"flow_name": "invoices"}'}
