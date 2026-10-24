"""Payload validation middleware for FastAPI application.

This module provides middleware for validating request payload sizes
to prevent excessive memory usage and potential DoS attacks.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

MAX_PAYLOAD_SIZE = 5 * 1024 * 1024  # 5 MB


class PayloadValidationMiddleware:
    """Reject bodies that exceed MAX_PAYLOAD_SIZE before they reach the route.

    Implemented as a raw ASGI callable rather than BaseHTTPMiddleware so the
    buffered body is passed via the ``receive`` argument, which downstream
    BaseHTTPMiddleware layers actually use.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)

        if request.method not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return

        # Reject early if the declared size already exceeds the limit.
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_PAYLOAD_SIZE:
            response = JSONResponse(
                status_code=413,
                content={"detail": f"Payload too large. Maximum size is {MAX_PAYLOAD_SIZE / (1024 * 1024):.0f}MB"},
            )
            await response(scope, receive, send)
            return

        # Stream the body to catch spoofed or absent Content-Length headers.
        body = b""
        async for chunk in request.stream():
            body += chunk
            if len(body) > MAX_PAYLOAD_SIZE:
                response = JSONResponse(
                    status_code=413,
                    content={"detail": f"Payload too large. Maximum size is {MAX_PAYLOAD_SIZE / (1024 * 1024):.0f}MB"},
                )
                await response(scope, receive, send)
                return

        consumed = False

        async def replay_receive() -> dict:
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay_receive, send)


# Keep the function-style alias so existing registrations that use
# ``app.middleware("http")(validate_payload_size)`` continue to work.
# FastAPI's @app.middleware("http") decorator wraps the callable in a
# BaseHTTPMiddleware; we bypass that by using the class directly.
async def validate_payload_size(request: Request, call_next):
    """Thin shim kept for backwards compatibility with app.middleware('http').

    Delegates to PayloadValidationMiddleware logic inline since we cannot
    easily call the class from a call_next-style wrapper and still control
    the receive argument.  This version is intentionally simple: it reads the
    body for size enforcement and replays it by patching request._receive
    (works for direct ASGI apps that do not layer BaseHTTPMiddleware above us).

    For full compatibility with BaseHTTPMiddleware stacks, register
    PayloadValidationMiddleware via app.add_middleware() instead.

    Args:
        request: The incoming FastAPI request object
        call_next: The next middleware or route handler in the chain

    Returns:
        JSONResponse with 413 status if payload is too large, otherwise
        the response from the next handler in the chain
    """
    if request.method not in ("POST", "PUT", "PATCH"):
        return await call_next(request)

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_PAYLOAD_SIZE:
        return JSONResponse(
            status_code=413,
            content={"detail": f"Payload too large. Maximum size is {MAX_PAYLOAD_SIZE / (1024 * 1024):.0f}MB"},
        )

    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_PAYLOAD_SIZE:
            return JSONResponse(
                status_code=413,
                content={"detail": f"Payload too large. Maximum size is {MAX_PAYLOAD_SIZE / (1024 * 1024):.0f}MB"},
            )

    consumed = False

    async def replay_receive() -> dict:
        """Replay the buffered body once for downstream handlers."""
        nonlocal consumed
        if not consumed:
            consumed = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.request", "body": b"", "more_body": False}

    request._receive = replay_receive  # type: ignore[attr-defined]
    return await call_next(request)
