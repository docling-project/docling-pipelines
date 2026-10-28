"""OAuth2 provider implementation with OIDC support."""

import secrets
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWTError

from docpipe.exceptions.docpipe_exceptions import ConfigurationError, DocpipeException, ExternalServiceError
from docpipe.utils.infrastructure.logging import get_logger

from .models import User
from .oauth2_config import OAuth2Config

logger = get_logger(__name__)


class OAuth2Provider(ABC):
    """Base OAuth2 provider class."""

    def __init__(self, config: OAuth2Config):
        """Initialize with the given OAuth2 configuration."""
        self.config = config
        self._discovery_cache: dict[str, Any] | None = None
        self._discovery_cache_time: datetime | None = None
        self._discovery_cache_ttl: timedelta = timedelta(hours=24)
        self._jwks_cache: dict[str, Any] | None = None
        self._jwks_cache_time: datetime | None = None
        self._jwks_cache_ttl: timedelta = timedelta(hours=1)

    @abstractmethod
    def get_provider_name(self) -> str:
        """Get provider name.

        Returns:
            Provider name string
        """
        ...

    async def discover_endpoints(self) -> dict[str, Any]:
        """Discover OAuth2/OIDC endpoints via discovery document.

        Returns:
            Dictionary containing discovered endpoints

        Raises:
            Exception: If discovery fails
        """
        now = datetime.now(UTC)
        if (
            self._discovery_cache is not None
            and self._discovery_cache_time is not None
            and now - self._discovery_cache_time < self._discovery_cache_ttl
        ):
            return self._discovery_cache

        if not self.config.oauth2_discovery_url:
            logger.warning("No discovery URL configured for %s", self.get_provider_name())
            self._discovery_cache = {}
            self._discovery_cache_time = now
            return self._discovery_cache

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.config.oauth2_discovery_url, timeout=10.0)
                response.raise_for_status()
                self._discovery_cache = response.json()
                self._discovery_cache_time = datetime.now(UTC)
                logger.info("Successfully discovered endpoints for %s", self.get_provider_name())
                return self._discovery_cache
        except Exception as e:
            logger.error("Failed to discover endpoints for %s: %s", self.get_provider_name(), e)
            raise ExternalServiceError(f"OIDC discovery failed: {e!s}") from e

    async def get_jwks(self) -> dict[str, Any]:
        """Fetch JWKS (JSON Web Key Set) for token validation.

        Returns:
            JWKS dictionary

        Raises:
            Exception: If JWKS fetch fails
        """
        now = datetime.now(UTC)
        if (
            self._jwks_cache is not None
            and self._jwks_cache_time is not None
            and now - self._jwks_cache_time < self._jwks_cache_ttl
        ):
            return self._jwks_cache

        jwks_uri = self.config.oauth2_jwks_uri
        if not jwks_uri:
            discovery = await self.discover_endpoints()
            jwks_uri = discovery.get("jwks_uri", "")

        if not jwks_uri:
            raise ConfigurationError("JWKS URI not configured or discovered")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(jwks_uri, timeout=10.0)
                response.raise_for_status()
                self._jwks_cache = response.json()
                self._jwks_cache_time = datetime.now(UTC)
                logger.info("Successfully fetched JWKS for %s", self.get_provider_name())
                return self._jwks_cache
        except ExternalServiceError:
            raise
        except Exception as e:
            logger.error("Failed to fetch JWKS for %s: %s", self.get_provider_name(), e)
            raise ExternalServiceError(f"JWKS fetch failed: {e!s}") from e

    def generate_authorization_url(self, state: str | None = None) -> tuple[str, str]:
        """Generate OAuth2 authorization URL.

        Args:
            state: Optional state parameter for CSRF protection

        Returns:
            Tuple of (authorization_url, state)
        """
        if not state:
            state = secrets.token_urlsafe(32)

        auth_endpoint = self.config.oauth2_authorization_endpoint

        params = {
            "client_id": self.config.oauth2_client_id,
            "redirect_uri": self.config.oauth2_redirect_uri,
            "response_type": "code",
            "scope": self.config.oauth2_scope,
            "state": state,
        }

        authorization_url = f"{auth_endpoint}?{urlencode(params)}"
        logger.debug("Generated authorization URL for %s", self.get_provider_name())
        return authorization_url, state

    async def exchange_code_for_token(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for access token.

        Args:
            code: Authorization code from OAuth2 callback

        Returns:
            Token response dictionary

        Raises:
            Exception: If token exchange fails
        """
        token_endpoint = self.config.oauth2_token_endpoint

        data = {
            "client_id": self.config.oauth2_client_id,
            "client_secret": self.config.oauth2_client_secret,
            "code": code,
            "redirect_uri": self.config.oauth2_redirect_uri,
            "grant_type": "authorization_code",
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(token_endpoint, data=data, timeout=10.0)
                response.raise_for_status()
                token_data = response.json()
                logger.info("Successfully exchanged code for token with %s", self.get_provider_name())
                return token_data
        except Exception as e:
            logger.error("Failed to exchange code for token with %s: %s", self.get_provider_name(), e)
            raise ExternalServiceError(f"Token exchange failed: {e!s}") from e

    async def validate_id_token(self, id_token: str) -> dict[str, Any]:
        """Validate OIDC ID token.

        Args:
            id_token: ID token to validate

        Returns:
            Decoded token payload

        Raises:
            Exception: If token validation fails
        """
        try:
            jwks = await self.get_jwks()

            unverified_header = jwt.get_unverified_header(id_token)
            kid = unverified_header.get("kid")

            key = None
            for jwk in jwks.get("keys", []):
                if jwk.get("kid") == kid:
                    key = jwk
                    break

            if not key:
                raise ConfigurationError(f"No matching key found for kid: {kid}")

            payload = jwt.decode(
                id_token,
                jwt.PyJWK(key).key,
                algorithms=["RS256"],
                audience=self.config.oidc_audience or self.config.oauth2_client_id,
                issuer=self.config.oidc_issuer,
            )

            logger.info("Successfully validated ID token for %s", self.get_provider_name())
            return payload

        except PyJWTError as e:
            logger.error("JWT validation failed for %s: %s", self.get_provider_name(), e)
            raise ExternalServiceError(f"ID token validation failed: {e!s}") from e
        except DocpipeException:
            raise
        except Exception as e:
            logger.error("Token validation error for %s: %s", self.get_provider_name(), e)
            raise ExternalServiceError(f"Token validation failed: {e!s}") from e

    async def get_user_info(self, access_token: str) -> dict[str, Any]:
        """Fetch user information from userinfo endpoint.

        Args:
            access_token: OAuth2 access token

        Returns:
            User information dictionary

        Raises:
            Exception: If userinfo fetch fails
        """
        userinfo_endpoint = self.config.oauth2_userinfo_endpoint

        if not userinfo_endpoint:
            discovery = await self.discover_endpoints()
            userinfo_endpoint = discovery.get("userinfo_endpoint", "")

        if not userinfo_endpoint:
            raise ConfigurationError("Userinfo endpoint not configured or discovered")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    userinfo_endpoint,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=10.0,
                )
                response.raise_for_status()
                userinfo = response.json()
                logger.info("Successfully fetched user info from %s", self.get_provider_name())
                return userinfo
        except ExternalServiceError:
            raise
        except Exception as e:
            logger.error("Failed to fetch user info from %s: %s", self.get_provider_name(), e)
            raise ExternalServiceError(f"Userinfo fetch failed: {e!s}") from e

    @abstractmethod
    async def extract_user_from_token(self, token_data: dict[str, Any]) -> User:
        """Extract user information from token data.

        Args:
            token_data: Token response data

        Returns:
            User object
        """
        ...


class GoogleOAuth2Provider(OAuth2Provider):
    """Google OAuth2 provider implementation."""

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "google"

    async def extract_user_from_token(self, token_data: dict[str, Any]) -> User:
        """Extract user from Google token data."""
        id_token = token_data.get("id_token")
        if not id_token:
            raise ExternalServiceError("No ID token in response")

        payload = await self.validate_id_token(id_token)

        return User(
            username=payload.get("email", ""),
            email=payload.get("email", ""),
            full_name=payload.get("name", ""),
        )


class AzureADOAuth2Provider(OAuth2Provider):
    """Azure AD OAuth2 provider implementation."""

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "azure"

    async def extract_user_from_token(self, token_data: dict[str, Any]) -> User:
        """Extract user from Azure AD token data."""
        id_token = token_data.get("id_token")
        if not id_token:
            raise ExternalServiceError("No ID token in response")

        payload = await self.validate_id_token(id_token)

        return User(
            username=payload.get("preferred_username", payload.get("email", "")),
            email=payload.get("email", payload.get("preferred_username", "")),
            full_name=payload.get("name", ""),
        )


class GenericOIDCProvider(OAuth2Provider):
    """Generic OIDC provider implementation."""

    def get_provider_name(self) -> str:
        """Get provider name."""
        return "generic"

    async def extract_user_from_token(self, token_data: dict[str, Any]) -> User:
        """Extract user from generic OIDC token data."""
        id_token = token_data.get("id_token")
        access_token = token_data.get("access_token")

        if id_token:
            payload = await self.validate_id_token(id_token)
        elif access_token:
            payload = await self.get_user_info(access_token)
        else:
            raise ExternalServiceError("No ID token or access token in response")

        username = payload.get("preferred_username") or payload.get("email") or payload.get("sub") or ""
        email = payload.get("email", "")
        full_name = payload.get("name", "")

        return User(
            username=username,
            email=email,
            full_name=full_name,
        )


def get_oauth2_provider(config: OAuth2Config) -> OAuth2Provider:
    """Get OAuth2 provider instance based on configuration.

    Args:
        config: OAuth2 configuration

    Returns:
        OAuth2Provider instance
    """
    provider_name = config.oauth2_provider.lower()

    if provider_name == "google":
        return GoogleOAuth2Provider(config)
    if provider_name == "azure":
        return AzureADOAuth2Provider(config)
    return GenericOIDCProvider(config)
