"""OAuth2 and OIDC configuration module."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


class OAuth2Config(BaseSettings):
    """OAuth2 configuration settings."""

    oauth2_enabled: bool = Field(default=False, description="Enable OAuth2 authentication")
    oauth2_provider: str = Field(default="generic", description="OAuth2 provider (google, azure, generic)")

    oauth2_client_id: str = Field(default="", description="OAuth2 client ID")
    oauth2_client_secret: str = Field(default="", description="OAuth2 client secret")
    oauth2_redirect_uri: str = Field(default="", description="OAuth2 redirect URI")

    oauth2_discovery_url: str = Field(default="", description="OIDC discovery endpoint URL")
    oauth2_authorization_endpoint: str = Field(default="", description="OAuth2 authorization endpoint")
    oauth2_token_endpoint: str = Field(default="", description="OAuth2 token endpoint")
    oauth2_userinfo_endpoint: str = Field(default="", description="OAuth2 userinfo endpoint")
    oauth2_jwks_uri: str = Field(default="", description="JWKS URI for token validation")

    oauth2_scope: str = Field(default="openid profile email", description="OAuth2 scopes")

    oidc_issuer: str = Field(default="", description="OIDC issuer URL")
    oidc_audience: str = Field(default="", description="OIDC audience (usually client_id)")

    oauth2_state_secret: str = Field(default="", description="Secret for state parameter encryption")
    oauth2_session_expire_minutes: int = Field(default=60, description="OAuth2 session expiration in minutes")

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


class GoogleOAuth2Config(OAuth2Config):
    """Google OAuth2 specific configuration."""

    oauth2_provider: str = "google"
    oauth2_discovery_url: str = "https://accounts.google.com/.well-known/openid-configuration"
    oauth2_authorization_endpoint: str = "https://accounts.google.com/o/oauth2/v2/auth"
    oauth2_token_endpoint: str = "https://oauth2.googleapis.com/token"
    oauth2_userinfo_endpoint: str = "https://openidconnect.googleapis.com/v1/userinfo"
    oauth2_jwks_uri: str = "https://www.googleapis.com/oauth2/v3/certs"
    oidc_issuer: str = "https://accounts.google.com"


class AzureADOAuth2Config(OAuth2Config):
    """Azure AD OAuth2 specific configuration."""

    oauth2_provider: str = "azure"
    azure_tenant_id: str = Field(default="common", description="Azure AD tenant ID")

    def __init__(self, **data):
        """Initialize Azure AD config with computed fields."""
        # Set computed fields before calling parent __init__
        if "azure_tenant_id" in data:
            tenant_id = data["azure_tenant_id"]
        else:
            tenant_id = "common"

        # Set all computed fields as regular fields
        data.setdefault(
            "oauth2_discovery_url",
            f"https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/openid-configuration",
        )
        data.setdefault(
            "oauth2_authorization_endpoint", f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"
        )
        data.setdefault("oauth2_token_endpoint", f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token")
        data.setdefault("oauth2_userinfo_endpoint", "https://graph.microsoft.com/oidc/userinfo")
        data.setdefault("oauth2_jwks_uri", f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys")
        data.setdefault("oidc_issuer", f"https://login.microsoftonline.com/{tenant_id}/v2.0")

        super().__init__(**data)


def get_oauth2_config(provider: str | None = None) -> OAuth2Config:
    """Get OAuth2 configuration based on provider.

    Args:
        provider: OAuth2 provider name (google, azure, generic)

    Returns:
        OAuth2Config instance for the specified provider
    """
    if provider is None:
        base_config = OAuth2Config()
        provider = base_config.oauth2_provider

    if provider == "google":
        return GoogleOAuth2Config()
    if provider == "azure":
        return AzureADOAuth2Config()
    return OAuth2Config()
