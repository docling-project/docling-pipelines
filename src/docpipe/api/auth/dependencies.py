"""FastAPI dependencies for authentication."""

from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2AuthorizationCodeBearer

from docpipe.utils.infrastructure.logging import get_logger

from .jwt_handler import JWTClaims, JWTConfig, verify_token
from .models import User

logger = get_logger(__name__)

security = HTTPBearer()

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


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    jwt_config: Annotated[JWTConfig, Depends(get_jwt_config)],
) -> User:
    """FastAPI dependency to extract and validate current user from JWT.

    Args:
        credentials: HTTP authorization credentials
        jwt_config: JWT configuration

    Returns:
        User object from token payload

    Raises:
        HTTPException: If token is invalid or missing required claims
    """
    token = credentials.credentials
    payload: dict[Any, Any] | None = verify_token(token, jwt_config)

    if payload is None:
        logger.warning("Invalid authentication token provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username = payload.get(JWTClaims.USERNAME)
    if username is None:
        logger.warning("Token missing username claim")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = User(
        username=username,
        email=payload.get(JWTClaims.EMAIL, ""),
        full_name=payload.get(JWTClaims.FULL_NAME, ""),
    )

    logger.debug("Authenticated user: %s", username)
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
