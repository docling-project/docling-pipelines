"""JWT token handling module."""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from jwt import PyJWTError
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

_JWT_SECRET_MIN_LENGTH = 32


class JWTClaims:
    """JWT payload claim key names."""

    USERNAME = "username"
    EMAIL = "email"
    FULL_NAME = "full_name"


class JWTConfig(BaseSettings):
    """JWT configuration settings."""

    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_secret_strength(cls, v: str) -> str:
        """Reject keys shorter than the minimum required length."""
        if not v or len(v) < _JWT_SECRET_MIN_LENGTH:
            raise ValueError(f"JWT secret key must be at least {_JWT_SECRET_MIN_LENGTH} characters long")
        return v


def create_access_token(data: dict, config: JWTConfig) -> str:
    """Generate JWT access token.

    Args:
        data: Data to encode in the token
        config: JWT configuration

    Returns:
        Encoded JWT token string
    """
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(minutes=config.jwt_access_token_expire_minutes)
    to_encode.update({"exp": expire})

    try:
        encoded_jwt = jwt.encode(to_encode, config.jwt_secret_key, algorithm=config.jwt_algorithm)
        logger.info("Created access token for user: %s", data.get(JWTClaims.USERNAME, "unknown"))
        return encoded_jwt
    except Exception as e:
        logger.error("Error creating access token: %s", e)
        raise


def verify_token(token: str, config: JWTConfig) -> dict | None:
    """Verify and decode JWT token.

    Args:
        token: JWT token string
        config: JWT configuration

    Returns:
        Decoded token payload if valid, None otherwise
    """
    try:
        # Every token issued by create_access_token carries "exp"; refuse tokens
        # without it so a correctly-signed token can never be valid forever.
        payload: dict[str, Any] = jwt.decode(
            token,
            config.jwt_secret_key,
            algorithms=[config.jwt_algorithm],
            options={"require": ["exp"]},
        )
        username: Any | None = payload.get(JWTClaims.USERNAME)
        if username is None:
            logger.warning("Token missing username claim")
            return None
        logger.debug("Token verified for user: %s", username)
        return payload
    except PyJWTError as e:
        logger.warning("JWT verification failed: %s", e)
        return None
    except Exception as e:
        logger.error("Unexpected error verifying token: %s", e)
        return None
