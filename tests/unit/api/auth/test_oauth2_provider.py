# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for OAuth2 provider implementations."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docpipe.api.auth.models import User
from docpipe.api.auth.oauth2_config import OAuth2Config
from docpipe.api.auth.oauth2_provider import (
    AzureADOAuth2Provider,
    GenericOIDCProvider,
    GoogleOAuth2Provider,
    get_oauth2_provider,
)
from docpipe.exceptions.docpipe_exceptions import ConfigurationError, ExternalServiceError


def _make_config(**kwargs) -> OAuth2Config:
    base = {
        "oauth2_provider": "generic",
        "oauth2_client_id": "client-id",
        "oauth2_client_secret": "client-secret",  # pragma: allowlist secret
        "oauth2_redirect_uri": "http://localhost/callback",
        "oauth2_scope": "openid profile email",
        "oauth2_authorization_endpoint": "https://provider.example/auth",
        "oauth2_token_endpoint": "https://provider.example/token",
        "oauth2_userinfo_endpoint": "https://provider.example/userinfo",
        "oauth2_jwks_uri": "https://provider.example/jwks",
        "oidc_issuer": "https://provider.example",
        "oidc_audience": "client-id",
        "oauth2_discovery_url": "",
    }
    base.update(kwargs)
    return OAuth2Config(**base)


# ---------------------------------------------------------------------------
# get_oauth2_provider factory
# ---------------------------------------------------------------------------


def test_get_oauth2_provider_returns_google_provider():
    config = _make_config(oauth2_provider="google")
    provider = get_oauth2_provider(config)
    assert isinstance(provider, GoogleOAuth2Provider)


def test_get_oauth2_provider_returns_azure_provider():
    config = _make_config(oauth2_provider="azure")
    provider = get_oauth2_provider(config)
    assert isinstance(provider, AzureADOAuth2Provider)


def test_get_oauth2_provider_returns_generic_for_unknown():
    config = _make_config(oauth2_provider="unknown")
    provider = get_oauth2_provider(config)
    assert isinstance(provider, GenericOIDCProvider)


# ---------------------------------------------------------------------------
# get_provider_name
# ---------------------------------------------------------------------------


def test_google_provider_name():
    config = _make_config(oauth2_provider="google")
    provider = GoogleOAuth2Provider(config)
    assert provider.get_provider_name() == "google"


def test_azure_provider_name():
    config = _make_config(oauth2_provider="azure")
    provider = AzureADOAuth2Provider(config)
    assert provider.get_provider_name() == "azure"


def test_generic_provider_name():
    config = _make_config()
    provider = GenericOIDCProvider(config)
    assert provider.get_provider_name() == "generic"


# ---------------------------------------------------------------------------
# generate_authorization_url
# ---------------------------------------------------------------------------


def test_generate_authorization_url_contains_required_params():
    config = _make_config()
    provider = GenericOIDCProvider(config)
    url, state = provider.generate_authorization_url()
    assert "client_id=client-id" in url
    assert "response_type=code" in url
    assert state in url
    assert len(state) > 0


def test_generate_authorization_url_uses_provided_state():
    config = _make_config()
    provider = GenericOIDCProvider(config)
    url, returned_state = provider.generate_authorization_url(state="my-custom-state")
    assert returned_state == "my-custom-state"
    assert "state=my-custom-state" in url


# ---------------------------------------------------------------------------
# discover_endpoints — cache hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discover_endpoints_returns_cached_value():
    config = _make_config()
    provider = GenericOIDCProvider(config)
    cached = {"jwks_uri": "https://provider.example/jwks"}
    provider._discovery_cache = cached
    provider._discovery_cache_time = datetime.now(UTC)

    result = await provider.discover_endpoints()
    assert result is cached


@pytest.mark.asyncio
async def test_discover_endpoints_returns_empty_when_no_discovery_url():
    config = _make_config(oauth2_discovery_url="")
    provider = GenericOIDCProvider(config)

    result = await provider.discover_endpoints()
    assert result == {}


@pytest.mark.asyncio
async def test_discover_endpoints_fetches_and_caches():
    config = _make_config(oauth2_discovery_url="https://provider.example/.well-known/openid-configuration")
    provider = GenericOIDCProvider(config)

    mock_response = MagicMock()
    mock_response.json.return_value = {"jwks_uri": "https://provider.example/jwks"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("docpipe.api.auth.oauth2_provider.httpx.AsyncClient", return_value=mock_client):
        result = await provider.discover_endpoints()

    assert result["jwks_uri"] == "https://provider.example/jwks"
    assert provider._discovery_cache is not None


@pytest.mark.asyncio
async def test_discover_endpoints_raises_on_http_error():
    config = _make_config(oauth2_discovery_url="https://provider.example/.well-known/openid-configuration")
    provider = GenericOIDCProvider(config)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=Exception("connection refused"))

    with patch("docpipe.api.auth.oauth2_provider.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ExternalServiceError, match="OIDC discovery failed"):
            await provider.discover_endpoints()


# ---------------------------------------------------------------------------
# get_jwks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_jwks_returns_cached_value():
    config = _make_config()
    provider = GenericOIDCProvider(config)
    cached = {"keys": [{"kid": "key1"}]}
    provider._jwks_cache = cached
    provider._jwks_cache_time = datetime.now(UTC)

    result = await provider.get_jwks()
    assert result is cached


@pytest.mark.asyncio
async def test_get_jwks_fetches_when_uri_configured():
    config = _make_config()
    provider = GenericOIDCProvider(config)

    mock_response = MagicMock()
    mock_response.json.return_value = {"keys": []}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("docpipe.api.auth.oauth2_provider.httpx.AsyncClient", return_value=mock_client):
        result = await provider.get_jwks()

    assert "keys" in result


@pytest.mark.asyncio
async def test_get_jwks_raises_configuration_error_when_no_uri():
    config = _make_config(oauth2_jwks_uri="", oauth2_discovery_url="")
    provider = GenericOIDCProvider(config)
    # Ensure discover_endpoints returns empty (no jwks_uri)
    provider._discovery_cache = {}
    provider._discovery_cache_time = datetime.now(UTC)

    with pytest.raises(ConfigurationError, match="JWKS URI not configured"):
        await provider.get_jwks()


@pytest.mark.asyncio
async def test_get_jwks_raises_on_http_error():
    config = _make_config()
    provider = GenericOIDCProvider(config)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=Exception("timeout"))

    with patch("docpipe.api.auth.oauth2_provider.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ExternalServiceError, match="JWKS fetch failed"):
            await provider.get_jwks()


# ---------------------------------------------------------------------------
# exchange_code_for_token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exchange_code_for_token_returns_token_data():
    config = _make_config()
    provider = GenericOIDCProvider(config)

    mock_response = MagicMock()
    mock_response.json.return_value = {"access_token": "tok", "id_token": "id"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("docpipe.api.auth.oauth2_provider.httpx.AsyncClient", return_value=mock_client):
        result = await provider.exchange_code_for_token("auth-code-123")

    assert result["access_token"] == "tok"


@pytest.mark.asyncio
async def test_exchange_code_for_token_raises_on_error():
    config = _make_config()
    provider = GenericOIDCProvider(config)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=Exception("network error"))

    with patch("docpipe.api.auth.oauth2_provider.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ExternalServiceError, match="Token exchange failed"):
            await provider.exchange_code_for_token("code")


# ---------------------------------------------------------------------------
# get_user_info
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_info_raises_when_no_endpoint():
    config = _make_config(oauth2_userinfo_endpoint="", oauth2_discovery_url="")
    provider = GenericOIDCProvider(config)
    provider._discovery_cache = {}
    provider._discovery_cache_time = datetime.now(UTC)

    with pytest.raises(ConfigurationError, match="Userinfo endpoint"):
        await provider.get_user_info("access-token")


@pytest.mark.asyncio
async def test_get_user_info_returns_user_data():
    config = _make_config()
    provider = GenericOIDCProvider(config)

    mock_response = MagicMock()
    mock_response.json.return_value = {"email": "user@example.com", "name": "User"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("docpipe.api.auth.oauth2_provider.httpx.AsyncClient", return_value=mock_client):
        result = await provider.get_user_info("access-token")

    assert result["email"] == "user@example.com"


# ---------------------------------------------------------------------------
# extract_user_from_token — Google
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_extract_user_raises_when_no_id_token():
    config = _make_config(oauth2_provider="google")
    provider = GoogleOAuth2Provider(config)

    with pytest.raises(ExternalServiceError, match="No ID token"):
        await provider.extract_user_from_token({})


@pytest.mark.asyncio
async def test_google_extract_user_returns_user():
    config = _make_config(oauth2_provider="google")
    provider = GoogleOAuth2Provider(config)

    provider.validate_id_token = AsyncMock(
        return_value={"sub": "google-sub", "email": "alice@example.com", "name": "Alice"}
    )

    user = await provider.extract_user_from_token({"id_token": "tok"})
    assert isinstance(user, User)
    assert user.username == "oidc:google:google-sub"
    assert user.email == "alice@example.com"


# ---------------------------------------------------------------------------
# extract_user_from_token — Azure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_azure_extract_user_raises_when_no_id_token():
    config = _make_config(oauth2_provider="azure")
    provider = AzureADOAuth2Provider(config)

    with pytest.raises(ExternalServiceError, match="No ID token"):
        await provider.extract_user_from_token({})


@pytest.mark.asyncio
async def test_azure_extract_user_returns_user_with_preferred_username():
    config = _make_config(oauth2_provider="azure")
    provider = AzureADOAuth2Provider(config)

    provider.validate_id_token = AsyncMock(
        return_value={"preferred_username": "bob@corp.com", "email": "bob@corp.com", "name": "Bob"}
    )

    user = await provider.extract_user_from_token({"id_token": "tok"})
    assert user.username == "oidc:azure:bob@corp.com"
    assert user.full_name == "Bob"


# ---------------------------------------------------------------------------
# extract_user_from_token — Generic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generic_extract_user_raises_when_no_tokens():
    config = _make_config()
    provider = GenericOIDCProvider(config)

    with pytest.raises(ExternalServiceError, match="No ID token or access token"):
        await provider.extract_user_from_token({})


@pytest.mark.asyncio
async def test_generic_extract_user_from_id_token():
    config = _make_config()
    provider = GenericOIDCProvider(config)
    provider.validate_id_token = AsyncMock(
        return_value={"preferred_username": "carol", "email": "carol@example.com", "name": "Carol"}
    )

    user = await provider.extract_user_from_token({"id_token": "tok"})
    assert user.username == "oidc:generic:carol"
    assert user.email == "carol@example.com"


@pytest.mark.asyncio
async def test_generic_extract_user_falls_back_to_access_token():
    config = _make_config()
    provider = GenericOIDCProvider(config)
    provider.get_user_info = AsyncMock(return_value={"sub": "user-sub", "email": "", "name": ""})

    user = await provider.extract_user_from_token({"access_token": "access-tok"})
    assert user.username == "oidc:generic:user-sub"
