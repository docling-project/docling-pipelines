# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""OAuth2 authentication routes."""

import secrets
import threading
import time
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.responses import RedirectResponse
from fastapi.responses import Response as FastAPIResponse

from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.utils.infrastructure.audit import sanitize_for_log
from docpipe.utils.infrastructure.logging import get_logger

from .config import get_auth_settings
from .jwt_handler import JWTClaims, JWTConfig, create_access_token
from .models import AuthProvider
from .oauth2_config import OAuth2Config, get_oauth2_config
from .oauth2_provider import OAuth2Provider, get_oauth2_provider
from .session_cookie import COOKIE_SAMESITE, is_secure_request, set_session_cookie

logger = get_logger(__name__)

router = APIRouter(prefix="/auth/oauth2", tags=["oauth2"])

# In-process TTL state store for OAuth2 CSRF tokens.
# Each entry: state_key -> (return_to, expiry_monotonic, nonce). The nonce also lives in a
# short-lived HttpOnly cookie set by /authorize, which binds the login to the browser that
# started it. Not suitable for multi-worker/multi-pod deployments (needs sticky routing for
# the login round trip) - replace with a shared expiring store (e.g. Redis) for
# horizontally-scaled production.
_STATE_TTL_SECONDS = 600  # 10 minutes
_MAX_STATE_ENTRIES = 10_000
_state_store: dict[str, tuple[str, float, str]] = {}
_state_lock = threading.Lock()

NONCE_COOKIE_NAME = "docpipe_oauth2_nonce"
NONCE_COOKIE_PATH = "/auth/oauth2"

# The SPA is mounted under /ui and React Router strips that basename from its paths, so a
# relative return_to without the prefix is resolved below it.
UI_PREFIX = "/ui"
DEFAULT_RETURN_TO = "/ui/projects"


def _is_same_origin(url: str) -> bool:
    """Return True only if url is a relative path (no scheme or host)."""
    if not url:
        return True
    parsed = urlparse(url)
    return parsed.scheme == "" and parsed.netloc == ""


def validate_return_to(*, value: str | None) -> str | None:
    """Return ``value`` when it is a safe same-origin relative path, otherwise ``None``.

    Accepts only values that start with a single ``/`` and have no scheme, host, backslash
    or control character. A value starting with ``//`` (protocol-relative) is refused.

    Args:
        value: Untrusted ``return_to`` / ``redirect_after`` value.

    Returns:
        The unchanged value when safe, or ``None`` when absent or unsafe.
    """
    if not value or not value.startswith("/") or value.startswith("//"):
        return None
    if "\\" in value or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return None
    if not _is_same_origin(value):
        return None
    return value


def resolve_return_to(*, value: str | None) -> str:
    """Resolve a stored ``return_to`` to the redirect target below ``/ui``.

    A safe path that does not already start with ``/ui`` gets the prefix. An absent or unsafe
    value falls back to ``/ui/projects``. The value is validated again here as defense in
    depth, even though ``/authorize`` already dropped unsafe values.

    Args:
        value: Stored ``return_to`` value.

    Returns:
        A same-origin path starting with ``/ui``.
    """
    safe = validate_return_to(value=value)
    if safe is None:
        return DEFAULT_RETURN_TO
    path_only = safe.split("?", 1)[0].split("#", 1)[0]
    if path_only == UI_PREFIX or path_only.startswith(f"{UI_PREFIX}/"):
        return safe
    return f"{UI_PREFIX}{safe}"


def _store_state(*, state: str, redirect_url: str, nonce: str = "") -> None:
    """Record state token with TTL. Raises RuntimeError when the store is at capacity."""
    now = time.monotonic()
    expiry = now + _STATE_TTL_SECONDS
    with _state_lock:
        expired = [k for k, (_, exp, _nonce) in _state_store.items() if now > exp]
        for k in expired:
            del _state_store[k]
        if len(_state_store) >= _MAX_STATE_ENTRIES:
            raise RuntimeError("OAuth2 state store is full")
        _state_store[state] = (redirect_url, expiry, nonce)


def _consume_state(*, state: str, nonce: str | None) -> str | None:
    """Remove a state token and return its stored ``return_to``, or None when it is not valid.

    The state is single-use: it is removed even when the nonce check fails. A missing or
    mismatched nonce makes the state invalid.

    Args:
        state: State parameter from the callback.
        nonce: Value of the nonce cookie sent with the callback, if any.

    Returns:
        The stored ``return_to`` (possibly empty), or None for an unknown, expired or
        browser-mismatched state.
    """
    with _state_lock:
        entry = _state_store.pop(state, None)
    if entry is None:
        return None
    redirect_url, expiry, stored_nonce = entry
    if time.monotonic() > expiry:
        return None
    if not nonce or not stored_nonce or not secrets.compare_digest(nonce.encode(), stored_nonce.encode()):
        return None
    return redirect_url


def get_oauth2_provider_instance(
    provider: str | None = Query(None, description="OAuth2 provider (google, azure, generic)"),
) -> OAuth2Provider:
    """Get OAuth2 provider instance.

    Args:
        provider: OAuth2 provider name

    Returns:
        OAuth2Provider instance

    Raises:
        HTTPException: If OAuth2 is not enabled or configured
    """
    config = get_oauth2_config(provider)

    if not config.oauth2_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth2 authentication is not enabled",
        )

    if not config.oauth2_client_id or not config.oauth2_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth2 is not properly configured",
        )

    return get_oauth2_provider(config)


@router.get("/authorize")
async def oauth2_authorize(
    request: Request,
    provider_instance: Annotated[OAuth2Provider, Depends(get_oauth2_provider_instance)],
    return_to: str | None = Query(None, description="Relative path to open after a successful login"),
    redirect_after: str | None = Query(None, description="Deprecated alias of return_to"),
):
    """Initiate OAuth2 authorization flow.

    Sets a short-lived HttpOnly nonce cookie and ties it to the stored ``state``, so the
    callback only completes in the browser that started the login. An unsafe ``return_to``
    (absolute, protocol-relative or containing a backslash) is dropped, and the callback then
    redirects to ``/ui/projects``.

    Args:
        request: FastAPI request object
        provider_instance: OAuth2 provider instance
        return_to: Optional relative path to open after login
        redirect_after: Backward-compatible alias of ``return_to``

    Returns:
        Redirect to OAuth2 provider authorization page
    """
    requested = return_to if return_to is not None else redirect_after
    safe_return_to = validate_return_to(value=requested)
    if requested and safe_return_to is None:
        logger.warning("Ignoring an unsafe return_to value on OAuth2 authorize")

    try:
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        _store_state(state=state, redirect_url=safe_return_to or "", nonce=nonce)
    except RuntimeError as exc:
        logger.warning("OAuth2 state store is full; rejecting new login attempt")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many pending login attempts. Please try again later.",
        ) from exc

    try:
        auth_url, _ = provider_instance.generate_authorization_url(state)
        logger.info("Initiating OAuth2 flow with %s", provider_instance.get_provider_name())
        response = RedirectResponse(url=auth_url)
        response.set_cookie(
            key=NONCE_COOKIE_NAME,
            value=nonce,
            max_age=_STATE_TTL_SECONDS,
            path=NONCE_COOKIE_PATH,
            httponly=True,
            samesite=COOKIE_SAMESITE,
            secure=is_secure_request(request=request, settings=get_auth_settings()),
        )
        return response

    except (HTTPException, DocpipeException):
        raise
    except Exception as e:
        logger.error("Failed to initiate OAuth2 flow: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate OAuth2 flow",
        ) from e


def _clear_nonce_cookie(*, response: FastAPIResponse, request: Request) -> None:
    """Expire the nonce cookie, which is single-use."""
    response.delete_cookie(
        key=NONCE_COOKIE_NAME,
        path=NONCE_COOKIE_PATH,
        httponly=True,
        samesite=COOKIE_SAMESITE,
        secure=is_secure_request(request=request, settings=get_auth_settings()),
    )


@router.get("/callback")
async def oauth2_callback(
    request: Request,
    provider_instance: Annotated[OAuth2Provider, Depends(get_oauth2_provider_instance)],
    code: str = Query(..., description="Authorization code"),
    state: str = Query(..., description="State parameter"),
):
    """Handle OAuth2 callback, set the session cookie and redirect into the SPA.

    The token never appears in a URL. The callback is rejected with 400, and no session
    cookie is set, when ``state`` is unknown or expired or the nonce cookie is missing or
    does not match the one tied to ``state``.

    Args:
        request: FastAPI request object
        provider_instance: OAuth2 provider instance
        code: Authorization code from OAuth2 provider
        state: State parameter for CSRF validation

    Returns:
        302 redirect to the validated same-origin ``return_to`` (default ``/ui/projects``)
    """
    try:
        stored_return_to = _consume_state(state=state, nonce=request.cookies.get(NONCE_COOKIE_NAME))
        if stored_return_to is None:
            logger.warning("Invalid, expired or browser-mismatched OAuth2 state received")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired state parameter",
            )

        token_data = await provider_instance.exchange_code_for_token(code)
        user = await provider_instance.extract_user_from_token(token_data)

        try:
            jwt_config = JWTConfig()
        except Exception as e:
            logger.error("Failed to load JWT config: %s", e)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="JWT configuration not available",
            ) from e

        jwt_token_data = {
            JWTClaims.USERNAME: user.username,
            JWTClaims.EMAIL: user.email,
            JWTClaims.FULL_NAME: user.full_name,
            JWTClaims.ROLES: [role.value for role in user.roles],
        }
        access_token = create_access_token(jwt_token_data, jwt_config)

        logger.info("OAuth2 login successful for user: %s", sanitize_for_log(user.username))

        response = RedirectResponse(url=resolve_return_to(value=stored_return_to), status_code=status.HTTP_302_FOUND)
        set_session_cookie(
            response=response,
            request=request,
            settings=get_auth_settings(),
            token=access_token,
            max_age_seconds=jwt_config.jwt_access_token_expire_minutes * 60,
        )
        _clear_nonce_cookie(response=response, request=request)
        return response

    except (HTTPException, DocpipeException):
        raise
    except Exception as e:
        logger.error("OAuth2 callback error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OAuth2 authentication failed",
        ) from e


def list_enabled_providers() -> list[AuthProvider]:
    """Return the configured OIDC providers with public fields only.

    Returns:
        One entry per enabled provider holding ``name``, ``display_name`` and ``authorize_url``.
    """
    providers: list[AuthProvider] = []

    for provider_name in ["google", "azure", "generic"]:
        try:
            config = get_oauth2_config(provider_name)
            if config.oauth2_enabled and config.oauth2_client_id:
                providers.append(
                    AuthProvider(
                        name=provider_name,
                        display_name=provider_name.title(),
                        authorize_url=f"/auth/oauth2/authorize?provider={provider_name}",
                    )
                )
        except Exception:  # nosec B112
            continue

    return providers


@router.get("/providers")
async def list_oauth2_providers():
    """List available OAuth2 providers.

    Returns:
        List of configured OAuth2 providers
    """
    return {"providers": [provider.model_dump() for provider in list_enabled_providers()]}


@router.get("/discovery/{provider}")
async def oauth2_discovery(
    provider: Annotated[str, Path(description="OAuth2 provider name")],
    config: Annotated[OAuth2Config, Depends(get_oauth2_config)],
):
    """Get OAuth2/OIDC discovery information for a provider.

    Args:
        provider: Provider name
        config: OAuth2 configuration

    Returns:
        Discovery document
    """
    if not config.oauth2_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth2 authentication is not enabled",
        )

    try:
        provider_instance = get_oauth2_provider(config)
        return await provider_instance.discover_endpoints()
    except (HTTPException, DocpipeException):
        raise
    except Exception as e:
        logger.error("Failed to fetch discovery document: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch discovery document",
        ) from e
