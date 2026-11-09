# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

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
from starlette.requests import Request

from docpipe.api.auth import dependencies
from docpipe.api.auth.config import DEFAULT_COOKIE_NAME
from docpipe.api.auth.dependencies import (
    LOCAL_PRINCIPAL_USERNAME,
    get_current_user,
    get_current_user_flexible,
    get_current_user_oauth2,
    get_jwt_config,
    get_session_jwt_config,
    require_session,
)
from docpipe.api.auth.jwt_handler import JWTConfig, create_access_token
from docpipe.api.auth.models import User
from docpipe.api.auth.roles import Role

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


def _request(*, cookie: str | None = None) -> Request:
    headers = [(b"cookie", f"{DEFAULT_COOKIE_NAME}={cookie}".encode())] if cookie else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers, "query_string": b""})


def _current_user(*, jwt_config, credentials=None, request=None) -> User:
    return get_current_user(
        request=request or _request(),
        credentials=credentials,
        jwt_config=jwt_config,
    )


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


@pytest.mark.usefixtures("auth_enabled")
class TestGetCurrentUser:
    def test_valid_token_returns_user_from_claims(self, *, jwt_config, alice_token):
        user = _current_user(credentials=_bearer(alice_token), jwt_config=jwt_config)

        assert user == User(**_ALICE)

    def test_optional_claims_default_to_empty_strings(self, jwt_config):
        token = create_access_token({"username": "bob"}, jwt_config)

        user = _current_user(credentials=_bearer(token), jwt_config=jwt_config)

        assert user == User(username="bob", email="", full_name="")

    def test_invalid_token_raises_401(self, jwt_config):
        with pytest.raises(HTTPException) as exc_info:
            _current_user(credentials=_bearer("not-a-jwt"), jwt_config=jwt_config)

        _assert_401(exc_info.value, detail="Invalid authentication credentials")

    def test_expired_token_raises_401(self, jwt_config):
        with pytest.raises(HTTPException) as exc_info:
            _current_user(credentials=_bearer(_expired_token(jwt_config)), jwt_config=jwt_config)

        _assert_401(exc_info.value, detail="Invalid authentication credentials")

    def test_token_signed_with_other_secret_raises_401(self, jwt_config):
        foreign = create_access_token(dict(_ALICE), JWTConfig(jwt_secret_key=_OTHER_SECRET))

        with pytest.raises(HTTPException) as exc_info:
            _current_user(credentials=_bearer(foreign), jwt_config=jwt_config)

        _assert_401(exc_info.value, detail="Invalid authentication credentials")

    def test_payload_without_username_raises_401(self, jwt_config):
        """Defence in depth: the dependency re-checks the claim even if verify_token lets it through."""
        with patch.object(dependencies, "verify_token", return_value={"email": "x@example.com"}):
            with pytest.raises(HTTPException) as exc_info:
                _current_user(credentials=_bearer("any"), jwt_config=jwt_config)

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

    @app.get("/session", dependencies=[Depends(require_session)])
    def session_only(request: Request):
        return {"auth_source": getattr(request.state, "auth_source", None)}

    @app.api_route("/mutate", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def mutate(user: Annotated[User, Depends(get_current_user)]):
        return {"username": user.username}

    @app.get("/source")
    def source(request: Request, user: Annotated[User, Depends(get_current_user)]):
        return {"auth_source": request.state.auth_source, "username": user.username}

    app.dependency_overrides[get_jwt_config] = lambda: jwt_config
    app.dependency_overrides[get_session_jwt_config] = lambda: jwt_config
    return app


@pytest.fixture
def client(app, auth_enabled) -> TestClient:
    return TestClient(app)


class TestBearerDependencyOverHttp:
    def test_valid_token_returns_200_with_user(self, *, client, alice_token):
        response = client.get("/me", headers={"Authorization": f"Bearer {alice_token}"})

        assert response.status_code == 200
        assert response.json() == {**_ALICE, "roles": ["viewer"]}

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

    def test_token_in_cookie_is_accepted(self, *, client, alice_token):
        client.cookies.set(DEFAULT_COOKIE_NAME, alice_token)

        response = client.get("/me")

        assert response.status_code == 200
        assert response.json()["username"] == "alice"

    def test_cookie_with_another_name_is_ignored(self, *, client, alice_token):
        client.cookies.set("access_token", alice_token)

        response = client.get("/me")

        assert response.status_code == 401

    def test_bearer_wins_over_cookie_for_another_user(self, *, client, jwt_config, alice_token):
        bob_token = create_access_token({"username": "bob"}, jwt_config)
        client.cookies.set(DEFAULT_COOKIE_NAME, bob_token)

        response = client.get("/me", headers={"Authorization": f"Bearer {alice_token}"})

        assert response.status_code == 200
        assert response.json()["username"] == "alice"

    def test_invalid_bearer_is_not_rescued_by_valid_cookie(self, *, client, alice_token):
        client.cookies.set(DEFAULT_COOKIE_NAME, alice_token)

        response = client.get("/me", headers={"Authorization": "Bearer garbage"})

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
        ],
    )
    def test_bad_cookie_tokens_return_401(self, *, client, jwt_config, token_factory):
        client.cookies.set(DEFAULT_COOKIE_NAME, token_factory(jwt_config))

        response = client.get("/me")

        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid authentication credentials"}
        assert response.headers["www-authenticate"] == "Bearer"

    def test_custom_cookie_name_is_honoured(self, *, client, monkeypatch, alice_token):
        monkeypatch.setenv("DOCPIPE_AUTH_COOKIE_NAME", "custom_session")
        client.cookies.set("custom_session", alice_token)

        assert client.get("/me").status_code == 200

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

    @pytest.mark.usefixtures("no_jwt_env", "auth_enabled")
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

        assert response.json() == {"user": {**_ALICE, "roles": ["viewer"]}}

    def test_invalid_token_is_treated_as_anonymous(self, client):
        response = client.get("/maybe-me", headers={"Authorization": "Bearer garbage"})

        assert response.status_code == 200
        assert response.json() == {"user": None}


class TestFlexibleDependencyOverHttp:
    def test_valid_token_returns_user(self, *, client, alice_token):
        response = client.get("/flexible-me", headers={"Authorization": f"Bearer {alice_token}"})

        assert response.status_code == 200
        assert response.json() == {**_ALICE, "roles": ["viewer"]}

    def test_invalid_token_returns_401(self, client):
        response = client.get("/flexible-me", headers={"Authorization": "Bearer garbage"})

        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"

    def test_missing_header_falls_through_to_the_final_401(self, client):
        """``security = HTTPBearer(auto_error=False)`` no longer rejects in the scheme, so the
        dependency reaches its own 401 after both token sources turn up empty."""
        response = client.get("/flexible-me")

        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid authentication credentials"}


# ---------------------------------------------------------------------------
# Session source, local principal and require_session
# ---------------------------------------------------------------------------


class TestAuthSource:
    def test_bearer_request_records_bearer(self, *, client, alice_token):
        response = client.get("/source", headers={"Authorization": f"Bearer {alice_token}"})

        assert response.json() == {"auth_source": "bearer", "username": "alice"}

    def test_cookie_request_records_cookie(self, *, client, alice_token):
        client.cookies.set(DEFAULT_COOKIE_NAME, alice_token)

        response = client.get("/source")

        assert response.json() == {"auth_source": "cookie", "username": "alice"}

    def test_bearer_wins_and_is_recorded_as_bearer(self, *, client, jwt_config, alice_token):
        client.cookies.set(DEFAULT_COOKIE_NAME, create_access_token({"username": "bob"}, jwt_config))

        response = client.get("/source", headers={"Authorization": f"Bearer {alice_token}"})

        assert response.json() == {"auth_source": "bearer", "username": "alice"}

    def test_disabled_auth_records_disabled(self, *, app):
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("DOCPIPE_AUTH_ENABLED", "false")
            response = TestClient(app).get("/source")

        assert response.json() == {"auth_source": "disabled", "username": LOCAL_PRINCIPAL_USERNAME}


class TestRequireSession:
    def test_rejects_anonymous_request(self, client):
        response = client.get("/session")

        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"

    def test_accepts_bearer_and_cookie(self, *, client, alice_token):
        assert client.get("/session", headers={"Authorization": f"Bearer {alice_token}"}).json() == {
            "auth_source": "bearer"
        }
        client.cookies.set(DEFAULT_COOKIE_NAME, alice_token)
        assert client.get("/session").json() == {"auth_source": "cookie"}

    def test_delegates_to_get_current_user_overrides(self, *, app, client):
        app.dependency_overrides[get_current_user] = lambda: User(username="override")

        response = client.get("/session")

        assert response.status_code == 200

    def test_returns_the_user_from_get_current_user(self):
        user = User(username="alice")

        assert require_session(user) is user


class TestLocalPrincipal:
    def test_disabled_auth_returns_admin_local_principal_without_credentials(self):
        user = _current_user(jwt_config=None)

        assert user.username == LOCAL_PRINCIPAL_USERNAME
        assert user.roles == [Role.ADMIN]

    def test_disabled_auth_ignores_presented_credentials(self, *, jwt_config, alice_token):
        user = _current_user(credentials=_bearer(alice_token), jwt_config=jwt_config)

        assert user.username == LOCAL_PRINCIPAL_USERNAME

    def test_disabled_auth_needs_no_jwt_secret(self, *, no_jwt_env):
        assert get_session_jwt_config() is None

    @pytest.mark.usefixtures("auth_enabled")
    def test_enabled_auth_requires_jwt_secret(self, *, no_jwt_env):
        with pytest.raises(HTTPException) as exc_info:
            get_session_jwt_config()

        assert exc_info.value.status_code == 503

    @pytest.mark.usefixtures("auth_enabled")
    def test_reserved_username_in_token_is_rejected(self, *, jwt_config):
        token = create_access_token({"username": LOCAL_PRINCIPAL_USERNAME}, jwt_config)

        with pytest.raises(HTTPException) as exc_info:
            _current_user(credentials=_bearer(token), jwt_config=jwt_config)

        _assert_401(exc_info.value, detail="Invalid authentication credentials")

    @pytest.mark.usefixtures("auth_enabled")
    def test_roles_claim_is_parsed(self, *, jwt_config):
        token = create_access_token({"username": "ed", "roles": ["editor"]}, jwt_config)

        user = _current_user(credentials=_bearer(token), jwt_config=jwt_config)

        assert user.roles == [Role.EDITOR]


# ---------------------------------------------------------------------------
# CSRF defence for cookie sessions
# ---------------------------------------------------------------------------

_UNSAFE_METHODS = ["POST", "PUT", "PATCH", "DELETE"]


class TestCsrfHeader:
    @pytest.mark.parametrize("method", _UNSAFE_METHODS)
    def test_cookie_mutation_without_header_is_rejected(self, *, client, alice_token, method):
        client.cookies.set(DEFAULT_COOKIE_NAME, alice_token)

        response = client.request(method, "/mutate")

        assert response.status_code == 403
        assert "X-Requested-With" in response.json()["detail"]

    @pytest.mark.parametrize("method", _UNSAFE_METHODS)
    @pytest.mark.parametrize("value", ["", "   "])
    def test_cookie_mutation_with_empty_header_is_rejected(self, *, client, alice_token, method, value):
        client.cookies.set(DEFAULT_COOKIE_NAME, alice_token)

        response = client.request(method, "/mutate", headers={"X-Requested-With": value})

        assert response.status_code == 403

    @pytest.mark.parametrize("method", _UNSAFE_METHODS)
    def test_cookie_mutation_with_header_is_accepted(self, *, client, alice_token, method):
        client.cookies.set(DEFAULT_COOKIE_NAME, alice_token)

        response = client.request(method, "/mutate", headers={"X-Requested-With": "XMLHttpRequest"})

        assert response.status_code == 200
        assert response.json() == {"username": "alice"}

    def test_cookie_read_needs_no_header(self, *, client, alice_token):
        client.cookies.set(DEFAULT_COOKIE_NAME, alice_token)

        response = client.get("/mutate")

        assert response.status_code == 200

    @pytest.mark.parametrize("method", _UNSAFE_METHODS)
    def test_bearer_mutation_is_exempt(self, *, client, alice_token, method):
        response = client.request(method, "/mutate", headers={"Authorization": f"Bearer {alice_token}"})

        assert response.status_code == 200

    @pytest.mark.parametrize("method", _UNSAFE_METHODS)
    def test_bearer_wins_over_cookie_for_another_user_and_is_exempt(self, *, client, jwt_config, alice_token, method):
        client.cookies.set(DEFAULT_COOKIE_NAME, create_access_token({"username": "bob"}, jwt_config))

        response = client.request(method, "/mutate", headers={"Authorization": f"Bearer {alice_token}"})

        assert response.status_code == 200
        assert response.json() == {"username": "alice"}

    def test_invalid_cookie_is_401_not_403(self, *, client):
        client.cookies.set(DEFAULT_COOKIE_NAME, "garbage")

        assert client.post("/mutate").status_code == 401

    @pytest.mark.parametrize("method", _UNSAFE_METHODS)
    def test_auth_disabled_needs_no_header(self, *, app, method):
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("DOCPIPE_AUTH_ENABLED", "false")
            response = TestClient(app).request(method, "/mutate")

        assert response.status_code == 200
