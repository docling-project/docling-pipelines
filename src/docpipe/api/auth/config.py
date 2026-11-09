# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Authentication and authorization settings, read from the environment on every call.

The settings are deliberately not cached: ``DOCPIPE_AUTH_ENABLED`` is read per request
so tests can change it with ``monkeypatch``. Operators must still set it before the
process starts (see the ``auth-api`` spec, "Toggle is fixed per deployment").
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from docpipe.core.constants.constants import DocpipeConfigKeys, EnvironmentVariables, _find_project_root
from docpipe.utils.infrastructure.logging import get_logger

from .roles import Role

logger = get_logger(__name__)

DEFAULT_COOKIE_NAME = "docpipe_access_token"
DEFAULT_ROLE = Role.VIEWER

# Separator for group identifiers in the DOCPIPE_AUTH_ROLE_MAPPING_* variables. LDAP
# distinguished names contain commas, so a comma cannot be used.
ROLE_MAPPING_SEPARATOR = ";"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})

_DEFAULT_CONFIG_PATH = _find_project_root() / "docling-pipelines-config.yaml"

# (path, mtime_ns, size) -> parsed ``auth.role_mapping`` section. Keyed on the file
# modification time so the per-request settings read does not re-parse an unchanged file.
_yaml_mapping_cache: dict[tuple[str, int, int], dict[Role, tuple[str, ...]]] = {}

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


def _coerce_group_list(raw: Any) -> tuple[str, ...]:
    """Coerce a YAML role-mapping value (a list, or a semicolon-separated string) to groups."""
    if isinstance(raw, str):
        return _parse_group_list(raw)
    if isinstance(raw, list | tuple):
        return tuple(item.strip() for item in raw if isinstance(item, str) and item.strip())
    return ()


def _read_yaml_role_mapping() -> dict[Role, tuple[str, ...]]:
    """Read the optional ``auth.role_mapping`` section of ``docling-pipelines-config.yaml``.

    The file is found through ``DOCPIPE_CONFIG_PATH`` and falls back to the project default.
    A missing or unreadable file, or a missing section, yields an empty mapping.

    Returns:
        Group identifiers per role, containing only the roles the file configures.
    """
    config_path = Path(os.getenv(EnvironmentVariables.DOCPIPE_CONFIG_PATH, str(_DEFAULT_CONFIG_PATH)))
    try:
        file_stat = config_path.stat()
        cache_key = (str(config_path), file_stat.st_mtime_ns, file_stat.st_size)
    except OSError:
        return {}
    cached = _yaml_mapping_cache.get(cache_key)
    if cached is not None:
        return cached

    mapping: dict[Role, tuple[str, ...]] = {}
    try:
        with config_path.open(encoding="utf-8") as config_file:
            loaded = yaml.safe_load(config_file) or {}
    except (OSError, yaml.YAMLError) as error:
        logger.warning("Could not read the auth role mapping from %s: %s", config_path, error)
        loaded = {}
    auth_section = loaded.get(DocpipeConfigKeys.AUTH) if isinstance(loaded, dict) else None
    role_section = auth_section.get(DocpipeConfigKeys.ROLE_MAPPING) if isinstance(auth_section, dict) else None
    if isinstance(role_section, dict):
        for role in Role:
            if role.value in role_section:
                mapping[role] = _coerce_group_list(role_section[role.value])
    _yaml_mapping_cache.clear()
    _yaml_mapping_cache[cache_key] = mapping
    return mapping


def _read_role_mapping() -> dict[Role, tuple[str, ...]]:
    """Build the role mapping from the YAML file, with ``DOCPIPE_AUTH_ROLE_MAPPING_*`` winning per role."""
    yaml_mapping = _read_yaml_role_mapping()
    mapping: dict[Role, tuple[str, ...]] = {}
    for role, variable in _ROLE_MAPPING_VARIABLES.items():
        env_groups = _parse_group_list(os.environ.get(variable))
        mapping[role] = env_groups if env_groups else yaml_mapping.get(role, ())
    return mapping


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
    # Sources: ``auth.role_mapping`` in docling-pipelines-config.yaml, overridden per role by
    # the DOCPIPE_AUTH_ROLE_MAPPING_* variables.
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
            role_mapping=_read_role_mapping(),
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
