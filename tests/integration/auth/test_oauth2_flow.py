# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Integration tests for OAuth2 authentication flow."""

from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from docpipe.api.auth.models import User
from docpipe.api.auth.oauth2_config import OAuth2Config, get_oauth2_config
from docpipe.api.auth.oauth2_routes import _state_store
from docpipe.api.main import app

_JWT_SECRET = "integration-test-secret-key-long-enough"  # pragma: allowlist secret
_SESSION_COOKIE = "docpipe_access_token"


def _error_message(response) -> str:
    """Return the message of the first error in the API's standard error envelope."""
    return response.json()["errors"][0]["message"].lower()


@pytest.fixture(autouse=True)
def _clean_state_store():
    _state_store.clear()
    yield
    _state_store.clear()


@pytest.fixture
def client(monkeypatch):
    """Create test client with a JWT secret configured."""
    monkeypatch.setenv("JWT_SECRET_KEY", _JWT_SECRET)
    return TestClient(app)


@pytest.fixture
def mock_oauth2_config():
    """Mock OAuth2 configuration."""
    return OAuth2Config(
        oauth2_enabled=True,
        oauth2_provider="google",
        oauth2_client_id="test-client-id",
        oauth2_client_secret="test-secret",
        oauth2_redirect_uri="http://localhost:8000/auth/oauth2/callback",
        oauth2_authorization_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
        oauth2_token_endpoint="https://oauth2.googleapis.com/token",
        oauth2_userinfo_endpoint="https://openidconnect.googleapis.com/v1/userinfo",
        oauth2_jwks_uri="https://www.googleapis.com/oauth2/v3/certs",
        oidc_issuer="https://accounts.google.com",
        oidc_audience="test-client-id",
    )


class TestOAuth2AuthorizeEndpoint:
    """Test OAuth2 authorize endpoint."""

    def test_authorize_redirect(self, client, mock_oauth2_config):
        """Test authorize endpoint redirects to provider."""
        with patch("docpipe.api.auth.oauth2_routes.get_oauth2_config") as mock_get_config:
            mock_get_config.return_value = mock_oauth2_config

            response = client.get("/auth/oauth2/authorize?provider=google", follow_redirects=False)

            assert response.status_code == 307  # Redirect
            assert "location" in response.headers
            assert "accounts.google.com" in response.headers["location"]

    def test_authorize_with_redirect_after(self, client, mock_oauth2_config):
        """A relative redirect_after is accepted and a nonce cookie is set."""
        with patch("docpipe.api.auth.oauth2_routes.get_oauth2_config") as mock_get_config:
            mock_get_config.return_value = mock_oauth2_config

            response = client.get(
                "/auth/oauth2/authorize?provider=google&redirect_after=/flows/abc",
                follow_redirects=False,
            )

            assert response.status_code == 307
            assert "docpipe_oauth2_nonce" in response.headers["set-cookie"]

    def test_authorize_with_absolute_redirect_after_is_not_rejected(self, client, mock_oauth2_config):
        """An absolute redirect_after is dropped (the callback falls back to /ui/projects), not a 400."""
        with patch("docpipe.api.auth.oauth2_routes.get_oauth2_config") as mock_get_config:
            mock_get_config.return_value = mock_oauth2_config

            response = client.get(
                "/auth/oauth2/authorize?provider=google&redirect_after=http://localhost:3000/dashboard",
                follow_redirects=False,
            )

            assert response.status_code == 307

    def test_authorize_oauth2_disabled(self, client):
        """Test authorize when OAuth2 is disabled."""
        disabled_config = OAuth2Config(oauth2_enabled=False)

        with patch("docpipe.api.auth.oauth2_routes.get_oauth2_config") as mock_get_config:
            mock_get_config.return_value = disabled_config

            response = client.get("/auth/oauth2/authorize?provider=google")

            assert response.status_code == 503
            assert "not enabled" in _error_message(response)

    def test_authorize_missing_credentials(self, client):
        """Test authorize with missing OAuth2 credentials."""
        incomplete_config = OAuth2Config(
            oauth2_enabled=True,
            oauth2_client_id="",
            oauth2_client_secret="",
        )

        with patch("docpipe.api.auth.oauth2_routes.get_oauth2_config") as mock_get_config:
            mock_get_config.return_value = incomplete_config

            response = client.get("/auth/oauth2/authorize?provider=google")

            assert response.status_code == 503
            assert "not properly configured" in _error_message(response)


class TestOAuth2CallbackEndpoint:
    """Test OAuth2 callback endpoint against the real state and nonce store."""

    @staticmethod
    def _start_login(client, *, query: str = "") -> str:
        """Call /authorize (the browser receives the nonce cookie) and return the issued state."""
        response = client.get(f"/auth/oauth2/authorize?provider=google{query}", follow_redirects=False)
        assert response.status_code == 307
        return parse_qs(urlparse(response.headers["location"]).query)["state"][0]

    def test_callback_success(self, client, mock_oauth2_config):
        """A matching state and nonce complete the login: session cookie plus a redirect into the SPA."""
        with (
            patch("docpipe.api.auth.oauth2_routes.get_oauth2_config") as mock_get_config,
            patch("docpipe.api.auth.oauth2_provider.GoogleOAuth2Provider.exchange_code_for_token") as mock_exchange,
            patch("docpipe.api.auth.oauth2_provider.GoogleOAuth2Provider.extract_user_from_token") as mock_extract,
        ):
            mock_get_config.return_value = mock_oauth2_config
            mock_exchange.return_value = {"access_token": "mock-access-token", "id_token": "mock-id-token"}
            mock_extract.return_value = User(username="test@gmail.com", email="test@gmail.com", full_name="Test User")
            state = self._start_login(client, query="&return_to=/flows/abc")

            response = client.get(
                f"/auth/oauth2/callback?code=test-code&state={state}&provider=google", follow_redirects=False
            )

            assert response.status_code == 302
            assert response.headers["location"] == "/ui/flows/abc"
            token = response.cookies.get(_SESSION_COOKIE)
            assert token
            assert token not in response.headers["location"]

    def test_callback_session_cookie_authenticates_me(self, client, mock_oauth2_config, monkeypatch):
        """The cookie issued by the callback is accepted by /auth/me."""
        monkeypatch.setenv("DOCPIPE_AUTH_ENABLED", "true")
        with (
            patch("docpipe.api.auth.oauth2_routes.get_oauth2_config") as mock_get_config,
            patch("docpipe.api.auth.oauth2_provider.GoogleOAuth2Provider.exchange_code_for_token") as mock_exchange,
            patch("docpipe.api.auth.oauth2_provider.GoogleOAuth2Provider.extract_user_from_token") as mock_extract,
        ):
            mock_get_config.return_value = mock_oauth2_config
            mock_exchange.return_value = {"id_token": "mock-id-token"}
            mock_extract.return_value = User(username="test@gmail.com", email="test@gmail.com", full_name="Test User")
            state = self._start_login(client)
            callback = client.get(
                f"/auth/oauth2/callback?code=test-code&state={state}&provider=google", follow_redirects=False
            )

            me = TestClient(app, cookies={_SESSION_COOKIE: callback.cookies.get(_SESSION_COOKIE)}).get("/auth/me")

            assert me.status_code == 200
            assert me.json()["username"] == "test@gmail.com"
            assert me.json()["roles"] == ["viewer"]

    def test_callback_invalid_state(self, client, mock_oauth2_config):
        """Test callback with invalid state parameter."""
        with patch("docpipe.api.auth.oauth2_routes.get_oauth2_config") as mock_get_config:
            mock_get_config.return_value = mock_oauth2_config

            response = client.get("/auth/oauth2/callback?code=test-code&state=invalid-state&provider=google")

            assert response.status_code == 400
            assert "invalid" in _error_message(response)
            assert _SESSION_COOKIE not in response.headers.get("set-cookie", "")

    def test_callback_without_nonce_cookie_is_rejected(self, client, mock_oauth2_config):
        """A callback from a browser that did not start the login is refused."""
        with patch("docpipe.api.auth.oauth2_routes.get_oauth2_config") as mock_get_config:
            mock_get_config.return_value = mock_oauth2_config
            state = self._start_login(client)
            client.cookies.clear()

            response = client.get(f"/auth/oauth2/callback?code=test-code&state={state}&provider=google")

            assert response.status_code == 400
            assert _SESSION_COOKIE not in response.headers.get("set-cookie", "")

    def test_callback_missing_code(self, client, mock_oauth2_config):
        """Test callback without authorization code."""
        with patch("docpipe.api.auth.oauth2_routes.get_oauth2_config") as mock_get_config:
            mock_get_config.return_value = mock_oauth2_config

            response = client.get("/auth/oauth2/callback?state=test-state&provider=google")

            assert response.status_code == 400  # The API reports request validation errors as 400 validation_error
            assert response.json()["errors"][0]["code"] == "validation_error"

    def test_callback_missing_state(self, client, mock_oauth2_config):
        """Test callback without state parameter."""
        with patch("docpipe.api.auth.oauth2_routes.get_oauth2_config") as mock_get_config:
            mock_get_config.return_value = mock_oauth2_config

            response = client.get("/auth/oauth2/callback?code=test-code&provider=google")

            assert response.status_code == 400
            assert response.json()["errors"][0]["code"] == "validation_error"


class TestOAuth2ProvidersEndpoint:
    """Test OAuth2 providers listing endpoint."""

    def test_list_providers_empty(self, client):
        """Test listing providers when none are configured."""
        with patch("docpipe.api.auth.oauth2_routes.get_oauth2_config") as mock_get_config:
            mock_get_config.return_value = OAuth2Config(oauth2_enabled=False)

            response = client.get("/auth/oauth2/providers")

            assert response.status_code == 200
            assert "providers" in response.json()
            assert len(response.json()["providers"]) == 0

    def test_list_providers_with_google(self, client, mock_oauth2_config):
        """Test listing providers with Google configured."""
        with patch("docpipe.api.auth.oauth2_routes.get_oauth2_config") as mock_get_config:
            mock_get_config.return_value = mock_oauth2_config

            response = client.get("/auth/oauth2/providers")

            assert response.status_code == 200
            providers = response.json()["providers"]
            assert len(providers) > 0

            # Check if Google is in the list
            google_provider = next((p for p in providers if p["name"] == "google"), None)
            if google_provider:
                assert google_provider["display_name"] == "Google"
                assert "authorize_url" in google_provider


class TestOAuth2DiscoveryEndpoint:
    """Test OAuth2 discovery endpoint."""

    def test_discovery_success(self, client, mock_oauth2_config):
        """Test successful OIDC discovery."""
        mock_discovery = {
            "issuer": "https://accounts.google.com",
            "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_endpoint": "https://oauth2.googleapis.com/token",
            "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
        }
        app.dependency_overrides[get_oauth2_config] = lambda: mock_oauth2_config
        try:
            with patch("docpipe.api.auth.oauth2_provider.GoogleOAuth2Provider.discover_endpoints") as mock_discover:
                mock_discover.return_value = mock_discovery

                response = client.get("/auth/oauth2/discovery/google?provider=google")
        finally:
            app.dependency_overrides.pop(get_oauth2_config, None)

        assert response.status_code == 200
        assert response.json()["issuer"] == "https://accounts.google.com"

    def test_discovery_oauth2_disabled(self, client):
        """Test discovery when OAuth2 is disabled."""
        app.dependency_overrides[get_oauth2_config] = lambda: OAuth2Config(oauth2_enabled=False)
        try:
            response = client.get("/auth/oauth2/discovery/google?provider=google")
        finally:
            app.dependency_overrides.pop(get_oauth2_config, None)

        assert response.status_code == 503


class TestOAuth2EndToEndFlow:
    """Test complete OAuth2 authentication flow."""

    @pytest.mark.asyncio
    async def test_complete_flow(self, client, mock_oauth2_config):
        """Test complete OAuth2 flow from authorize to token."""
        with patch("docpipe.api.auth.oauth2_routes.get_oauth2_config") as mock_get_config:
            mock_get_config.return_value = mock_oauth2_config

            # Step 1: Initiate authorization
            response = client.get("/auth/oauth2/authorize?provider=google", follow_redirects=False)
            assert response.status_code == 307

            # Extract state from redirect URL
            location = response.headers["location"]
            assert "state=" in location

            # Step 2: Simulate callback (would normally come from OAuth provider)
            # This is tested separately in TestOAuth2CallbackEndpoint

    def test_flow_with_protected_endpoint(self, client, mock_oauth2_config, monkeypatch):
        """Test using OAuth2 token with protected endpoint."""
        # Create a valid JWT token
        from docpipe.api.auth.jwt_handler import (
            JWTConfig,
            create_access_token,
        )

        monkeypatch.setenv("DOCPIPE_AUTH_ENABLED", "true")
        jwt_config = JWTConfig(jwt_secret_key=_JWT_SECRET)
        token_data = {
            "username": "test@gmail.com",
            "email": "test@gmail.com",
            "full_name": "Test User",
        }
        token = create_access_token(token_data, jwt_config)

        # Use token to access protected endpoint
        response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        assert response.json()["username"] == "test@gmail.com"
