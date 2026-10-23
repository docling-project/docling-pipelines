"""Unit tests for FastAPI authentication dependencies.

Covers the dependency functions both when called directly (to pin down each
branch) and when wired into a minimal FastAPI app (to verify the HTTP contract:
status codes, ``WWW-Authenticate`` header, and how the security schemes extract
the bearer token).
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from unittest.mock import patch

import jwt
import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from docpipe.api.auth import dependencies
from docpipe.api.auth.dependencies import (
    get_current_user,
    get_current_user_flexible,
    get_current_user_oauth2,
    get_jwt_config,
)
from docpipe.api.auth.jwt_handler import JWTConfig, create_access_token
from docpipe.api.auth.models import User

_SECRET = "dependencies-test-secret-key-long-enough"  # pragma: allowlist secret
_OTHER_SECRET = "a-completely-different-secret-key-value"  # pragma: allowlist secret
_ALICE = {"username": "alice", "email": "alice@example.com", "full_name": "Alice Example"}


@pytest.fixture
def jwt_config() -> JWTConfig:
    return JWTConfig(jwt_secret_key=_SECRET, jwt_algorithm="HS256", jwt_access_token_expire_minutes=5)


@pytest.fixture
def alice_token(jwt_config: JWTConfig) -> str:
    return create_access_token(dict(_ALICE), jwt_config)


@pytest.fixture
def no_jwt_env(monkeypatch, tmp_path):
    """Ensure no JWT secret is available from the environment or a .env file."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _expired_token(jwt_config: JWTConfig) -> str:
    expired = datetime.now(UTC) - timedelta(minutes=1)
    return jwt.encode({**_ALICE, "exp": expired}, jwt_config.jwt_secret_key, algorithm=jwt_config.jwt_algorithm)


def _assert_401(exc: HTTPException, *, detail: str) -> None:
    assert exc.status_code == 401
    assert exc.detail == detail
    assert exc.headers == {"WWW-Authenticate": "Bearer"}


# ---------------------------------------------------------------------------
# get_jwt_config
# ---------------------------------------------------------------------------


class TestGetJwtConfig:
    def test_returns_config_from_environment(self, *, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("JWT_SECRET_KEY", _SECRET)
        monkeypatch.setenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "7")

        config = get_jwt_config()

        assert config.jwt_secret_key == _SECRET
        assert config.jwt_access_token_expire_minutes == 7

    @pytest.mark.usefixtures("no_jwt_env")
    def test_missing_secret_raises_503(self):
        with pytest.raises(HTTPException) as exc_info:
            get_jwt_config()

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail == "Authentication service not configured"

    def test_weak_secret_raises_503_without_leaking_details(self, *, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("JWT_SECRET_KEY", "too-short")  # pragma: allowlist secret

        with pytest.raises(HTTPException) as exc_info:
            get_jwt_config()

        assert exc_info.value.status_code == 503
        assert "too-short" not in str(exc_info.value.detail)


# ---------------------------------------------------------------------------
# get_current_user (direct calls)
# ---------------------------------------------------------------------------


class TestGetCurrentUser:
    def test_valid_token_returns_user_from_claims(self, *, jwt_config, alice_token):
        user = get_current_user(_bearer(alice_token), jwt_config)

        assert user == User(**_ALICE)

    def test_optional_claims_default_to_empty_strings(self, jwt_config):
        token = create_access_token({"username": "bob"}, jwt_config)

        user = get_current_user(_bearer(token), jwt_config)

        assert user == User(username="bob", email="", full_name="")

    def test_invalid_token_raises_401(self, jwt_config):
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(_bearer("not-a-jwt"), jwt_config)

        _assert_401(exc_info.value, detail="Invalid authentication credentials")

    def test_expired_token_raises_401(self, jwt_config):
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(_bearer(_expired_token(jwt_config)), jwt_config)

        _assert_401(exc_info.value, detail="Invalid authentication credentials")

    def test_token_signed_with_other_secret_raises_401(self, jwt_config):
        foreign = create_access_token(dict(_ALICE), JWTConfig(jwt_secret_key=_OTHER_SECRET))

        with pytest.raises(HTTPException) as exc_info:
            get_current_user(_bearer(foreign), jwt_config)

        _assert_401(exc_info.value, detail="Invalid authentication credentials")

    def test_payload_without_username_raises_401(self, jwt_config):
        """Defence in depth: the dependency re-checks the claim even if verify_token lets it through."""
        with patch.object(dependencies, "verify_token", return_value={"email": "x@example.com"}):
            with pytest.raises(HTTPException) as exc_info:
                get_current_user(_bearer("any"), jwt_config)

        _assert_401(exc_info.value, detail="Invalid token payload")


# ---------------------------------------------------------------------------
# get_current_user_oauth2 (direct calls)
# ---------------------------------------------------------------------------


class TestGetCurrentUserOAuth2:
    @pytest.mark.parametrize("token", [None, ""])
    def test_missing_token_returns_none(self, *, jwt_config, token):
        assert get_current_user_oauth2(token, jwt_config) is None

    def test_valid_token_returns_user(self, *, jwt_config, alice_token):
        assert get_current_user_oauth2(alice_token, jwt_config) == User(**_ALICE)

    def test_invalid_token_returns_none(self, jwt_config):
        assert get_current_user_oauth2("garbage", jwt_config) is None

    def test_expired_token_returns_none(self, jwt_config):
        assert get_current_user_oauth2(_expired_token(jwt_config), jwt_config) is None

    def test_payload_without_username_returns_none(self, jwt_config):
        with patch.object(dependencies, "verify_token", return_value={"email": "x@example.com"}):
            assert get_current_user_oauth2("any", jwt_config) is None


# ---------------------------------------------------------------------------
# get_current_user_flexible (direct calls)
# ---------------------------------------------------------------------------


class TestGetCurrentUserFlexible:
    def test_valid_bearer_credentials_win(self, *, jwt_config, alice_token):
        other = create_access_token({"username": "bob"}, jwt_config)

        user = get_current_user_flexible(_bearer(alice_token), other, jwt_config)

        assert user.username == "alice"

    def test_falls_back_to_oauth2_token_when_bearer_invalid(self, *, jwt_config, alice_token):
        user = get_current_user_flexible(_bearer("garbage"), alice_token, jwt_config)

        assert user == User(**_ALICE)

    def test_uses_oauth2_token_when_no_bearer_credentials(self, *, jwt_config, alice_token):
        user = get_current_user_flexible(None, alice_token, jwt_config)

        assert user == User(**_ALICE)

    def test_no_tokens_raises_401(self, jwt_config):
        with pytest.raises(HTTPException) as exc_info:
            get_current_user_flexible(None, None, jwt_config)

        _assert_401(exc_info.value, detail="Invalid authentication credentials")

    def test_both_tokens_invalid_raises_401(self, jwt_config):
        with pytest.raises(HTTPException) as exc_info:
            get_current_user_flexible(_bearer("garbage"), _expired_token(jwt_config), jwt_config)

        _assert_401(exc_info.value, detail="Invalid authentication credentials")

    def test_payloads_without_username_raise_401(self, jwt_config):
        with patch.object(dependencies, "verify_token", return_value={"email": "x@example.com"}):
            with pytest.raises(HTTPException) as exc_info:
                get_current_user_flexible(_bearer("a"), "b", jwt_config)

        _assert_401(exc_info.value, detail="Invalid authentication credentials")


# ---------------------------------------------------------------------------
# HTTP contract through a minimal FastAPI app
# ---------------------------------------------------------------------------


@pytest.fixture
def app(jwt_config) -> FastAPI:
    app = FastAPI()

    @app.get("/me")
    def me(user: Annotated[User, Depends(get_current_user)]):
        return user

    @app.get("/maybe-me")
    def maybe_me(user: Annotated[User | None, Depends(get_current_user_oauth2)]):
        return {"user": user}

    @app.get("/flexible-me")
    def flexible_me(user: Annotated[User, Depends(get_current_user_flexible)]):
        return user

    app.dependency_overrides[get_jwt_config] = lambda: jwt_config
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


class TestBearerDependencyOverHttp:
    def test_valid_token_returns_200_with_user(self, *, client, alice_token):
        response = client.get("/me", headers={"Authorization": f"Bearer {alice_token}"})

        assert response.status_code == 200
        assert response.json() == _ALICE

    def test_scheme_is_case_insensitive(self, *, client, alice_token):
        response = client.get("/me", headers={"Authorization": f"bearer {alice_token}"})

        assert response.status_code == 200

    def test_missing_authorization_header_returns_401(self, client):
        response = client.get("/me")

        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"

    def test_non_bearer_scheme_returns_401(self, client):
        response = client.get("/me", headers={"Authorization": "Basic YWxpY2U6c2VjcmV0"})

        assert response.status_code == 401

    def test_token_in_cookie_is_not_accepted(self, *, client, alice_token):
        """Only the Authorization header is honoured; cookies carry no authentication."""
        client.cookies.set("access_token", alice_token)

        response = client.get("/me")

        assert response.status_code == 401

    @pytest.mark.parametrize(
        "token_factory",
        [
            pytest.param(lambda cfg: "garbage", id="malformed"),
            pytest.param(_expired_token, id="expired"),
            pytest.param(
                lambda cfg: create_access_token(dict(_ALICE), JWTConfig(jwt_secret_key=_OTHER_SECRET)),
                id="foreign_signature",
            ),
            pytest.param(
                lambda cfg: create_access_token(dict(_ALICE), cfg)[:-4] + "AAAA",
                id="tampered_signature",
            ),
            pytest.param(
                lambda cfg: jwt.encode({"username": "alice"}, cfg.jwt_secret_key, algorithm=cfg.jwt_algorithm),
                id="no_exp",
            ),
        ],
    )
    def test_bad_tokens_return_401_with_www_authenticate(self, *, client, jwt_config, token_factory):
        response = client.get("/me", headers={"Authorization": f"Bearer {token_factory(jwt_config)}"})

        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid authentication credentials"}
        assert response.headers["www-authenticate"] == "Bearer"

    @pytest.mark.usefixtures("no_jwt_env")
    def test_unconfigured_jwt_returns_503(self, *, app, alice_token):
        app.dependency_overrides.clear()

        response = TestClient(app).get("/me", headers={"Authorization": f"Bearer {alice_token}"})

        assert response.status_code == 503
        assert response.json() == {"detail": "Authentication service not configured"}


class TestOptionalOAuth2DependencyOverHttp:
    def test_anonymous_request_gets_none(self, client):
        response = client.get("/maybe-me")

        assert response.status_code == 200
        assert response.json() == {"user": None}

    def test_valid_token_resolves_user(self, *, client, alice_token):
        response = client.get("/maybe-me", headers={"Authorization": f"Bearer {alice_token}"})

        assert response.json() == {"user": _ALICE}

    def test_invalid_token_is_treated_as_anonymous(self, client):
        response = client.get("/maybe-me", headers={"Authorization": "Bearer garbage"})

        assert response.status_code == 200
        assert response.json() == {"user": None}


class TestFlexibleDependencyOverHttp:
    def test_valid_token_returns_user(self, *, client, alice_token):
        response = client.get("/flexible-me", headers={"Authorization": f"Bearer {alice_token}"})

        assert response.status_code == 200
        assert response.json() == _ALICE

    def test_invalid_token_returns_401(self, client):
        response = client.get("/flexible-me", headers={"Authorization": "Bearer garbage"})

        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"

    def test_missing_header_is_rejected_by_http_bearer_scheme(self, client):
        """``security = HTTPBearer()`` uses ``auto_error=True``, so the scheme itself
        rejects a request without credentials before the OAuth2 fallback is reached."""
        response = client.get("/flexible-me")

        assert response.status_code == 401
        assert response.json() == {"detail": "Not authenticated"}
