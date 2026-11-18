"""OAuth2 authentication routes."""

import secrets
import threading
import time
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.responses import RedirectResponse

from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.utils.infrastructure.logging import get_logger

from .jwt_handler import JWTClaims, JWTConfig, create_access_token
from .models import TokenResponse
from .oauth2_config import OAuth2Config, get_oauth2_config
from .oauth2_provider import OAuth2Provider, get_oauth2_provider

logger = get_logger(__name__)

router = APIRouter(prefix="/auth/oauth2", tags=["oauth2"])

# In-process TTL state store for OAuth2 CSRF tokens.
# Each entry: state_key -> (redirect_url, expiry_monotonic).
# Not suitable for multi-worker/multi-pod deployments — replace with a
# shared expiring store (e.g. Redis) for horizontally-scaled production.
_STATE_TTL_SECONDS = 600  # 10 minutes
_MAX_STATE_ENTRIES = 10_000
_state_store: dict[str, tuple[str, float]] = {}
_state_lock = threading.Lock()


def _is_same_origin(url: str) -> bool:
    """Return True only if url is a relative path (no scheme or host)."""
    if not url:
        return True
    parsed = urlparse(url)
    return parsed.scheme == "" and parsed.netloc == ""


def _store_state(*, state: str, redirect_url: str) -> None:
    """Record state token with TTL. Raises RuntimeError when the store is at capacity."""
    now = time.monotonic()
    expiry = now + _STATE_TTL_SECONDS
    with _state_lock:
        expired = [k for k, (_, exp) in _state_store.items() if now > exp]
        for k in expired:
            del _state_store[k]
        if len(_state_store) >= _MAX_STATE_ENTRIES:
            raise RuntimeError("OAuth2 state store is full")
        _state_store[state] = (redirect_url, expiry)


def _consume_state(*, state: str) -> str | None:
    """Remove and return the redirect URL for a valid, unexpired state token, or None."""
    with _state_lock:
        entry = _state_store.pop(state, None)
    if entry is None:
        return None
    redirect_url, expiry = entry
    if time.monotonic() > expiry:
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


def _require_same_origin_redirect(
    redirect_after: str | None = Query(None, description="URL to redirect after successful login"),
) -> str | None:
    """Dependency that validates redirect_after before any other dependencies run.

    Raises HTTP 400 if the value contains a scheme or netloc (open-redirect guard).
    """
    if redirect_after and not _is_same_origin(redirect_after):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="redirect_after must be a relative URL (no scheme or host)",
        )
    return redirect_after


@router.get("/authorize")
async def oauth2_authorize(
    redirect_after: Annotated[str | None, Depends(_require_same_origin_redirect)],
    provider_instance: Annotated[OAuth2Provider, Depends(get_oauth2_provider_instance)],
):
    """Initiate OAuth2 authorization flow.

    Args:
        provider_instance: OAuth2 provider instance
        redirect_after: Optional URL to redirect after login (validated by dependency)

    Returns:
        Redirect to OAuth2 provider authorization page
    """
    try:
        state = secrets.token_urlsafe(32)
        _store_state(state=state, redirect_url=redirect_after or "")
    except RuntimeError as exc:
        logger.warning("OAuth2 state store is full; rejecting new login attempt")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many pending login attempts. Please try again later.",
        ) from exc

    try:
        auth_url, _ = provider_instance.generate_authorization_url(state)
        logger.info("Initiating OAuth2 flow with %s", provider_instance.get_provider_name())
        return RedirectResponse(url=auth_url)

    except (HTTPException, DocpipeException):
        raise
    except Exception as e:
        logger.error("Failed to initiate OAuth2 flow: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate OAuth2 flow",
        ) from e


@router.get("/callback")
async def oauth2_callback(
    request: Request,
    provider_instance: Annotated[OAuth2Provider, Depends(get_oauth2_provider_instance)],
    code: str = Query(..., description="Authorization code"),
    state: str = Query(..., description="State parameter"),
):
    """Handle OAuth2 callback and exchange code for token.

    Args:
        request: FastAPI request object
        provider_instance: OAuth2 provider instance
        code: Authorization code from OAuth2 provider
        state: State parameter for CSRF validation

    Returns:
        Redirect with access token or token response
    """
    try:
        redirect_after = _consume_state(state=state)
        if redirect_after is None:
            logger.warning("Invalid or expired OAuth2 state parameter received")
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
        }
        access_token = create_access_token(jwt_token_data, jwt_config)

        logger.info("OAuth2 login successful for user: %s", user.username)

        if redirect_after:
            # Fragment keeps the token out of server logs and the Referer header.
            redirect_url = f"{redirect_after}#access_token={access_token}"
            return RedirectResponse(url=redirect_url)

        return TokenResponse(access_token=access_token)

    except (HTTPException, DocpipeException):
        raise
    except Exception as e:
        logger.error("OAuth2 callback error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OAuth2 authentication failed",
        ) from e


@router.get("/providers")
async def list_oauth2_providers():
    """List available OAuth2 providers.

    Returns:
        List of configured OAuth2 providers
    """
    providers = []

    for provider_name in ["google", "azure", "generic"]:
        try:
            config = get_oauth2_config(provider_name)
            if config.oauth2_enabled and config.oauth2_client_id:
                providers.append(
                    {
                        "name": provider_name,
                        "display_name": provider_name.title(),
                        "authorize_url": f"/auth/oauth2/authorize?provider={provider_name}",
                    }
                )
        except Exception:  # nosec B112
            continue

    return {"providers": providers}


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
