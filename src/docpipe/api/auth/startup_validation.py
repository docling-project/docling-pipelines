# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Startup validation of the authentication configuration.

When ``DOCPIPE_AUTH_ENABLED`` is true the API refuses to start unless ``JWT_SECRET_KEY`` is
set, is not a known placeholder and is long enough. This replaces the former behaviour of
silently disabling login on a JWT configuration error. When authentication is disabled no
secret is needed and the API starts normally.

Request-time behaviour (``get_jwt_config`` and ``get_session_jwt_config``) is unchanged.
"""

from pydantic import ValidationError

from docpipe.core.constants.constants import EnvironmentVariables
from docpipe.exceptions.docpipe_exceptions import ConfigurationError
from docpipe.utils.infrastructure.logging import get_logger

from .config import AuthSettings
from .jwt_handler import _JWT_SECRET_MIN_LENGTH, JWTConfig

logger = get_logger(__name__)

JWT_SECRET_VARIABLE = "JWT_SECRET_KEY"  # nosec B105  # pragma: allowlist secret
CORS_WILDCARD = "*"

# Lower-case fragments that mark a secret copied from an example file or a document.
_PLACEHOLDER_MARKERS: tuple[str, ...] = (
    "change-this",
    "change_this",
    "changeme",
    "change-me",
    "change_me",
    "your-secret",
    "your_secret",
    "your-jwt-secret",
    "your_jwt_secret",
    "secret-key-here",
    "replace-me",
    "replace_me",
    "placeholder",
    "local-dev-secret",
)

_GENERATE_HINT = 'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'


def is_placeholder_secret(*, secret: str) -> bool:
    """Return True when ``secret`` looks like a value copied from an example or a document."""
    lowered = secret.strip().lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


def _secret_error_message() -> str:
    return (
        f"{JWT_SECRET_VARIABLE} must be set to a value of at least {_JWT_SECRET_MIN_LENGTH} characters "
        f"when {EnvironmentVariables.DOCPIPE_AUTH_ENABLED} is true. {_GENERATE_HINT}"
    )


def _build_enabled_jwt_config() -> JWTConfig:
    """Build the JWT configuration for an auth-enabled deployment or raise.

    Raises:
        ConfigurationError: If the secret is unset, too short or a known placeholder, or any other
            JWT setting is invalid. The secret value is never included in the message.
    """
    try:
        config = JWTConfig()
    except ValidationError as exc:
        failing_fields = sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]})
        if "jwt_secret_key" in failing_fields:
            raise ConfigurationError(_secret_error_message()) from exc
        raise ConfigurationError(f"Invalid JWT configuration: {', '.join(failing_fields)}") from exc
    if is_placeholder_secret(secret=config.jwt_secret_key):
        raise ConfigurationError(
            f"{JWT_SECRET_VARIABLE} is a known placeholder value and must be replaced when "
            f"{EnvironmentVariables.DOCPIPE_AUTH_ENABLED} is true. {_GENERATE_HINT}"
        )
    return config


def _build_optional_jwt_config() -> JWTConfig | None:
    """Build the JWT configuration for an auth-disabled deployment, or ``None`` when unusable."""
    try:
        return JWTConfig()
    except ValidationError:
        logger.info("%s is not configured; token issuance is unavailable", JWT_SECRET_VARIABLE)
        return None


def validate_auth_startup(*, settings: AuthSettings, cors_origins: list[str]) -> JWTConfig | None:
    """Validate the authentication configuration at application startup.

    Args:
        settings: Current authentication settings.
        cors_origins: Parsed ``CORS_ORIGINS`` entries.

    Returns:
        The JWT configuration, or ``None`` when authentication is disabled and no usable
        ``JWT_SECRET_KEY`` is configured.

    Raises:
        ConfigurationError: If authentication is enabled and the JWT configuration is unusable.
    """
    if CORS_WILDCARD in cors_origins:
        logger.warning(
            "SECURITY WARNING: CORS_ORIGINS contains '*', which allows any origin. "
            "Set CORS_ORIGINS to the explicit origins of your frontend."
        )

    if not settings.enabled:
        return _build_optional_jwt_config()

    jwt_config = _build_enabled_jwt_config()
    if not settings.cookie_secure and not settings.trust_proxy_headers:
        logger.warning(
            "Authentication is enabled but neither %s nor %s is true. Behind a TLS-terminating proxy "
            "the session cookie would be issued without the Secure attribute.",
            EnvironmentVariables.DOCPIPE_AUTH_COOKIE_SECURE,
            EnvironmentVariables.DOCPIPE_TRUST_PROXY_HEADERS,
        )
    return jwt_config
