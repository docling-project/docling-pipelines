# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Authentication and authorization settings, read from the environment on every call.

The settings are deliberately not cached: ``DOCPIPE_AUTH_ENABLED`` is read per request
so tests can change it with ``monkeypatch``. Operators must still set it before the
process starts (see the ``auth-api`` spec, "Toggle is fixed per deployment").
"""

import os
from dataclasses import dataclass, field

from docpipe.core.constants.constants import EnvironmentVariables
from docpipe.utils.infrastructure.logging import get_logger

from .roles import Role

logger = get_logger(__name__)

DEFAULT_COOKIE_NAME = "docpipe_access_token"
DEFAULT_ROLE = Role.VIEWER

# Separator for group identifiers in the DOCPIPE_AUTH_ROLE_MAPPING_* variables. LDAP
# distinguished names contain commas, so a comma cannot be used.
ROLE_MAPPING_SEPARATOR = ";"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})

_ROLE_MAPPING_VARIABLES: dict[Role, str] = {
    Role.VIEWER: EnvironmentVariables.DOCPIPE_AUTH_ROLE_MAPPING_VIEWER,
    Role.EDITOR: EnvironmentVariables.DOCPIPE_AUTH_ROLE_MAPPING_EDITOR,
    Role.ADMIN: EnvironmentVariables.DOCPIPE_AUTH_ROLE_MAPPING_ADMIN,
}


def _env_bool(*, name: str, default: bool) -> bool:
    """Read a boolean environment variable (``1``, ``true``, ``yes``, ``on`` are true)."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in _TRUE_VALUES


def _env_str(*, name: str) -> str | None:
    """Read a string environment variable, returning ``None`` when unset or blank."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip()


def _parse_group_list(raw: str | None) -> tuple[str, ...]:
    """Split a semicolon-separated group list, trimming entries and dropping empty ones."""
    if not raw:
        return ()
    return tuple(item.strip() for item in raw.split(ROLE_MAPPING_SEPARATOR) if item.strip())


def _read_default_role() -> Role:
    """Read ``DOCPIPE_AUTH_DEFAULT_ROLE``, falling back to ``viewer`` (fail closed)."""
    raw = _env_str(name=EnvironmentVariables.DOCPIPE_AUTH_DEFAULT_ROLE)
    if raw is None:
        return DEFAULT_ROLE
    try:
        return Role(raw.lower())
    except ValueError:
        logger.warning(
            "Invalid %s value; falling back to %s",
            EnvironmentVariables.DOCPIPE_AUTH_DEFAULT_ROLE,
            DEFAULT_ROLE.value,
        )
        return DEFAULT_ROLE


@dataclass(frozen=True)
class AuthSettings:
    """Immutable snapshot of the authentication settings at the time of the call."""

    enabled: bool = False
    default_role: Role = DEFAULT_ROLE
    # Role -> group identifiers. Matching rules (LDAP DN case-insensitivity, exact OIDC
    # strings) belong to the authenticators, not to this settings object.
    # The YAML source (auth.role_mapping in docling-pipelines-config.yaml) is not read yet.
    role_mapping: dict[Role, tuple[str, ...]] = field(default_factory=dict)
    cookie_name: str = DEFAULT_COOKIE_NAME
    cookie_secure: bool = False
    trust_proxy_headers: bool = False
    bootstrap_username: str | None = None
    bootstrap_password_hash: str | None = None

    @classmethod
    def from_env(cls) -> "AuthSettings":
        """Build settings from the current environment."""
        return cls(
            # Default is false in this phase; it flips to true in the final rollout phase.
            enabled=_env_bool(name=EnvironmentVariables.DOCPIPE_AUTH_ENABLED, default=False),
            default_role=_read_default_role(),
            role_mapping={
                role: _parse_group_list(os.environ.get(variable)) for role, variable in _ROLE_MAPPING_VARIABLES.items()
            },
            cookie_name=_env_str(name=EnvironmentVariables.DOCPIPE_AUTH_COOKIE_NAME) or DEFAULT_COOKIE_NAME,
            cookie_secure=_env_bool(name=EnvironmentVariables.DOCPIPE_AUTH_COOKIE_SECURE, default=False),
            trust_proxy_headers=_env_bool(name=EnvironmentVariables.DOCPIPE_TRUST_PROXY_HEADERS, default=False),
            bootstrap_username=_env_str(name=EnvironmentVariables.DOCPIPE_AUTH_BOOTSTRAP_USERNAME),
            bootstrap_password_hash=_env_str(name=EnvironmentVariables.DOCPIPE_AUTH_BOOTSTRAP_PASSWORD_HASH),
        )


def get_auth_settings() -> AuthSettings:
    """Return the current settings (re-read from the environment on every call).

    Usable as a FastAPI dependency.
    """
    return AuthSettings.from_env()
