"""Unit tests for OAuth2 provider."""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qsl

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from docpipe.api.auth.models import User
from docpipe.api.auth.oauth2_config import (
    AzureADOAuth2Config,
    GoogleOAuth2Config,
    OAuth2Config,
)
from docpipe.api.auth.oauth2_provider import (
    AzureADOAuth2Provider,
    GenericOIDCProvider,
    GoogleOAuth2Provider,
    get_oauth2_provider,
)
from docpipe.exceptions.docpipe_exceptions import ConfigurationError, ExternalServiceError


def _raise(exc: Exception):
    """Build an httpx.MockTransport handler that raises ``exc`` (network-level failure)."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return handler


@pytest.fixture
def oauth2_config():
    """Create OAuth2 configuration for testing."""
    return OAuth2Config(
        oauth2_enabled=True,
        oauth2_provider="generic",
        oauth2_client_id="test-client-id",
        oauth2_client_secret="test-secret",
        oauth2_redirect_uri="http://localhost:8000/callback",
        oauth2_authorization_endpoint="https://provider.com/authorize",
        oauth2_token_endpoint="https://provider.com/token",
        oauth2_userinfo_endpoint="https://provider.com/userinfo",
        oauth2_jwks_uri="https://provider.com/jwks",
        oidc_issuer="https://provider.com",
        oidc_audience="test-client-id",
    )


@pytest.fixture
def google_config():
    """Create Google OAuth2 configuration for testing."""
    return GoogleOAuth2Config(
        oauth2_enabled=True,
        oauth2_client_id="google-client-id",
        oauth2_client_secret="google-secret",
        oauth2_redirect_uri="http://localhost:8000/callback",
    )


@pytest.fixture
def azure_config():
    """Create Azure AD OAuth2 configuration for testing."""
    return AzureADOAuth2Config(
        oauth2_enabled=True,
        azure_tenant_id="test-tenant",
        oauth2_client_id="azure-client-id",
        oauth2_client_secret="azure-secret",
        oauth2_redirect_uri="http://localhost:8000/callback",
    )


class TestGoogleOAuth2Provider:
    """Test Google OAuth2 provider."""

    def test_provider_name(self, google_config):
        """Test provider name."""
        provider = GoogleOAuth2Provider(google_config)
        assert provider.get_provider_name() == "google"

    def test_generate_authorization_url(self, google_config):
        """Test authorization URL generation."""
        provider = GoogleOAuth2Provider(google_config)
        auth_url, state = provider.generate_authorization_url()

        assert "accounts.google.com" in auth_url
        assert "client_id=google-client-id" in auth_url
        assert "redirect_uri=" in auth_url
        assert "response_type=code" in auth_url
        assert "scope=" in auth_url
        assert f"state={state}" in auth_url
        assert len(state) > 0

    def test_generate_authorization_url_with_custom_state(self, google_config):
        """Test authorization URL with custom state."""
        provider = GoogleOAuth2Provider(google_config)
        custom_state = "custom-state-value"
        auth_url, state = provider.generate_authorization_url(custom_state)

        assert state == custom_state
        assert f"state={custom_state}" in auth_url

    @pytest.mark.asyncio
    async def test_extract_user_from_token(self, google_config):
        """Test extracting user from Google token."""
        provider = GoogleOAuth2Provider(google_config)

        # Mock validate_id_token
        with patch.object(provider, "validate_id_token", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = {
                "email": "test@gmail.com",
                "name": "Test User",
                "sub": "google-user-id",
            }

            token_data = {"id_token": "mock-id-token"}
            user = await provider.extract_user_from_token(token_data)

            assert isinstance(user, User)
            assert user.username == "test@gmail.com"
            assert user.email == "test@gmail.com"
            assert user.full_name == "Test User"

    @pytest.mark.asyncio
    async def test_extract_user_no_id_token(self, google_config):
        """Test extracting user without ID token raises error."""
        provider = GoogleOAuth2Provider(google_config)

        token_data = {"access_token": "mock-access-token"}

        with pytest.raises(Exception, match="No ID token in response"):
            await provider.extract_user_from_token(token_data)


class TestAzureADOAuth2Provider:
    """Test Azure AD OAuth2 provider."""

    def test_provider_name(self, azure_config):
        """Test provider name."""
        provider = AzureADOAuth2Provider(azure_config)
        assert provider.get_provider_name() == "azure"

    def test_generate_authorization_url(self, azure_config):
        """Test authorization URL generation."""
        provider = AzureADOAuth2Provider(azure_config)
        auth_url, _state = provider.generate_authorization_url()

        assert "login.microsoftonline.com" in auth_url
        assert "test-tenant" in auth_url
        assert "client_id=azure-client-id" in auth_url

    @pytest.mark.asyncio
    async def test_extract_user_from_token(self, azure_config):
        """Test extracting user from Azure AD token."""
        provider = AzureADOAuth2Provider(azure_config)

        with patch.object(provider, "validate_id_token", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = {
                "preferred_username": "test@company.com",
                "email": "test@company.com",
                "name": "Test User",
                "sub": "azure-user-id",
            }

            token_data = {"id_token": "mock-id-token"}
            user = await provider.extract_user_from_token(token_data)

            assert isinstance(user, User)
            assert user.username == "test@company.com"
            assert user.email == "test@company.com"
            assert user.full_name == "Test User"

    @pytest.mark.asyncio
    async def test_extract_user_fallback_to_email(self, azure_config):
        """Test extracting user falls back to email if no preferred_username."""
        provider = AzureADOAuth2Provider(azure_config)

        with patch.object(provider, "validate_id_token", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = {
                "email": "test@company.com",
                "name": "Test User",
            }

            token_data = {"id_token": "mock-id-token"}
            user = await provider.extract_user_from_token(token_data)

            assert user.username == "test@company.com"


class TestGenericOIDCProvider:
    """Test Generic OIDC provider."""

    def test_provider_name(self, oauth2_config):
        """Test provider name."""
        provider = GenericOIDCProvider(oauth2_config)
        assert provider.get_provider_name() == "generic"

    @pytest.mark.asyncio
    async def test_extract_user_from_id_token(self, oauth2_config):
        """Test extracting user from ID token."""
        provider = GenericOIDCProvider(oauth2_config)

        with patch.object(provider, "validate_id_token", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = {
                "preferred_username": "testuser",
                "email": "test@example.com",
                "name": "Test User",
                "sub": "user-id",
            }

            token_data = {"id_token": "mock-id-token"}
            user = await provider.extract_user_from_token(token_data)

            assert user.username == "testuser"
            assert user.email == "test@example.com"
            assert user.full_name == "Test User"

    @pytest.mark.asyncio
    async def test_extract_user_from_access_token(self, oauth2_config):
        """Test extracting user from access token via userinfo."""
        provider = GenericOIDCProvider(oauth2_config)

        with patch.object(provider, "get_user_info", new_callable=AsyncMock) as mock_userinfo:
            mock_userinfo.return_value = {
                "email": "test@example.com",
                "name": "Test User",
                "sub": "user-id",
            }

            token_data = {"access_token": "mock-access-token"}
            user = await provider.extract_user_from_token(token_data)

            assert user.username == "test@example.com"
            assert user.email == "test@example.com"

    @pytest.mark.asyncio
    async def test_extract_user_username_fallback(self, oauth2_config):
        """Test username fallback logic."""
        provider = GenericOIDCProvider(oauth2_config)

        with patch.object(provider, "validate_id_token", new_callable=AsyncMock) as mock_validate:
            # Test fallback: preferred_username -> email -> sub
            mock_validate.return_value = {
                "sub": "user-id-123",
                "name": "Test User",
            }

            token_data = {"id_token": "mock-id-token"}
            user = await provider.extract_user_from_token(token_data)

            assert user.username == "user-id-123"

    @pytest.mark.asyncio
    async def test_extract_user_no_token(self, oauth2_config):
        """Test extracting user without any token raises error."""
        provider = GenericOIDCProvider(oauth2_config)

        token_data: dict[str, str] = {}

        with pytest.raises(Exception, match="No ID token or access token in response"):
            await provider.extract_user_from_token(token_data)


class TestOAuth2ProviderCommon:
    """Test common OAuth2 provider functionality."""

    @pytest.mark.asyncio
    async def test_exchange_code_for_token(self, oauth2_config):
        """Test exchanging authorization code for token."""
        provider = GenericOIDCProvider(oauth2_config)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "mock-access-token",
            "id_token": "mock-id-token",
            "token_type": "Bearer",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

            token_data = await provider.exchange_code_for_token("auth-code")

            assert token_data["access_token"] == "mock-access-token"
            assert token_data["id_token"] == "mock-id-token"

    @pytest.mark.asyncio
    async def test_discover_endpoints(self, oauth2_config):
        """Test OIDC discovery."""
        oauth2_config.oauth2_discovery_url = "https://provider.com/.well-known/openid-configuration"
        provider = GenericOIDCProvider(oauth2_config)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "issuer": "https://provider.com",
            "authorization_endpoint": "https://provider.com/authorize",
            "token_endpoint": "https://provider.com/token",
            "jwks_uri": "https://provider.com/jwks",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)

            discovery = await provider.discover_endpoints()

            assert discovery["issuer"] == "https://provider.com"
            assert discovery["authorization_endpoint"] == "https://provider.com/authorize"

    @pytest.mark.asyncio
    async def test_discover_endpoints_cached(self, oauth2_config):
        """Test that discovery results are cached."""
        from datetime import UTC, datetime

        oauth2_config.oauth2_discovery_url = "https://provider.com/.well-known/openid-configuration"
        provider = GenericOIDCProvider(oauth2_config)

        # Set cache with a fresh timestamp so TTL guard passes
        provider._discovery_cache = {"cached": "data"}
        provider._discovery_cache_time = datetime.now(UTC)

        # Should return cached data without making HTTP request
        discovery = await provider.discover_endpoints()

        assert discovery == {"cached": "data"}


class TestGetOAuth2Provider:
    """Test OAuth2 provider factory function."""

    def test_get_google_provider(self, google_config):
        """Test getting Google provider."""
        provider = get_oauth2_provider(google_config)

        assert isinstance(provider, GoogleOAuth2Provider)
        assert provider.get_provider_name() == "google"

    def test_get_azure_provider(self, azure_config):
        """Test getting Azure provider."""
        provider = get_oauth2_provider(azure_config)

        assert isinstance(provider, AzureADOAuth2Provider)
        assert provider.get_provider_name() == "azure"

    def test_get_generic_provider(self, oauth2_config):
        """Test getting generic provider."""
        provider = get_oauth2_provider(oauth2_config)

        assert isinstance(provider, GenericOIDCProvider)
        assert provider.get_provider_name() == "generic"

    def test_get_provider_unknown(self):
        """Test getting provider with unknown type."""
        config = OAuth2Config(oauth2_provider="unknown")
        provider = get_oauth2_provider(config)

        assert isinstance(provider, GenericOIDCProvider)


# ---------------------------------------------------------------------------
# OIDC ID token validation with real RSA keys
# ---------------------------------------------------------------------------

_KID = "test-kid"
_ISSUER = "https://provider.com"
_CLIENT_ID = "test-client-id"
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _rsa_key_pair() -> tuple[str, str]:
    """Return (private PEM, public PEM) for a fresh RSA key."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private_pem, public_pem


@pytest.fixture(scope="module")
def signing_key() -> dict[str, Any]:
    """The provider's signing key and the JWKS that publishes it."""
    private_pem, public_pem = _rsa_key_pair()
    public_key = cast(rsa.RSAPublicKey, serialization.load_pem_public_key(public_pem.encode()))
    public_jwk = json.loads(RSAAlgorithm.to_jwk(public_key))
    public_jwk["kid"] = _KID
    return {"private_pem": private_pem, "public_pem": public_pem, "jwks": {"keys": [public_jwk]}}


@pytest.fixture(scope="module")
def attacker_private_pem() -> str:
    return _rsa_key_pair()[0]


def _claims(**overrides: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "iss": _ISSUER,
        "aud": _CLIENT_ID,
        "sub": "user-123",
        "email": "alice@example.com",
        "name": "Alice Example",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }
    claims.update(overrides)
    return claims


def _sign_rs256(claims: dict[str, Any], *, private_pem: str, kid: str = _KID) -> str:
    return jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": kid})


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unsigned_token(header: dict[str, Any], claims: dict[str, Any]) -> str:
    return f"{_b64url(json.dumps(header).encode())}.{_b64url(json.dumps(claims).encode())}"


@pytest.fixture
def oidc_provider(*, oauth2_config, signing_key) -> GenericOIDCProvider:
    """Generic provider whose JWKS is already cached (no HTTP)."""
    provider = GenericOIDCProvider(oauth2_config)
    provider._jwks_cache = signing_key["jwks"]
    provider._jwks_cache_time = datetime.now(UTC)
    return provider


class TestValidateIdToken:
    """``validate_id_token`` must only accept untampered RS256 tokens for our client and issuer."""

    async def test_valid_token_returns_claims(self, *, oidc_provider, signing_key):
        token = _sign_rs256(_claims(), private_pem=signing_key["private_pem"])

        payload = await oidc_provider.validate_id_token(token)

        assert payload["sub"] == "user-123"
        assert payload["email"] == "alice@example.com"

    async def test_audience_defaults_to_client_id(self, *, oidc_provider, signing_key):
        oidc_provider.config.oidc_audience = ""
        token = _sign_rs256(_claims(aud=_CLIENT_ID), private_pem=signing_key["private_pem"])

        payload = await oidc_provider.validate_id_token(token)

        assert payload["aud"] == _CLIENT_ID

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"aud": "some-other-client"}, id="wrong_audience"),
            pytest.param({"iss": "https://evil.example.com"}, id="wrong_issuer"),
            pytest.param({"exp": int((datetime.now(UTC) - timedelta(minutes=5)).timestamp())}, id="expired"),
        ],
    )
    async def test_claim_violations_are_rejected(self, *, oidc_provider, signing_key, overrides):
        token = _sign_rs256(_claims(**overrides), private_pem=signing_key["private_pem"])

        with pytest.raises(ExternalServiceError, match="ID token validation failed"):
            await oidc_provider.validate_id_token(token)

    async def test_unknown_kid_raises_configuration_error(self, *, oidc_provider, signing_key):
        token = _sign_rs256(_claims(), private_pem=signing_key["private_pem"], kid="rotated-away")

        with pytest.raises(ConfigurationError, match="No matching key found for kid: rotated-away"):
            await oidc_provider.validate_id_token(token)

    async def test_token_signed_by_foreign_key_is_rejected(self, *, oidc_provider, attacker_private_pem):
        token = _sign_rs256(_claims(), private_pem=attacker_private_pem)

        with pytest.raises(ExternalServiceError, match="ID token validation failed"):
            await oidc_provider.validate_id_token(token)

    async def test_tampered_payload_is_rejected(self, *, oidc_provider, signing_key):
        token = _sign_rs256(_claims(), private_pem=signing_key["private_pem"])
        header, _, signature = token.split(".")
        forged = _b64url(json.dumps(_claims(email="admin@example.com")).encode())

        with pytest.raises(ExternalServiceError, match="ID token validation failed"):
            await oidc_provider.validate_id_token(f"{header}.{forged}.{signature}")

    async def test_alg_none_is_rejected(self, oidc_provider):
        token = _unsigned_token({"alg": "none", "kid": _KID}, _claims()) + "."

        with pytest.raises(ExternalServiceError, match="ID token validation failed"):
            await oidc_provider.validate_id_token(token)

    async def test_hs256_key_confusion_with_public_key_is_rejected(self, *, oidc_provider, signing_key):
        """Classic RS256->HS256 confusion: HMAC-sign with the *public* key as the secret."""
        signing_input = _unsigned_token({"alg": "HS256", "kid": _KID, "typ": "JWT"}, _claims())
        signature = hmac.new(signing_key["public_pem"].encode(), signing_input.encode(), hashlib.sha256).digest()
        token = f"{signing_input}.{_b64url(signature)}"

        with pytest.raises(ExternalServiceError, match="ID token validation failed"):
            await oidc_provider.validate_id_token(token)

    async def test_malformed_token_is_rejected(self, oidc_provider):
        with pytest.raises(ExternalServiceError, match="ID token validation failed"):
            await oidc_provider.validate_id_token("not-a-jwt")

    async def test_jwks_fetch_failure_propagates(self, oauth2_config):
        provider = GenericOIDCProvider(oauth2_config)

        with patch.object(
            provider, "get_jwks", new_callable=AsyncMock, side_effect=ExternalServiceError("JWKS fetch failed: boom")
        ):
            with pytest.raises(ExternalServiceError, match="JWKS fetch failed: boom"):
                await provider.validate_id_token("irrelevant")

    async def test_unexpected_error_is_wrapped(self, *, oauth2_config, signing_key):
        provider = GenericOIDCProvider(oauth2_config)
        token = _sign_rs256(_claims(), private_pem=signing_key["private_pem"])

        # A malformed JWKS document (list instead of object) is not a PyJWTError.
        with patch.object(provider, "get_jwks", new_callable=AsyncMock, return_value=["not", "a", "jwks"]):
            with pytest.raises(ExternalServiceError, match=r"^Token validation failed"):
                await provider.validate_id_token(token)


# ---------------------------------------------------------------------------
# HTTP interactions through httpx.MockTransport (real httpx client, no network)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_http(monkeypatch):
    """Route every ``httpx.AsyncClient`` to a MockTransport handler.

    Usage: ``requests = mock_http(handler)``; ``requests`` collects every request sent.
    """

    def install(handler) -> list[httpx.Request]:
        seen: list[httpx.Request] = []

        def recording_handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        transport = httpx.MockTransport(recording_handler)
        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: _REAL_ASYNC_CLIENT(transport=transport))
        return seen

    return install


class TestProviderHttpInteractions:
    """Discovery, JWKS, userinfo and token endpoint calls, including failure modes."""

    async def test_jwks_uri_is_resolved_through_discovery(self, *, oauth2_config, signing_key, mock_http):
        oauth2_config.oauth2_jwks_uri = ""
        oauth2_config.oauth2_discovery_url = "https://provider.com/.well-known/openid-configuration"
        responses = {
            "/.well-known/openid-configuration": {"jwks_uri": "https://provider.com/discovered-jwks"},
            "/discovered-jwks": signing_key["jwks"],
        }
        requests = mock_http(lambda request: httpx.Response(200, json=responses[request.url.path]))
        provider = GenericOIDCProvider(oauth2_config)

        jwks = await provider.get_jwks()

        assert jwks == signing_key["jwks"]
        assert [str(r.url) for r in requests] == [
            "https://provider.com/.well-known/openid-configuration",
            "https://provider.com/discovered-jwks",
        ]

    async def test_jwks_missing_from_discovery_raises_configuration_error(self, *, oauth2_config, mock_http):
        oauth2_config.oauth2_jwks_uri = ""
        oauth2_config.oauth2_discovery_url = "https://provider.com/.well-known/openid-configuration"
        mock_http(lambda request: httpx.Response(200, json={"issuer": _ISSUER}))

        with pytest.raises(ConfigurationError, match="JWKS URI not configured or discovered"):
            await GenericOIDCProvider(oauth2_config).get_jwks()

    async def test_stale_jwks_cache_is_refreshed(self, *, oauth2_config, signing_key, mock_http):
        requests = mock_http(lambda request: httpx.Response(200, json=signing_key["jwks"]))
        provider = GenericOIDCProvider(oauth2_config)
        provider._jwks_cache = {"keys": []}
        provider._jwks_cache_time = datetime.now(UTC) - timedelta(hours=2)

        jwks = await provider.get_jwks()

        assert jwks == signing_key["jwks"]
        assert len(requests) == 1

    async def test_jwks_endpoint_error_raises_external_service_error(self, *, oauth2_config, mock_http):
        mock_http(lambda request: httpx.Response(503))

        with pytest.raises(ExternalServiceError, match="JWKS fetch failed"):
            await GenericOIDCProvider(oauth2_config).get_jwks()

    @pytest.mark.parametrize(
        "failure",
        [
            pytest.param(lambda request: httpx.Response(500), id="http_500"),
            pytest.param(lambda request: httpx.Response(200, text="<html>not json</html>"), id="not_json"),
            pytest.param(_raise(httpx.ConnectTimeout("timed out")), id="timeout"),
        ],
    )
    async def test_discovery_failures_raise_external_service_error(self, *, oauth2_config, mock_http, failure):
        oauth2_config.oauth2_discovery_url = "https://provider.com/.well-known/openid-configuration"
        mock_http(failure)
        provider = GenericOIDCProvider(oauth2_config)

        with pytest.raises(ExternalServiceError, match="OIDC discovery failed"):
            await provider.discover_endpoints()

        assert provider._discovery_cache is None

    async def test_userinfo_endpoint_resolved_through_discovery_with_bearer_header(self, *, oauth2_config, mock_http):
        oauth2_config.oauth2_userinfo_endpoint = ""
        oauth2_config.oauth2_discovery_url = "https://provider.com/.well-known/openid-configuration"
        responses = {
            "/.well-known/openid-configuration": {"userinfo_endpoint": "https://provider.com/me"},
            "/me": {"sub": "user-123", "email": "alice@example.com"},
        }
        requests = mock_http(lambda request: httpx.Response(200, json=responses[request.url.path]))

        userinfo = await GenericOIDCProvider(oauth2_config).get_user_info("access-token-xyz")

        assert userinfo == {"sub": "user-123", "email": "alice@example.com"}
        assert str(requests[-1].url) == "https://provider.com/me"
        assert requests[-1].headers["Authorization"] == "Bearer access-token-xyz"

    @pytest.mark.parametrize(
        "failure",
        [
            pytest.param(lambda request: httpx.Response(401, json={"error": "invalid_token"}), id="http_401"),
            pytest.param(_raise(httpx.ConnectError("connection refused")), id="network_error"),
        ],
    )
    async def test_userinfo_failures_raise_external_service_error(self, *, oauth2_config, mock_http, failure):
        mock_http(failure)

        with pytest.raises(ExternalServiceError, match="Userinfo fetch failed"):
            await GenericOIDCProvider(oauth2_config).get_user_info("expired-access-token")

    async def test_token_exchange_posts_authorization_code_grant(self, *, oauth2_config, mock_http):
        requests = mock_http(lambda request: httpx.Response(200, json={"access_token": "at", "id_token": "it"}))

        token_data = await GenericOIDCProvider(oauth2_config).exchange_code_for_token("auth-code-123")

        assert token_data == {"access_token": "at", "id_token": "it"}
        (request,) = requests
        assert request.method == "POST"
        assert str(request.url) == "https://provider.com/token"
        assert dict(parse_qsl(request.content.decode())) == {
            "client_id": "test-client-id",
            "client_secret": "test-secret",  # pragma: allowlist secret
            "code": "auth-code-123",
            "redirect_uri": "http://localhost:8000/callback",
            "grant_type": "authorization_code",
        }

    @pytest.mark.parametrize(
        "failure",
        [
            pytest.param(lambda request: httpx.Response(400, json={"error": "invalid_grant"}), id="invalid_grant"),
            pytest.param(_raise(httpx.ReadTimeout("timed out")), id="timeout"),
            pytest.param(lambda request: httpx.Response(200, text="not json"), id="not_json"),
        ],
    )
    async def test_token_exchange_failures_raise_external_service_error(self, *, oauth2_config, mock_http, failure):
        mock_http(failure)

        with pytest.raises(ExternalServiceError, match="Token exchange failed"):
            await GenericOIDCProvider(oauth2_config).exchange_code_for_token("bad-code")

    async def test_token_exchange_error_does_not_leak_client_secret(self, *, oauth2_config, mock_http):
        mock_http(lambda request: httpx.Response(400, json={"error": "invalid_grant"}))

        with pytest.raises(ExternalServiceError) as exc_info:
            await GenericOIDCProvider(oauth2_config).exchange_code_for_token("bad-code")

        assert "test-secret" not in str(exc_info.value)

    async def test_google_login_end_to_end_with_real_signature(self, *, google_config, signing_key, mock_http):
        """Full Google extraction: JWKS served over (mocked) HTTP, real RS256 verification."""
        mock_http(lambda request: httpx.Response(200, json=signing_key["jwks"]))
        id_token = _sign_rs256(
            _claims(iss="https://accounts.google.com", aud="google-client-id", email="bob@gmail.com", name="Bob"),
            private_pem=signing_key["private_pem"],
        )

        user = await GoogleOAuth2Provider(google_config).extract_user_from_token({"id_token": id_token})

        assert user == User(username="bob@gmail.com", email="bob@gmail.com", full_name="Bob")
