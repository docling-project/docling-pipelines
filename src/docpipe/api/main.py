"""FastAPI application main entry point.

This module configures the FastAPI application with:
- Transaction middleware for request tracking across the application
- Security headers middleware for enhanced security
- CORS middleware for cross-origin resource sharing
- Standardized error handlers following IBM Cloud standards
- OAuth2/OIDC authentication with LDAP support
"""

import logging
import os
import shutil
import subprocess  # nosec B404
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, cast

import httpx
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from docpipe.api.api_router import api_router
from docpipe.api.auth.dependencies import get_current_user
from docpipe.api.auth.jwt_handler import JWTClaims, JWTConfig, create_access_token
from docpipe.api.auth.ldap_auth import LDAPAuthenticator, LDAPConfig
from docpipe.api.auth.models import LoginRequest, TokenResponse, User
from docpipe.api.auth.oauth2_routes import router as oauth2_router
from docpipe.api.middleware.api_logging_middleware import ApiLoggingMiddleware
from docpipe.api.middleware.error_handler import (
    docpipe_exception_handler,
    generic_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from docpipe.api.middleware.payload_validation import PayloadValidationMiddleware
from docpipe.api.middleware.rate_limit import (
    RATE_LIMIT_WINDOW_SECONDS,
    check_login_rate_limit,
)
from docpipe.api.middleware.security_headers import SecurityHeadersMiddleware
from docpipe.api.middleware.transaction_middleware import TransactionMiddleware
from docpipe.api.openapi import build_custom_openapi
from docpipe.core.constants.constants import EnvironmentVariables
from docpipe.core.event_streaming.factory import EventStreamingFactory
from docpipe.core.job_management.adapters.config.job_management_factory import get_default_factory
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.utils.infrastructure.logging import (
    configure_third_party_loggers,
    set_dpk_log_level_from_ds_log_level,
    setup_logging,
)

set_dpk_log_level_from_ds_log_level()
setup_logging()
log_level_name = os.getenv(EnvironmentVariables.DS_LOG_LEVEL, "INFO").upper()
log_level = logging.getLevelName(log_level_name)
_handler = logging.StreamHandler(sys.stdout)
configure_third_party_loggers(log_level=log_level, handler=_handler)

logger = logging.getLogger(__name__)

# Hop-by-hop headers must not be forwarded by a proxy — they are connection-level
# and meaningful only between two adjacent nodes. Forwarding them intact causes
# content-length / transfer-encoding mismatches and broken chunked responses.
_HOP_BY_HOP_HEADERS: frozenset[str] = frozenset(
    {
        "connection",
        "content-length",  # httpx recomputes from actual body; forwarding causes duplicate header
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)


def _wait_for_bff(*, bff_url: str, retries: int = 20, delay: float = 0.2) -> bool:
    """Poll the BFF /health endpoint until it responds with a 2xx status.

    Args:
        bff_url: Base URL of the BFF server (e.g. http://localhost:3001).
        retries: Maximum number of attempts before giving up.
        delay: Seconds to wait between attempts.

    Returns:
        True if the BFF became healthy within the retry budget, False otherwise.
    """
    for _ in range(retries):
        try:
            response = httpx.get(f"{bff_url}/health", timeout=0.5)
            if 200 <= response.status_code < 300:
                return True
        except httpx.TransportError:
            pass
        time.sleep(delay)
    return False


def _start_bff() -> tuple[subprocess.Popen | None, str]:
    """Start the bundled BFF (Node/Express) sidecar.

    The BFF bundle is shipped inside the wheel at docpipe/api/bff/server.cjs.
    It only requires `node` — no npm or node_modules needed at runtime.
    No-op if node is not available or the bundle is missing (e.g. wheel built without npm).
    No-op if BFF_URL is already set in the environment (e.g. injected by a pod spec or
    docker-compose), which means the BFF is already running as a separate container.

    Returns:
        A (process, bff_url) tuple. Both are empty/None when the sidecar is not started.
        The caller falls back to the BFF_URL environment variable when the returned URL
        is empty (e.g. external BFF pre-configured via docker-compose or k8s env injection).
    """
    if os.getenv("BFF_URL"):
        logger.info("BFF_URL already set - skipping sidecar start (external BFF assumed)")
        return None, ""

    bff_bundle = Path(__file__).parent / "bff" / "server.cjs"
    if not bff_bundle.exists():
        logger.warning("BFF not started: bff/server.cjs not found in wheel")
        return None, ""
    node_bin = shutil.which("node")
    if not node_bin:
        logger.warning("BFF not started: node not found in PATH")
        return None, ""

    bff_port = int(os.getenv("BFF_PORT", "3001"))
    fastapi_port = int(os.getenv("FASTAPI_PORT", "8080"))
    env = {
        **os.environ,
        "BACKEND_API_URL": f"http://localhost:{fastapi_port}",
        "BFF_PORT": str(bff_port),
    }
    logger.info("Starting BFF sidecar on port %d...", bff_port)
    # Inherit parent stdout/stderr (stdout=None, stderr=None is the default, stated
    # explicitly for clarity). Using subprocess.PIPE without a reader thread would
    # fill the OS pipe buffer (~64 KB) and deadlock the child process under load.
    process = subprocess.Popen(  # nosec B603
        [node_bin, str(bff_bundle)],
        env=env,
        stdout=None,
        stderr=None,
    )
    bff_url = f"http://localhost:{bff_port}"
    if not _wait_for_bff(bff_url=bff_url):
        logger.warning("BFF sidecar did not become healthy within startup budget - continuing anyway")
    logger.info("BFF sidecar started (pid=%d)", process.pid)
    return process, bff_url


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan."""
    try:
        get_default_factory().initialize_storage()
    except Exception as exc:
        msg = f"STARTUP ERROR — storage initialization failed: {exc}"
        print(msg, file=sys.stderr, flush=True)
        logger.error("Storage initialization failed during startup: %s", exc)
        raise
    # Register secret providers (no-op when secrets.vault.enabled=false in config)
    from docpipe.integrations.secrets.vault_initializer import initialize_secret_providers

    initialize_secret_providers()
    event_listener = EventStreamingFactory.create_kafka_listener()
    bff_process, started_bff_url = _start_bff()
    # Shared AsyncClient — reused across all proxy_to_bff requests so the
    # connection pool is maintained and TCP overhead is paid once, not per request.
    # Use the URL returned by the sidecar, or fall back to a pre-configured external
    # BFF_URL (set by docker-compose / k8s env injection before the process starts).
    bff_url = (started_bff_url or os.getenv("BFF_URL", "")).rstrip("/")
    app.state.bff_client = httpx.AsyncClient(timeout=30.0, base_url=bff_url) if bff_url else None

    # Wire custom operators catalog path into DOCPIPE_CUSTOM_OPERATORS for pipeline runtime discovery
    from docpipe.utils.infrastructure.filesystem import get_data_path

    custom_operators_dir = get_data_path(sub_dir="/custom_operators")
    existing_custom_ops = os.getenv(EnvironmentVariables.DOCPIPE_CUSTOM_OPERATORS, "")
    custom_op_paths = [p for p in existing_custom_ops.split(",") if p.strip()]
    if custom_operators_dir not in custom_op_paths:
        custom_op_paths.append(custom_operators_dir)
        os.environ[EnvironmentVariables.DOCPIPE_CUSTOM_OPERATORS] = ",".join(custom_op_paths)

    try:
        if event_listener is not None:
            event_listener.start()
        yield
    finally:
        if event_listener is not None:
            await event_listener.stop()
        if app.state.bff_client is not None:
            await app.state.bff_client.aclose()
        if bff_process:
            logger.info("Shutting down BFF sidecar...")
            bff_process.terminate()
            # Do not call bff_process.wait() — it is a synchronous blocking call
            # inside an async context and would stall the uvicorn event loop during
            # shutdown. SIGTERM is sufficient; the OS reaps the child after it exits.


app = FastAPI(
    title="Docpipe Opensource API",
    description="API for Docpipe opensource",
    version="0.1.0",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    openapi_url="/api/v1/openapi.json",
    servers=[
        {"url": "http://localhost:8080", "description": "Local development server"},
        {"url": "https://api.docpipe.example.com", "description": "Production server"},
    ],
    openapi_tags=[
        {
            "name": "Projects",
            "description": "Project management operations for creating, listing, retrieving, updating, and deleting projects",
        },
        {
            "name": "Flows",
            "description": "Flow management operations for creating, reading, updating, and deleting data processing flows",
        },
        {
            "name": "Operators",
            "description": "Operator metadata operations for retrieving information about available operators, their configurations, and capabilities",
        },
        {
            "name": "Providers",
            "description": "Provider operations for listing available models from LLM/embedding providers (ollama, watsonx)",
        },
        {
            "name": "job-runs",
            "description": "Job run operations for creating, listing, monitoring, canceling, and deleting executions",
        },
        {
            "name": "System",
            "description": "System health and status endpoints",
        },
    ],
    lifespan=lifespan,
)


# Override the default OpenAPI schema generator
cast(Any, app).openapi = build_custom_openapi(app)

# Middleware registered in reverse execution order (last added = outermost).
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(ApiLoggingMiddleware)
app.add_middleware(TransactionMiddleware)

cors_origins_env = os.getenv("CORS_ORIGINS", "http://localhost:3000")
allowed_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    ldap_authenticator: LDAPAuthenticator | None = None
    ldap_config: LDAPConfig | None = LDAPConfig()
    if ldap_config:
        ldap_authenticator = LDAPAuthenticator(ldap_config)

    try:
        jwt_config: JWTConfig | None = JWTConfig()
        logger.info("Authentication configurations initialized successfully")
    except Exception as e:
        logger.warning(
            "JWT secret key not configured: %s. Login and token issuance "
            "are disabled. Set JWT_SECRET_KEY to enable authentication.",
            e,
        )
        jwt_config = None

except Exception as e:
    logger.error("Failed to initialize authentication configurations: %s", e)
    ldap_config = None
    jwt_config = None
    ldap_authenticator = None

# More specific handlers first, then generic.
app.add_exception_handler(DocpipeException, cast(Any, docpipe_exception_handler))
app.add_exception_handler(StarletteHTTPException, cast(Any, http_exception_handler))
app.add_exception_handler(RequestValidationError, cast(Any, validation_exception_handler))
app.add_exception_handler(Exception, generic_exception_handler)


@app.get(
    "/",
    tags=["system"],
    operation_id="read_root",
    summary="API root endpoint",
)
async def root():
    """Root endpoint returning welcome message."""
    from docpipe.api.dto.flow_dto import RootResponse

    return RootResponse(message="Welcome to Docpipe Opensource API")


@app.get(
    "/health",
    tags=["system"],
    operation_id="health_check",
    summary="Health check endpoint",
)
async def health_check():
    """Health check endpoint returning service status."""
    from docpipe.api.dto.flow_dto import HealthCheckResponse

    return HealthCheckResponse(status="healthy")


@app.post("/auth/login", response_model=TokenResponse)
async def login(credentials: LoginRequest, request: Request):
    """Authenticate user via LDAP and return JWT token.

    Args:
        credentials: Login credentials (username and password)
        request: FastAPI request object (used for rate limiting)

    Returns:
        TokenResponse with access token

    Raises:
        HTTPException: If authentication fails or LDAP is not configured
    """
    client_ip = request.client.host if request.client else "unknown"
    if not check_login_rate_limit(client_ip=client_ip):
        logger.warning("Rate limit exceeded for login from IP: %s", client_ip)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many login attempts. Please wait {RATE_LIMIT_WINDOW_SECONDS} seconds before retrying.",
        )

    if ldap_authenticator is None or jwt_config is None:
        logger.error("Authentication not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service not configured",
        )

    try:
        user: User | None = ldap_authenticator.authenticate(credentials.username, credentials.password)

        if not user:
            logger.warning("Failed login attempt for user: %s", credentials.username)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
            )

        token_data = {
            JWTClaims.USERNAME: user.username,
            JWTClaims.EMAIL: user.email,
            JWTClaims.FULL_NAME: user.full_name,
        }
        access_token: str = create_access_token(token_data, jwt_config)

        logger.info("User logged in successfully: %s", credentials.username)
        return TokenResponse(access_token=access_token)

    except (HTTPException, DocpipeException):
        raise
    except Exception as e:
        logger.error("Login error for user %s: %s", credentials.username, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication service error",
        ) from e


@app.get("/auth/me", response_model=User)
async def get_current_user_info(current_user: Annotated[User, Depends(get_current_user)]):
    """Get current authenticated user information.

    Args:
        current_user: Current authenticated user from JWT token

    Returns:
        User information
    """
    return current_user


@app.get("/protected")
async def protected_route(current_user: Annotated[User, Depends(get_current_user)]):
    """Example protected endpoint requiring authentication.

    Args:
        current_user: Current authenticated user from JWT token

    Returns:
        Welcome message with username
    """
    return {"message": f"Hello {current_user.username}", "user": current_user}


app.include_router(oauth2_router)
app.add_middleware(PayloadValidationMiddleware)
app.include_router(api_router)


# BFF proxy: forward /api/* to the BFF server.
# BFF_URL is set by _start_bff() in lifespan — read dynamically inside the handler.
# /api/v1/* is matched by api_router above and never reaches this route.
@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], operation_id="proxy_to_bff")
async def proxy_to_bff(path: str, request: Request):
    """Proxy /api/* requests to the BFF server when BFF_URL is set.

    Uses the shared AsyncClient from app.state so the connection pool is reused
    across requests. Falls back to a 404 when no BFF client is available.
    """
    client: httpx.AsyncClient | None = request.app.state.bff_client
    if client is None:
        raise HTTPException(status_code=404, detail="Not found")

    # Build target path + query string.
    target = f"/api/{path}"
    params = str(request.url.query)
    if params:
        target = f"{target}?{params}"

    # Forward all inbound headers except hop-by-hop and host (host is rewritten
    # by httpx to match the BFF base_url).
    # Preserve X-Transaction-ID so the full request chain is traceable end-to-end.
    forward_headers = {
        k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP_HEADERS and k.lower() != "host"
    }

    try:
        response = await client.request(
            method=request.method,
            url=target,
            headers=forward_headers,
            content=request.stream(),  # stream body chunk-by-chunk — avoids OOM on large payloads
        )
    except httpx.ConnectError as exc:
        raise HTTPException(status_code=503, detail="BFF unavailable") from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="BFF request timed out") from exc

    # Strip hop-by-hop headers from the upstream response before forwarding to
    # the client — they are meaningless outside the BFF→FastAPI connection.
    response_headers = {k: v for k, v in response.headers.items() if k.lower() not in _HOP_BY_HOP_HEADERS}
    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=response_headers,
    )


def mount_ui_routes(target_app: FastAPI, ui_static_dir: Path) -> None:
    """Register /ui static file and SPA fallback routes on the given app.

    No-op (with a warning) when ui_static_dir does not exist — e.g. in
    environments where the frontend has not been built. Extracted as a
    standalone function so it can be exercised in tests against a
    temporary directory, independent of the real build output.
    """
    if not ui_static_dir.exists():
        logger.warning("Frontend static directory not found at %s. UI will not be available.", ui_static_dir)
        return

    # Mount assets directory for CSS/JS files
    assets_dir = ui_static_dir / "assets"
    if assets_dir.exists():
        target_app.mount("/ui/assets", StaticFiles(directory=assets_dir), name="ui-assets")

    # Resolve once at mount time so serve_ui does not pay the syscall cost on
    # every request. All path safety checks are performed against this resolved root.
    _safe_root = ui_static_dir.resolve()

    # Serve index.html for root /ui path
    @target_app.get("/ui")
    async def serve_ui_root():
        """Serve the SPA index.html for the /ui root path."""
        return FileResponse(_safe_root / "index.html")

    # Catch-all route for client-side routing (must be last)
    @target_app.get("/ui/{full_path:path}")
    async def serve_ui(full_path: str):
        """Serve static assets by path or fall back to index.html for SPA routes.

        Path traversal protection:
        - resolved_path.is_relative_to() blocks all "../.." escape attempts.
        - An additional symlink check ensures a symlink inside the static dir
          cannot point outside the root (defence-in-depth for volume mounts).
        """
        if "." in full_path.split("/")[-1]:
            # Resolve expands all ".." components to an absolute path.
            file_path = (_safe_root / full_path).resolve()
            # Guard 1: the resolved path must remain inside the static root.
            if not file_path.is_relative_to(_safe_root):
                raise HTTPException(status_code=400, detail="Invalid path")
            # Guard 2: if the raw path is a symlink, its target must also be
            # inside the root — prevents symlink-escape attacks on volume mounts.
            raw_path = _safe_root / full_path
            if raw_path.is_symlink() and not raw_path.resolve().is_relative_to(_safe_root):
                raise HTTPException(status_code=400, detail="Invalid path")
            if file_path.exists() and file_path.is_file():
                return FileResponse(file_path)
            raise HTTPException(status_code=404, detail="Asset not found")
        # Extension-less paths are client-side routes — serve the SPA shell.
        return FileResponse(_safe_root / "index.html")

    logger.info("Frontend static files mounted from %s", ui_static_dir)


# Mount static files for React frontend
static_dir = Path(__file__).parent / "static"
mount_ui_routes(app, static_dir)


def run() -> None:
    """Start the Uvicorn server for the Docpipe API."""
    uvicorn.run(
        "docpipe.api.main:app",
        host="127.0.0.1",
        port=8080,
        reload=True,
    )


if __name__ == "__main__":
    run()
