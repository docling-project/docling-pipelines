# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Route tests for login, logout, auth config and the current-user lookup."""

from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

from docpipe.api.auth.jwt_handler import JWTConfig, create_access_token
from docpipe.api.auth.models import User
from docpipe.api.auth.roles import Role
from docpipe.api.main import app
from docpipe.api.middleware import rate_limit

_SECRET = "route-test-secret-key-that-is-long-enough"  # pragma: allowlist secret
_USER_PASSWORD = "route-test-password"  # pragma: allowlist secret
_COOKIE = "docpipe_access_token"


@pytest.fixture(autouse=True)
def _reset_throttle():
    rate_limit.reset_all_state()
    yield
    rate_limit.reset_all_state()


@pytest.fixture
def jwt_config() -> JWTConfig:
    return JWTConfig(jwt_secret_key=_SECRET)


@pytest.fixture
def ldap_user() -> User:
    return User(username="alice", email="alice@example.com", full_name="Alice", roles=[Role.EDITOR])


@pytest.fixture
def client(jwt_config, ldap_user, monkeypatch):
    """Client with a mocked LDAP authenticator that accepts alice only."""
    authenticator = MagicMock()
    authenticator.authenticate.side_effect = lambda *, username, password: (
        ldap_user if (username, password) == ("alice", _USER_PASSWORD) else None
    )
    for name in ("DOCPIPE_TRUST_PROXY_HEADERS", "DOCPIPE_AUTH_COOKIE_SECURE", "DOCPIPE_AUTH_COOKIE_NAME"):
        monkeypatch.delenv(name, raising=False)
    with (
        patch("docpipe.api.main.ldap_authenticator", authenticator),
        patch("docpipe.api.main.bootstrap_authenticator", None),
        patch("docpipe.api.main.jwt_config", jwt_config),
    ):
        yield TestClient(app)


def _login(client: TestClient, *, password: str = _USER_PASSWORD, **kwargs):
    return client.post("/auth/login", json={"username": "alice", "password": password}, **kwargs)


class TestLogin:
    def test_success_returns_token_user_roles_and_sets_cookie(self, client, jwt_config):
        response = _login(client)

        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["user"] == {
            "username": "alice",
            "email": "alice@example.com",
            "full_name": "Alice",
            "roles": ["editor"],
        }
        claims = jwt.decode(body["access_token"], _SECRET, algorithms=["HS256"])
        assert claims["roles"] == ["editor"]
        assert response.cookies.get(_COOKIE) == body["access_token"]

    def test_cookie_flags(self, client):
        header = _login(client).headers["set-cookie"].lower()

        assert "httponly" in header
        assert "samesite=lax" in header
        assert "path=/" in header
        assert "max-age=1800" in header
        assert "secure" not in header

    @pytest.mark.parametrize(
        ("setup", "expect_secure"),
        [
            pytest.param("https_url", True, id="https_scheme"),
            pytest.param("forwarded_trusted", True, id="forwarded_proto_with_trust"),
            pytest.param("forwarded_untrusted", False, id="forwarded_proto_without_trust"),
            pytest.param("forwarded_trusted_http", False, id="forwarded_proto_http"),
            pytest.param("forced", True, id="cookie_secure_override"),
        ],
    )
    def test_secure_flag(self, client, monkeypatch, setup, expect_secure):
        kwargs: dict = {}
        if setup == "https_url":
            client = TestClient(app, base_url="https://testserver")
        elif setup in {"forwarded_trusted", "forwarded_untrusted", "forwarded_trusted_http"}:
            if setup != "forwarded_untrusted":
                monkeypatch.setenv("DOCPIPE_TRUST_PROXY_HEADERS", "true")
            kwargs["headers"] = {"X-Forwarded-Proto": "http" if setup.endswith("_http") else "https"}
        elif setup == "forced":
            monkeypatch.setenv("DOCPIPE_AUTH_COOKIE_SECURE", "true")

        header = _login(client, **kwargs).headers["set-cookie"].lower()

        assert ("; secure" in header) is expect_secure

    def test_custom_cookie_name(self, client, monkeypatch):
        monkeypatch.setenv("DOCPIPE_AUTH_COOKIE_NAME", "custom_session")

        response = _login(client)

        assert response.cookies.get("custom_session") == response.json()["access_token"]

    def test_wrong_password_returns_generic_401_without_cookie(self, client):
        response = _login(client, password="wrong")  # pragma: allowlist secret

        assert response.status_code == 401
        assert response.json()["errors"][0]["message"] == "Invalid credentials"
        assert "set-cookie" not in response.headers

    def test_unknown_user_and_wrong_password_look_identical(self, client):
        unknown = client.post("/auth/login", json={"username": "nobody", "password": "x"})  # pragma: allowlist secret
        wrong = _login(client, password="x")  # pragma: allowlist secret

        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json()["errors"][0]["message"] == wrong.json()["errors"][0]["message"]

    def test_no_login_method_configured_returns_503(self, jwt_config):
        with (
            patch("docpipe.api.main.ldap_authenticator", None),
            patch("docpipe.api.main.bootstrap_authenticator", None),
            patch("docpipe.api.main.jwt_config", jwt_config),
        ):
            response = TestClient(app).post("/auth/login", json={"username": "a", "password": "b"})

        assert response.status_code == 503
        assert "set-cookie" not in response.headers

    def test_missing_jwt_configuration_returns_503(self):
        with (
            patch("docpipe.api.main.ldap_authenticator", MagicMock()),
            patch("docpipe.api.main.jwt_config", None),
        ):
            response = TestClient(app).post("/auth/login", json={"username": "a", "password": "b"})

        assert response.status_code == 503

    def test_issued_token_authenticates_as_bearer_and_cookie(self, client, monkeypatch):
        monkeypatch.setenv("DOCPIPE_AUTH_ENABLED", "true")
        monkeypatch.setenv("JWT_SECRET_KEY", _SECRET)
        token = _login(client).json()["access_token"]

        by_bearer = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        by_cookie = TestClient(app, cookies={_COOKIE: token}).get("/auth/me")

        assert by_bearer.json()["roles"] == by_cookie.json()["roles"] == ["editor"]


class TestLogout:
    def test_clears_cookie_for_authenticated_browser(self, client, monkeypatch):
        monkeypatch.setenv("DOCPIPE_AUTH_ENABLED", "true")
        monkeypatch.setenv("JWT_SECRET_KEY", _SECRET)
        token = _login(client).json()["access_token"]

        response = client.post("/auth/logout", headers={"X-Requested-With": "XMLHttpRequest"})

        assert response.status_code == 200
        header = response.headers["set-cookie"].lower()
        assert f"{_COOKIE}=" in header
        assert "max-age=0" in header
        assert "path=/" in header
        assert token not in header

    def test_succeeds_with_expired_cookie(self, client, jwt_config, monkeypatch):
        monkeypatch.setenv("DOCPIPE_AUTH_ENABLED", "true")
        monkeypatch.setenv("JWT_SECRET_KEY", _SECRET)
        expired = jwt.encode({"username": "alice", "exp": 1}, _SECRET, algorithm="HS256")

        response = TestClient(app, cookies={_COOKIE: expired}).post("/auth/logout")

        assert response.status_code == 200
        assert "max-age=0" in response.headers["set-cookie"].lower()

    def test_succeeds_without_any_session_when_auth_is_enabled(self, client, monkeypatch):
        monkeypatch.setenv("DOCPIPE_AUTH_ENABLED", "true")

        response = client.post("/auth/logout")

        assert response.status_code == 200
        assert "max-age=0" in response.headers["set-cookie"].lower()

    def test_secure_flag_follows_the_same_rules(self, client, monkeypatch):
        monkeypatch.setenv("DOCPIPE_AUTH_COOKIE_SECURE", "true")

        assert "; secure" in client.post("/auth/logout").headers["set-cookie"].lower()


class TestAuthConfig:
    def test_is_public_and_reports_credential_login(self, client, monkeypatch):
        monkeypatch.setenv("DOCPIPE_AUTH_ENABLED", "true")

        response = client.get("/auth/config")

        assert response.status_code == 200
        assert response.json() == {"auth_enabled": True, "credential_login": True, "providers": []}

    def test_reports_no_credential_login_without_authenticators(self, jwt_config):
        with (
            patch("docpipe.api.main.ldap_authenticator", None),
            patch("docpipe.api.main.bootstrap_authenticator", None),
            patch("docpipe.api.main.jwt_config", jwt_config),
        ):
            body = TestClient(app).get("/auth/config").json()

        assert body["credential_login"] is False

    def test_reports_auth_disabled(self, client):
        assert client.get("/auth/config").json()["auth_enabled"] is False

    def test_provider_entries_carry_only_public_fields_and_no_secrets(self, client, monkeypatch):
        monkeypatch.setenv("OAUTH2_ENABLED", "true")
        monkeypatch.setenv("OAUTH2_PROVIDER", "generic")
        monkeypatch.setenv("OAUTH2_CLIENT_ID", "client-id-value")
        monkeypatch.setenv("OAUTH2_CLIENT_SECRET", "client-secret-value")  # pragma: allowlist secret
        monkeypatch.setenv("OAUTH2_AUTHORIZATION_ENDPOINT", "https://idp.example.com/authorize")
        monkeypatch.setenv("AZURE_TENANT_ID", "tenant-id-value")

        response = client.get("/auth/config")

        providers = response.json()["providers"]
        assert providers
        for provider in providers:
            assert set(provider) == {"name", "display_name", "authorize_url"}
        text = response.text
        for forbidden in ("client-id-value", "client-secret-value", "tenant-id-value", "idp.example.com"):
            assert forbidden not in text

    def test_body_exposes_only_the_documented_top_level_keys(self, client):
        assert set(client.get("/auth/config").json()) == {"auth_enabled", "credential_login", "providers"}


class TestMe:
    def test_includes_roles(self, client, jwt_config, monkeypatch):
        monkeypatch.setenv("DOCPIPE_AUTH_ENABLED", "true")
        monkeypatch.setenv("JWT_SECRET_KEY", _SECRET)
        token = create_access_token({"username": "bob", "email": "b@x.org", "roles": ["admin"]}, jwt_config)

        response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        assert response.json() == {"username": "bob", "email": "b@x.org", "full_name": "", "roles": ["admin"]}

    def test_requires_a_session_when_auth_is_enabled(self, client, monkeypatch):
        monkeypatch.setenv("DOCPIPE_AUTH_ENABLED", "true")
        monkeypatch.setenv("JWT_SECRET_KEY", _SECRET)

        assert client.get("/auth/me").status_code == 401


class TestCors:
    def test_preflight_does_not_allow_credentials(self, client):
        response = client.options(
            "/auth/login",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
        )

        assert response.status_code == 200
        assert response.headers.get("access-control-allow-credentials") != "true"

    def test_actual_response_does_not_allow_credentials(self, client):
        response = _login(client, headers={"Origin": "http://localhost:3000"})

        assert response.headers.get("access-control-allow-credentials") != "true"
