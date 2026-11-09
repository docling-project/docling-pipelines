# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""LDAP authentication module."""

from typing import Any

import ldap
from ldap.filter import escape_filter_chars
from pydantic_settings import BaseSettings, SettingsConfigDict

from docpipe.exceptions.docpipe_exceptions import ConfigurationError, ExternalServiceError
from docpipe.utils.infrastructure.logging import get_logger

from .config import get_auth_settings
from .models import User
from .ports import AuthenticatorPort, is_reserved_username
from .role_mapping import resolve_role
from .roles import Role

logger = get_logger(__name__)


class LDAPConfig(BaseSettings):
    """LDAP configuration settings."""

    ldap_server: str = ""
    ldap_base_dn: str = ""
    ldap_user_dn: str = ""
    ldap_bind_dn: str = ""
    ldap_bind_password: str = ""
    ldap_use_ssl: bool = False
    ldap_use_active_directory: bool = False
    ldap_ad_domain: str = ""
    # Attribute that lists the groups a user belongs to (Active Directory and OpenLDAP
    # with the memberof overlay use ``memberOf``).
    ldap_group_attribute: str = "memberOf"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


class LDAPAuthenticator(AuthenticatorPort):
    """LDAP authenticator class."""

    def __init__(self, config: LDAPConfig):
        """Initialize with the given LDAP configuration."""
        self.config = config
        logger.info("LDAP role mapping reads groups from the %s attribute", self._group_attribute())

    def _group_attribute(self) -> str:
        """Return the configured group attribute, falling back to ``memberOf``."""
        return self.config.ldap_group_attribute.strip() or "memberOf"

    def _resolve_roles(self, *, attrs: dict[str, Any]) -> list[Role]:
        """Map the entry's group attribute values to the user's role.

        Distinguished names are compared case-insensitively. A user with no mapped group
        receives the configured default role (``viewer`` unless overridden).

        Args:
            attrs: Attributes of the user's directory entry, with bytes values.

        Returns:
            A one-element list holding the user's role.
        """
        group_attribute = self._group_attribute()
        values: list[Any] = next((v for k, v in attrs.items() if k.lower() == group_attribute.lower()), [])
        groups = [
            value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value) for value in values
        ]
        settings = get_auth_settings()
        return [
            resolve_role(
                groups=groups,
                role_mapping=settings.role_mapping,
                default_role=settings.default_role,
                case_insensitive=True,
            )
        ]

    def authenticate(self, *, username: str, password: str) -> User | None:
        """Authenticate user against LDAP server.

        Args:
            username: Username to authenticate
            password: Password for authentication

        Returns:
            User object (with the role derived from the group attribute) if authentication
            successful, None otherwise

        Raises:
            Exception: If LDAP connection or authentication fails
        """
        # A simple bind with an empty password is an "unauthenticated bind"
        # (RFC 4513, section 5.1.2) that many servers report as successful, so
        # it must never be treated as proof of the user's identity.
        if not username or not password:
            logger.warning("Rejected LDAP authentication with empty username or password")
            return None

        if is_reserved_username(username):
            logger.warning("Rejected LDAP authentication for a reserved username")
            return None

        ldap_client = None

        try:
            ldap_client = ldap.initialize(self.config.ldap_server)
            ldap_client.set_option(ldap.OPT_REFERRALS, 0)
            ldap_client.set_option(ldap.OPT_PROTOCOL_VERSION, 3)

            if self.config.ldap_use_ssl:
                ldap_client.set_option(
                    ldap.OPT_X_TLS_REQUIRE_CERT,
                    ldap.OPT_X_TLS_NEVER,
                )
                ldap_client.start_tls_s()

            # ------------------------------------------------------------------
            # Active Directory: authenticate directly using username@domain
            # ------------------------------------------------------------------
            if self.config.ldap_use_active_directory:
                if not self.config.ldap_ad_domain:
                    raise ConfigurationError("ldap_ad_domain must be configured when using Active Directory")

                bind_dn = f"{username}@{self.config.ldap_ad_domain}"

                logger.info("Attempting AD authentication for user: %s", username)

                try:
                    ldap_client.simple_bind_s(bind_dn, password)
                except ldap.INVALID_CREDENTIALS:
                    logger.warning("Invalid credentials for user: %s", username)
                    return None

                search_filter = f"(sAMAccountName={escape_filter_chars(username)})"
                attributes = [
                    "cn",
                    "mail",
                    "sAMAccountName",
                    "userPrincipalName",
                    self._group_attribute(),
                ]

                result = ldap_client.search_s(
                    self.config.ldap_user_dn,
                    ldap.SCOPE_SUBTREE,
                    search_filter,
                    attributes,
                )

                email = ""
                full_name = ""
                entry_attrs: dict[str, Any] = {}

                if result:
                    _, entry_attrs = result[0]

                    email = entry_attrs.get("mail", [b""])[0].decode("utf-8") if "mail" in entry_attrs else ""

                    full_name = entry_attrs.get("cn", [b""])[0].decode("utf-8") if "cn" in entry_attrs else ""

                logger.info("Successfully authenticated user: %s", username)

                return User(
                    username=username,
                    email=email,
                    full_name=full_name,
                    roles=self._resolve_roles(attrs=entry_attrs),
                )

            # ------------------------------------------------------------------
            # Standard LDAP/OpenLDAP: find user DN first, then bind as user
            # ------------------------------------------------------------------

            ldap_client.simple_bind_s(
                self.config.ldap_bind_dn,
                self.config.ldap_bind_password,
            )

            search_filter = f"(uid={escape_filter_chars(username)})"
            attributes = ["cn", "mail", "uid", self._group_attribute()]

            result = ldap_client.search_s(
                self.config.ldap_user_dn,
                ldap.SCOPE_SUBTREE,
                search_filter,
                attributes,
            )

            if not result:
                logger.warning("User not found in LDAP: %s", username)
                return None

            user_dn, attrs = result[0]

            email = attrs.get("mail", [b""])[0].decode("utf-8") if "mail" in attrs else ""

            full_name = attrs.get("cn", [b""])[0].decode("utf-8") if "cn" in attrs else ""

            ldap_client.unbind_s()

            ldap_client = ldap.initialize(self.config.ldap_server)
            ldap_client.set_option(ldap.OPT_REFERRALS, 0)
            ldap_client.set_option(ldap.OPT_PROTOCOL_VERSION, 3)

            if self.config.ldap_use_ssl:
                ldap_client.set_option(
                    ldap.OPT_X_TLS_REQUIRE_CERT,
                    ldap.OPT_X_TLS_NEVER,
                )
                ldap_client.start_tls_s()

            try:
                ldap_client.simple_bind_s(user_dn, password)
            except ldap.INVALID_CREDENTIALS:
                logger.warning("Invalid credentials for user: %s", username)
                return None

            logger.info("Successfully authenticated user: %s", username)

            return User(
                username=username,
                email=email,
                full_name=full_name,
                roles=self._resolve_roles(attrs=attrs),
            )

        except ldap.SERVER_DOWN:
            logger.error("LDAP server is down: %s", self.config.ldap_server)
            raise ExternalServiceError("LDAP server is unavailable") from None

        except ldap.INVALID_DN_SYNTAX as e:
            logger.error("LDAP DN syntax error for user %s: %s", username, e)
            raise ConfigurationError("LDAP configuration error: invalid bind DN format") from e

        except (ConfigurationError, ExternalServiceError):
            raise

        except Exception as e:
            logger.error("LDAP authentication error for user %s: %s", username, e)
            raise ExternalServiceError(f"LDAP authentication error: {e!s}") from e

        finally:
            if ldap_client:
                try:
                    ldap_client.unbind_s()
                except Exception as e:
                    logger.error("Failed to unbind LDAP connection: %s", e)

    def verify_connection(self) -> bool:
        """Verify LDAP server connection.

        Returns:
            True if connection successful, False otherwise
        """
        ldap_client = None
        try:
            ldap_client = ldap.initialize(self.config.ldap_server)
            ldap_client.set_option(ldap.OPT_REFERRALS, 0)
            ldap_client.set_option(ldap.OPT_PROTOCOL_VERSION, 3)

            if self.config.ldap_use_ssl:
                ldap_client.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER)
                ldap_client.start_tls_s()

            ldap_client.simple_bind_s(self.config.ldap_bind_dn, self.config.ldap_bind_password)
            logger.info("LDAP connection verified successfully")
            return True

        except Exception as e:
            logger.error("LDAP connection verification failed: %s", e)
            return False
        finally:
            if ldap_client:
                try:
                    ldap_client.unbind_s()
                except Exception as e:
                    logger.error("Error unbinding LDAP connection: %s", e)
