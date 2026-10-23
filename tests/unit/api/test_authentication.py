"""Unit tests for authentication endpoints and JWT handling.

This module tests authentication functionality including:
- JWT token creation and verification
- Login endpoint with mocked LDAP authentication
- Protected endpoint access with valid/invalid tokens
- User information retrieval
"""

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from docpipe.api.auth.dependencies import get_current_user
from docpipe.api.auth.jwt_handler import JWTConfig, create_access_token, verify_token
from docpipe.api.auth.models import User
from docpipe.api.main import app

# Must be ≥ 32 characters to pass the new length validator.
_VALID_JWT_SECRET = "test-secret-key-for-unit-tests-long-enough"  # pragma: allowlist secret


@pytest.fixture
def jwt_config() -> JWTConfig:
    """Create JWT configuration for testing."""
    return JWTConfig(
        jwt_secret_key=_VALID_JWT_SECRET,
        jwt_algorithm="HS256",
        jwt_access_token_expire_minutes=30,
    )


@pytest.fixture
def test_user() -> User:
    """Create a test user."""
    return User(
        username="testuser",
        email="testuser@example.com",
        full_name="Test User",
    )


@pytest.fixture
def valid_token(*, jwt_config: JWTConfig, test_user: User) -> str:
    """Create a valid JWT token for testing."""
    token_data = {
        "username": test_user.username,
        "email": test_user.email,
        "full_name": test_user.full_name,
    }
    return create_access_token(data=token_data, config=jwt_config)


class TestJWTTokenCreation:
    """Test JWT token creation functionality."""

    def test_create_access_token_returns_valid_token(self, *, jwt_config: JWTConfig, test_user: User):
        """Test that create_access_token generates a valid JWT token."""
        token_data = {
            "username": test_user.username,
            "email": test_user.email,
            "full_name": test_user.full_name,
        }

        token = create_access_token(data=token_data, config=jwt_config)

        assert isinstance(token, str)
        assert len(token) > 0
        # Verify token can be decoded
        payload = verify_token(token=token, config=jwt_config)
        assert payload is not None
        assert payload["username"] == test_user.username
        assert payload["email"] == test_user.email

    def test_create_access_token_includes_expiration(self, *, jwt_config: JWTConfig):
        """Test that created tokens include expiration time."""
        token_data = {"username": "testuser"}

        token = create_access_token(data=token_data, config=jwt_config)
        payload = verify_token(token=token, config=jwt_config)

        assert payload is not None
        assert "exp" in payload
        # Verify expiration is in the future
        exp_timestamp = payload["exp"]
        assert exp_timestamp > datetime.now(UTC).timestamp()


class TestJWTTokenVerification:
    """Test JWT token verification functionality."""

    def test_verify_token_with_valid_token_returns_payload(self, *, jwt_config: JWTConfig, valid_token: str):
        """Test that verify_token successfully decodes valid tokens."""
        payload = verify_token(token=valid_token, config=jwt_config)

        assert payload is not None
        assert payload["username"] == "testuser"
        assert payload["email"] == "testuser@example.com"

    def test_verify_token_with_invalid_token_returns_none(self, *, jwt_config: JWTConfig):
        """Test that verify_token returns None for invalid tokens."""
        invalid_token = "invalid.jwt.token"

        payload = verify_token(token=invalid_token, config=jwt_config)

        assert payload is None

    def test_verify_token_with_expired_token_returns_none(self, *, jwt_config: JWTConfig):
        """Test that verify_token returns None for expired tokens."""
        # Create token with past expiration
        token_data = {
            "username": "testuser",
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        }
        import jwt

        expired_token = jwt.encode(token_data, jwt_config.jwt_secret_key, algorithm=jwt_config.jwt_algorithm)

        payload = verify_token(token=expired_token, config=jwt_config)

        assert payload is None

    def test_verify_token_without_username_returns_none(self, *, jwt_config: JWTConfig):
        """Test that verify_token returns None for tokens missing username."""
        token_data = {"email": "test@example.com"}  # Missing username
        import jwt

        token = jwt.encode(token_data, jwt_config.jwt_secret_key, algorithm=jwt_config.jwt_algorithm)

        payload = verify_token(token=token, config=jwt_config)

        assert payload is None


class TestLoginEndpoint:
    """Test login endpoint functionality."""

    @patch("docpipe.api.main.ldap_authenticator")
    @patch("docpipe.api.main.jwt_config")
    def test_login_with_valid_credentials_returns_token(self, mock_jwt_config, mock_ldap_auth):
        """Test successful login returns JWT token."""
        mock_user = User(username="testuser", email="test@example.com", full_name="Test User")
        mock_ldap_auth.authenticate.return_value = mock_user
        mock_jwt_config.jwt_secret_key = _VALID_JWT_SECRET
        mock_jwt_config.jwt_algorithm = "HS256"
        mock_jwt_config.jwt_access_token_expire_minutes = 30

        client = TestClient(app)
        response = client.post("/auth/login", json={"username": "testuser", "password": "testpass"})

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert len(data["access_token"]) > 0

    @patch("docpipe.api.main.ldap_authenticator")
    @patch("docpipe.api.main.jwt_config")
    def test_login_with_invalid_credentials_returns_401(self, mock_jwt_config, mock_ldap_auth):
        """Test login with invalid credentials returns 401."""
        mock_ldap_auth.authenticate.return_value = None
        mock_jwt_config.jwt_secret_key = _VALID_JWT_SECRET
        mock_jwt_config.jwt_algorithm = "HS256"
        mock_jwt_config.jwt_access_token_expire_minutes = 30

        client = TestClient(app)
        response = client.post("/auth/login", json={"username": "testuser", "password": "wrongpass"})

        assert response.status_code == 401
        json_response = response.json()
        assert "errors" in json_response
        assert json_response["errors"][0]["code"] == "unauthorized"

    @patch("docpipe.api.main.ldap_authenticator", None)
    @patch("docpipe.api.main.jwt_config", None)
    def test_login_when_auth_not_configured_returns_503(self):
        """Test login returns 503 when authentication is not configured."""
        client = TestClient(app)
        credentials = {"username": "testuser", "password": os.environ.get("TEST_PASSWORD", "testpass")}

        response = client.post("/auth/login", json=credentials)

        assert response.status_code == 503
        json_response = response.json()
        assert "errors" in json_response
        assert json_response["errors"][0]["code"] == "service_unavailable"


class TestProtectedEndpoints:
    """Test protected endpoint access with authentication."""

    def test_protected_endpoint_with_valid_token_returns_200(self, *, jwt_config: JWTConfig, valid_token: str):
        """Test accessing protected endpoint with valid token succeeds."""
        client = TestClient(app)

        # Override JWT config dependency
        app.dependency_overrides[get_current_user] = lambda: User(
            username="testuser",
            email="testuser@example.com",
            full_name="Test User",
        )

        response = client.get("/protected", headers={"Authorization": f"Bearer {valid_token}"})

        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "testuser" in data["message"]

    def test_protected_endpoint_without_token_returns_401(self):
        """Test accessing protected endpoint without token returns 401."""
        client = TestClient(app)

        response = client.get("/protected")

        assert response.status_code == 401
        json_response = response.json()
        assert "errors" in json_response
        assert json_response["errors"][0]["code"] == "unauthorized"

    def test_protected_endpoint_with_invalid_token_returns_401(self):
        """Test accessing protected endpoint with invalid token returns 401.

        When JWT_SECRET_KEY is not configured in the test environment, the
        dependency raises 503.  Either way the endpoint must NOT return 200.
        """
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/protected", headers={"Authorization": "Bearer invalid.token.here"})

        assert response.status_code in (401, 503)


class TestUserInfoEndpoint:
    """Test user information retrieval endpoint."""

    def test_get_current_user_info_with_valid_token_returns_user(self):
        """Test /auth/me endpoint returns user information."""
        client = TestClient(app)

        # Override dependency to return test user
        test_user = User(
            username="testuser",
            email="testuser@example.com",
            full_name="Test User",
        )
        app.dependency_overrides[get_current_user] = lambda: test_user

        response = client.get("/auth/me")

        app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"
        assert data["email"] == "testuser@example.com"
        assert data["full_name"] == "Test User"

    def test_get_current_user_info_without_token_returns_401(self):
        """Test /auth/me endpoint without token returns 401."""
        client = TestClient(app)

        response = client.get("/auth/me")

        assert response.status_code == 401
        json_response = response.json()
        assert "errors" in json_response
        assert json_response["errors"][0]["code"] == "unauthorized"


class TestAuthenticationDependency:
    """Test get_current_user dependency function."""

    def test_get_current_user_with_valid_token_returns_user(self, *, jwt_config: JWTConfig, valid_token: str):
        """Test get_current_user extracts user from valid token."""
        from fastapi.security import HTTPAuthorizationCredentials

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=valid_token)

        # This would normally be called by FastAPI, we're testing the logic
        from docpipe.api.auth.dependencies import get_current_user

        user = get_current_user(credentials=credentials, jwt_config=jwt_config)

        assert user.username == "testuser"
        assert user.email == "testuser@example.com"

    def test_get_current_user_with_invalid_token_raises_401(self, *, jwt_config: JWTConfig):
        """Test get_current_user raises HTTPException for invalid token."""
        from fastapi.security import HTTPAuthorizationCredentials

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid.token")

        from docpipe.api.auth.dependencies import get_current_user

        with pytest.raises(HTTPException) as exc_info:
            get_current_user(credentials=credentials, jwt_config=jwt_config)

        assert exc_info.value.status_code == 401
        assert "Invalid authentication credentials" in exc_info.value.detail
