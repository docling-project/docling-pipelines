# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""FastAPI dependencies for authentication."""

from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2AuthorizationCodeBearer

from docpipe.utils.infrastructure.logging import get_logger

from .config import get_auth_settings
from .jwt_handler import JWTClaims, JWTConfig, verify_token
from .models import User
from .roles import Role, parse_roles

logger = get_logger(__name__)

# Reserved username of the principal returned when authentication is disabled. Contains
# characters that no LDAP, OIDC or bootstrap login produces, and authenticators reject it.
LOCAL_PRINCIPAL_USERNAME = "<local-principal>"

AUTH_SOURCE_BEARER = "bearer"
AUTH_SOURCE_COOKIE = "cookie"
AUTH_SOURCE_DISABLED = "disabled"

# Cookie-authenticated requests with these methods must carry a non-empty CSRF header.
# A cross-origin page cannot add a custom header without a CORS preflight that the
# allowed-origin list refuses. Bearer requests are exempt.
CSRF_HEADER = "X-Requested-With"
CSRF_PROTECTED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

security = HTTPBearer(auto_error=False)

oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl="/auth/oauth2/authorize",
    tokenUrl="/auth/oauth2/callback",
    auto_error=False,
)


def get_jwt_config() -> JWTConfig:
    """Get JWT configuration.

    Returns:
        JWT configuration instance

    Raises:
        HTTPException: 503 if JWT configuration is missing or invalid.
    """
    try:
        return JWTConfig()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service not configured",
        ) from exc


def get_session_jwt_config() -> JWTConfig | None:
    """Resolve the JWT configuration for a session check.

    Returns ``None`` when auth is disabled, so a deployment with auth off needs no
    ``JWT_SECRET_KEY``.

    Returns:
        JWT configuration, or ``None`` when authentication is disabled.

    Raises:
        HTTPException: 503 if auth is enabled and the JWT configuration is invalid.
    """
    if not get_auth_settings().enabled:
        return None
    return get_jwt_config()


def _unauthorized(*, detail: str) -> HTTPException:
    """Build a 401 response carrying the ``WWW-Authenticate: Bearer`` challenge."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _enforce_csrf_header(*, request: Request) -> None:
    """Reject an unsafe cookie-authenticated request that lacks the CSRF header.

    Args:
        request: Current request, already known to be cookie-authenticated.

    Raises:
        HTTPException: 403 if the method is unsafe and ``X-Requested-With`` is missing or empty.
    """
    if request.method not in CSRF_PROTECTED_METHODS:
        return
    if request.headers.get(CSRF_HEADER, "").strip():
        return
    logger.warning("Rejected cookie-authenticated %s request without the %s header", request.method, CSRF_HEADER)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Missing required header: {CSRF_HEADER}",
    )


def get_current_user(
    *,
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    jwt_config: Annotated[JWTConfig | None, Depends(get_session_jwt_config)],
) -> User:
    """FastAPI dependency to extract and validate the current user from the session.

    The Bearer header is read first and wins over the session cookie. The credential
    source is recorded in ``request.state.auth_source`` as ``bearer``, ``cookie`` or
    ``disabled``. Cookie-authenticated ``POST``, ``PUT``, ``PATCH`` and ``DELETE``
    requests must carry a non-empty ``X-Requested-With`` header; Bearer requests are
    exempt. When authentication is disabled, the reserved local principal is returned
    without reading any credential.

    Args:
        request: Current request
        credentials: HTTP authorization credentials, if a Bearer header is present
        jwt_config: JWT configuration, ``None`` when authentication is disabled

    Returns:
        User object from the token payload, or the local principal when auth is disabled

    Raises:
        HTTPException: 401 if no valid credential is presented, 403 if the CSRF header is
            missing on a cookie-authenticated mutation
    """
    settings = get_auth_settings()
    if not settings.enabled:
        request.state.auth_source = AUTH_SOURCE_DISABLED
        return User(username=LOCAL_PRINCIPAL_USERNAME, roles=[Role.ADMIN])

    if jwt_config is None:
        # Auth was switched on between dependency resolution and this call.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service not configured",
        )

    if credentials is not None:
        token = credentials.credentials
        auth_source = AUTH_SOURCE_BEARER
    else:
        cookie_token = request.cookies.get(settings.cookie_name)
        if not cookie_token:
            logger.debug("No authentication credentials provided")
            raise _unauthorized(detail="Not authenticated")
        token = cookie_token
        auth_source = AUTH_SOURCE_COOKIE

    payload: dict[Any, Any] | None = verify_token(token, jwt_config)

    if payload is None:
        logger.warning("Invalid authentication token provided")
        raise _unauthorized(detail="Invalid authentication credentials")

    username = payload.get(JWTClaims.USERNAME)
    if username is None:
        logger.warning("Token missing username claim")
        raise _unauthorized(detail="Invalid token payload")

    if username == LOCAL_PRINCIPAL_USERNAME:
        logger.warning("Token carries the reserved local principal username")
        raise _unauthorized(detail="Invalid authentication credentials")

    request.state.auth_source = auth_source
    if auth_source == AUTH_SOURCE_COOKIE:
        _enforce_csrf_header(request=request)

    user = User(
        username=username,
        email=payload.get(JWTClaims.EMAIL, ""),
        full_name=payload.get(JWTClaims.FULL_NAME, ""),
        roles=parse_roles(payload.get(JWTClaims.ROLES)),
    )

    logger.debug("Authenticated user: %s", username)
    return user


def require_session(user: Annotated[User, Depends(get_current_user)]) -> User:
    """Router-level dependency that requires a valid session.

    Delegates to ``get_current_user`` through ``Depends`` so dependency overrides of
    ``get_current_user`` apply to every route that carries this dependency.

    Args:
        user: The authenticated user, or the local principal when auth is disabled.

    Returns:
        The authenticated user.
    """
    return user


def get_current_user_oauth2(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    jwt_config: Annotated[JWTConfig, Depends(get_jwt_config)],
) -> User | None:
    """FastAPI dependency to extract user from OAuth2 token.

    Args:
        token: OAuth2 token from authorization header
        jwt_config: JWT configuration

    Returns:
        User object if token is valid, None otherwise
    """
    if not token:
        return None

    payload: dict[Any, Any] | None = verify_token(token, jwt_config)

    if payload is None:
        return None

    username = payload.get(JWTClaims.USERNAME)
    if username is None:
        return None

    return User(
        username=username,
        email=payload.get(JWTClaims.EMAIL, ""),
        full_name=payload.get(JWTClaims.FULL_NAME, ""),
    )


def get_current_user_flexible(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    oauth2_token: Annotated[str | None, Depends(oauth2_scheme)],
    jwt_config: Annotated[JWTConfig, Depends(get_jwt_config)],
) -> User:
    """FastAPI dependency supporting both Bearer token and OAuth2.

    Args:
        credentials: HTTP authorization credentials (Bearer token)
        oauth2_token: OAuth2 token
        jwt_config: JWT configuration

    Returns:
        User object from token payload

    Raises:
        HTTPException: If no valid token provided
    """
    if credentials:
        token = credentials.credentials
        payload: dict[Any, Any] | None = verify_token(token, jwt_config)

        if payload is not None:
            username = payload.get(JWTClaims.USERNAME)
            if username is not None:
                return User(
                    username=username,
                    email=payload.get(JWTClaims.EMAIL, ""),
                    full_name=payload.get(JWTClaims.FULL_NAME, ""),
                )

    if oauth2_token:
        payload = verify_token(oauth2_token, jwt_config)

        if payload is not None:
            username = payload.get(JWTClaims.USERNAME)
            if username is not None:
                return User(
                    username=username,
                    email=payload.get(JWTClaims.EMAIL, ""),
                    full_name=payload.get(JWTClaims.FULL_NAME, ""),
                )

    logger.warning("No valid authentication token provided")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
