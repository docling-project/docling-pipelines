# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Bootstrap administrator: a break-glass local login configured through the environment.

The login is active only when both ``DOCPIPE_AUTH_BOOTSTRAP_USERNAME`` and
``DOCPIPE_AUTH_BOOTSTRAP_PASSWORD_HASH`` (a bcrypt hash) are set. It always grants the
``admin`` role, stays available when LDAP or OIDC is configured, and every successful
login is audited. The hash is verified with ``bcrypt.checkpw`` directly (``passlib`` is
incompatible with the locked bcrypt 5).
"""

import secrets

import bcrypt

from docpipe.exceptions.docpipe_exceptions import ConfigurationError
from docpipe.utils.infrastructure.audit import OUTCOME_SUCCESS, audit_event
from docpipe.utils.infrastructure.logging import get_logger

from .config import AuthSettings
from .models import User
from .ports import AuthenticatorPort, is_reserved_username
from .roles import Role

logger = get_logger(__name__)

# bcrypt only uses the first 72 bytes of a password. bcrypt 5 raises on longer input, so
# such passwords are rejected before bcrypt is called.
BCRYPT_MAX_PASSWORD_BYTES = 72

AUDIT_ACTION_BOOTSTRAP_LOGIN = "auth.bootstrap_login"


class BootstrapAdminAuthenticator(AuthenticatorPort):
    """Authenticates the single bootstrap administrator against a bcrypt hash."""

    def __init__(self, *, username: str, password_hash: str) -> None:
        """Validate the configuration and keep the credentials in memory.

        Args:
            username: Bootstrap administrator username.
            password_hash: bcrypt hash of the administrator password.

        Raises:
            ConfigurationError: If the username is empty or reserved, or the hash is not a
                valid bcrypt hash.
        """
        if not username.strip():
            raise ConfigurationError("The bootstrap administrator username must not be empty")
        if is_reserved_username(username):
            raise ConfigurationError("The bootstrap administrator username is reserved")
        hash_bytes = password_hash.encode("utf-8")
        try:
            # A malformed hash makes bcrypt raise ValueError ("Invalid salt").
            bcrypt.checkpw(b"configuration-check", hash_bytes)
        except ValueError as exc:
            raise ConfigurationError(
                "DOCPIPE_AUTH_BOOTSTRAP_PASSWORD_HASH is not a valid bcrypt hash"  # pragma: allowlist secret
            ) from exc
        self._username = username
        self._password_hash = hash_bytes

    @classmethod
    def from_settings(cls, *, settings: AuthSettings) -> "BootstrapAdminAuthenticator | None":
        """Build the authenticator from the environment-derived settings.

        Args:
            settings: Current auth settings.

        Returns:
            The authenticator when both variables are set, or ``None`` when neither is.

        Raises:
            ConfigurationError: If only one variable is set, or the values are invalid.
        """
        username = settings.bootstrap_username
        password_hash = settings.bootstrap_password_hash
        if username is None and password_hash is None:
            return None
        if username is None or password_hash is None:
            raise ConfigurationError(
                "DOCPIPE_AUTH_BOOTSTRAP_USERNAME and DOCPIPE_AUTH_BOOTSTRAP_PASSWORD_HASH "  # pragma: allowlist secret
                "must be set together"
            )
        authenticator = cls(username=username, password_hash=password_hash)
        logger.warning(
            "The bootstrap administrator login is active for user %s. It always grants the admin role and "
            "stays available when LDAP or OIDC is configured; unset the bootstrap variables when they "
            "are not needed.",
            username,
        )
        return authenticator

    def authenticate(self, *, username: str, password: str) -> User | None:
        """Verify the bootstrap credentials.

        The bcrypt check runs even when the username does not match, so the response time
        does not reveal the username. The username is compared with
        ``secrets.compare_digest``.

        Args:
            username: Username presented at login.
            password: Password presented at login.

        Returns:
            An ``admin`` user on success, ``None`` otherwise (including passwords longer
            than 72 bytes).
        """
        if not username or not password or is_reserved_username(username):
            return None
        password_bytes = password.encode("utf-8")
        if len(password_bytes) > BCRYPT_MAX_PASSWORD_BYTES:
            return None
        username_matches = secrets.compare_digest(username.encode("utf-8"), self._username.encode("utf-8"))
        password_matches = bcrypt.checkpw(password_bytes, self._password_hash)
        if not (username_matches and password_matches):
            return None
        audit_event(
            username=self._username,
            action=AUDIT_ACTION_BOOTSTRAP_LOGIN,
            target="/auth/login",
            outcome=OUTCOME_SUCCESS,
        )
        return User(username=self._username, roles=[Role.ADMIN])
