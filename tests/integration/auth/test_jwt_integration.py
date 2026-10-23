"""Integration tests for JWT authentication."""

from datetime import UTC

import pytest
from fastapi.testclient import TestClient

from docpipe.api.auth.jwt_handler import (
    JWTConfig,
    create_access_token,
)
from docpipe.api.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def jwt_config():
    """Create JWT configuration for testing."""
    return JWTConfig(jwt_secret_key="test-secret-key-for-integration-tests")


class TestJWTAuthentication:
    """Test JWT authentication integration."""

    def test_access_protected_endpoint_with_valid_token(self, client, jwt_config):
        """Test accessing protected endpoint with valid JWT token."""
        token_data = {
            "username": "testuser",
            "email": "test@example.com",
            "full_name": "Test User",
        }
        token = create_access_token(token_data, jwt_config)

        response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"
        assert data["email"] == "test@example.com"
        assert data["full_name"] == "Test User"

    def test_access_protected_endpoint_without_token(self, client):
        """Test accessing protected endpoint without token."""
        response = client.get("/auth/me")

        assert response.status_code == 403  # Forbidden or 401 Unauthorized

    def test_access_protected_endpoint_with_invalid_token(self, client):
        """Test accessing protected endpoint with invalid token."""
        response = client.get("/auth/me", headers={"Authorization": "Bearer invalid-token"})

        assert response.status_code == 401

    def test_access_protected_endpoint_with_malformed_header(self, client):
        """Test accessing protected endpoint with malformed auth header."""
        response = client.get("/auth/me", headers={"Authorization": "InvalidFormat token"})

        assert response.status_code in [401, 403]

    def test_protected_route_with_valid_token(self, client, jwt_config):
        """Test protected route with valid token."""
        token_data = {"username": "testuser"}
        token = create_access_token(token_data, jwt_config)

        response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        assert "testuser" in response.json()["message"]

    def test_token_with_missing_username_claim(self, client, jwt_config):
        """Test token without username claim is rejected."""
        from datetime import datetime, timedelta

        import jwt

        # Create token without username
        data: dict[str, object] = {"email": "test@example.com"}
        expire = datetime.now(UTC) + timedelta(minutes=30)
        data.update({"exp": expire})

        token = jwt.encode(data, jwt_config.jwt_secret_key, algorithm=jwt_config.jwt_algorithm)

        response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401

    def test_expired_token(self, client, jwt_config):
        """Test expired token is rejected."""
        from datetime import datetime, timedelta

        import jwt

        # Create expired token
        data: dict[str, object] = {"username": "testuser"}
        expire = datetime.now(UTC) - timedelta(minutes=1)
        data.update({"exp": expire})

        token = jwt.encode(data, jwt_config.jwt_secret_key, algorithm=jwt_config.jwt_algorithm)

        response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401


class TestMultipleTokens:
    """Test handling multiple tokens."""

    def test_different_users_different_tokens(self, client, jwt_config):
        """Test that different users get different tokens."""
        user1_data = {"username": "user1"}
        user2_data = {"username": "user2"}

        token1 = create_access_token(user1_data, jwt_config)
        token2 = create_access_token(user2_data, jwt_config)

        assert token1 != token2

        # Verify each token returns correct user
        response1 = client.get("/auth/me", headers={"Authorization": f"Bearer {token1}"})
        response2 = client.get("/auth/me", headers={"Authorization": f"Bearer {token2}"})

        assert response1.json()["username"] == "user1"
        assert response2.json()["username"] == "user2"

    def test_token_reuse(self, client, jwt_config):
        """Test that tokens can be reused multiple times."""
        token_data = {"username": "testuser"}
        token = create_access_token(token_data, jwt_config)

        # Use token multiple times
        for _ in range(3):
            response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 200
            assert response.json()["username"] == "testuser"


class TestTokenWithDifferentData:
    """Test tokens with various data payloads."""

    def test_token_with_minimal_data(self, client, jwt_config):
        """Test token with only username."""
        token_data = {"username": "testuser"}
        token = create_access_token(token_data, jwt_config)

        response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"
        assert data["email"] == ""
        assert data["full_name"] == ""

    def test_token_with_full_data(self, client, jwt_config):
        """Test token with all user data."""
        token_data = {
            "username": "testuser",
            "email": "test@example.com",
            "full_name": "Test User",
        }
        token = create_access_token(token_data, jwt_config)

        response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"
        assert data["email"] == "test@example.com"
        assert data["full_name"] == "Test User"

    def test_token_with_extra_claims(self, client, jwt_config):
        """Test token with extra custom claims."""
        token_data = {
            "username": "testuser",
            "email": "test@example.com",
            "custom_field": "custom_value",
        }
        token = create_access_token(token_data, jwt_config)

        response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        # Custom fields should be preserved in token but not in User model
        assert response.json()["username"] == "testuser"
