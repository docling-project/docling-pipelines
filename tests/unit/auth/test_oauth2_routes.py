# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for OAuth2 route helpers and security fixes."""

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from docpipe.api.auth import oauth2_routes
from docpipe.api.auth.jwt_handler import JWTConfig, verify_token
from docpipe.api.auth.models import User
from docpipe.api.auth.oauth2_config import OAuth2Config, get_oauth2_config
from docpipe.api.auth.oauth2_provider import (
    AzureADOAuth2Provider,
    GenericOIDCProvider,
    GoogleOAuth2Provider,
    OAuth2Provider,
)
from docpipe.api.auth.oauth2_routes import (
    _MAX_STATE_ENTRIES,
    _STATE_TTL_SECONDS,
    NONCE_COOKIE_NAME,
    _consume_state,
    _is_same_origin,
    _state_store,
    _store_state,
    get_oauth2_provider_instance,
    resolve_return_to,
    validate_return_to,
)
from docpipe.api.auth.roles import Role
from docpipe.api.middleware.error_handler import docpipe_exception_handler
from docpipe.exceptions.docpipe_exceptions import ConfigurationError, DocpipeException, ExternalServiceError


@pytest.fixture(autouse=True)
def clear_state_store():
    """Ensure state store is empty before each test."""
    _state_store.clear()
    yield
    _state_store.clear()


# ---------------------------------------------------------------------------
# _is_same_origin
# ---------------------------------------------------------------------------


class TestIsSameOrigin:
    @pytest.mark.parametrize(
        "url",
        [
            "",
            "/",
            "/dashboard",
            "/callback?next=/home",
            "/deep/path?foo=bar#anchor",
        ],
    )
    def test_relative_urls_are_safe(self, url):
        assert _is_same_origin(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://evil.example.com",
            "http://evil.example.com/path",
            "javascript:alert(1)",
            "//evil.example.com/path",  # protocol-relative
            "//evil.example.com",
        ],
    )
    def test_external_and_protocol_relative_urls_are_rejected(self, url):
        assert _is_same_origin(url) is False

    def test_empty_string_is_safe(self):
        assert _is_same_origin("") is True


# ---------------------------------------------------------------------------
# _store_state / _consume_state
# ---------------------------------------------------------------------------


class TestStateStore:
    def test_stored_state_is_consumed_once(self):
        _store_state(state="abc123", redirect_url="/home", nonce="n1")
        result = _consume_state(state="abc123", nonce="n1")
        assert result == "/home"

    def test_consumed_state_cannot_be_reused(self):
        _store_state(state="abc123", redirect_url="/home", nonce="n1")
        _consume_state(state="abc123", nonce="n1")
        assert _consume_state(state="abc123", nonce="n1") is None

    def test_unknown_state_returns_none(self):
        assert _consume_state(state="no-such-state", nonce="n1") is None

    def test_empty_redirect_url_is_stored_and_returned(self):
        _store_state(state="s1", redirect_url="", nonce="n1")
        assert _consume_state(state="s1", nonce="n1") == ""

    def test_expired_state_is_rejected(self):
        state = "expired-state"
        expired_time = time.monotonic() - _STATE_TTL_SECONDS - 1
        _state_store[state] = ("/home", expired_time, "n1")
        assert _consume_state(state=state, nonce="n1") is None

    def test_expired_states_are_purged_on_store(self):
        # Plant an expired entry
        _state_store["old"] = ("/old", time.monotonic() - _STATE_TTL_SECONDS - 1, "n0")
        # Storing a new state triggers purge
        _store_state(state="new", redirect_url="/new", nonce="n1")
        assert "old" not in _state_store
        assert "new" in _state_store

    def test_multiple_states_tracked_independently(self):
        _store_state(state="s1", redirect_url="/a", nonce="n1")
        _store_state(state="s2", redirect_url="/b", nonce="n2")
        assert _consume_state(state="s1", nonce="n1") == "/a"
        assert _consume_state(state="s2", nonce="n2") == "/b"

    def test_store_full_raises_runtime_error(self):
        """_store_state raises RuntimeError when the cap is reached after purging."""
        # Fill the store to capacity with fresh (non-expired) entries
        future = time.monotonic() + _STATE_TTL_SECONDS + 100
        for i in range(_MAX_STATE_ENTRIES):
            _state_store[f"fill-{i}"] = ("/x", future, "n")
        with pytest.raises(RuntimeError, match="full"):
            _store_state(state="overflow", redirect_url="/y", nonce="n")

    @pytest.mark.parametrize("nonce", [None, "", "wrong"])
    def test_missing_or_mismatched_nonce_is_rejected_and_burns_state(self, nonce):
        _store_state(state="s1", redirect_url="/a", nonce="right")

        assert _consume_state(state="s1", nonce=nonce) is None
        assert _consume_state(state="s1", nonce="right") is None

    def test_state_stored_without_nonce_is_never_valid(self):
        _store_state(state="s1", redirect_url="/a")

        assert _consume_state(state="s1", nonce="") is None
        assert _consume_state(state="s1", nonce="anything") is None


# ---------------------------------------------------------------------------
# return_to validation
# ---------------------------------------------------------------------------


class TestReturnToValidation:
    @pytest.mark.parametrize(
        "value",
        ["/flows/x", "/flows/x?a=1", "/ui/flows/x", "/", "/flows/%E2%9C%93?q=a%20b", "/p?next=/a//b"],
    )
    def test_safe_values_are_kept(self, value):
        assert validate_return_to(value=value) == value

    @pytest.mark.parametrize(
        "value",
        [
            None,
            "",
            "https://evil.example/",
            "http://evil.example",
            "//evil.example/path",
            "///evil.example",
            "/\\evil.example.com",
            "/\\/evil.example.com",
            "\\evil.example",
            "javascript:alert(1)",
            "relative/no/leading/slash",
            "/a\nb",
            "/a\rb",
            "/a\x00b",
        ],
    )
    def test_unsafe_values_are_refused(self, value):
        assert validate_return_to(value=value) is None

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("/flows/abc", "/ui/flows/abc"),
            ("/flows/x?a=1", "/ui/flows/x?a=1"),
            ("/dashboard?tab=flows", "/ui/dashboard?tab=flows"),
            ("/ui/flows/abc", "/ui/flows/abc"),
            ("/ui", "/ui"),
            ("/ui?x=1", "/ui?x=1"),
            ("/uix/flows", "/ui/uix/flows"),
            ("/flows/%E2%9C%93?q=a%20b", "/ui/flows/%E2%9C%93?q=a%20b"),
            ("", "/ui/projects"),
            (None, "/ui/projects"),
            ("https://evil.example/", "/ui/projects"),
            ("//evil.example/x", "/ui/projects"),
            ("/\\evil.example", "/ui/projects"),
        ],
    )
    def test_resolution_prefixes_ui_and_defaults(self, value, expected):
        assert resolve_return_to(value=value) == expected


# ---------------------------------------------------------------------------
# /authorize endpoint — redirect_after validation
# ---------------------------------------------------------------------------


class TestAuthorizeEndpointRedirectValidation:
    """The /authorize endpoint drops unsafe return_to values; the callback then uses the default."""

    @pytest.fixture
    def app_with_routes(self):
        from docpipe.api.auth.oauth2_routes import router

        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.mark.parametrize("parameter", ["redirect_after", "return_to"])
    @pytest.mark.parametrize(
        "value",
        ["https://evil.example.com", "//evil.example.com/path", "/\\evil.example.com", "https://evil.example/"],
    )
    def test_unsafe_value_never_returns_400(self, app_with_routes, parameter, value):
        client = TestClient(app_with_routes, raise_server_exceptions=False)

        response = client.get("/auth/oauth2/authorize", params={parameter: value})

        # OAuth2 is not configured in this app, so the provider dependency answers 503;
        # the point is that return_to validation never answers 400.
        assert response.status_code != 400

    def test_relative_redirect_after_is_not_blocked(self, app_with_routes, monkeypatch):
        client = TestClient(app_with_routes, raise_server_exceptions=False)
        response = client.get(
            "/auth/oauth2/authorize",
            params={"redirect_after": "/dashboard"},
        )
        assert response.status_code != 400

    def test_no_redirect_after_is_not_blocked(self, app_with_routes):
        client = TestClient(app_with_routes, raise_server_exceptions=False)
        response = client.get("/auth/oauth2/authorize")
        assert response.status_code != 400


# ---------------------------------------------------------------------------
# Shared fixtures for endpoint tests
# ---------------------------------------------------------------------------

_JWT_SECRET = "oauth2-routes-test-secret-key-long-enough"  # pragma: allowlist secret
_AUTHORIZATION_ENDPOINT = "https://idp.example.com/authorize"
_ALICE = User(username="alice", email="alice@example.com", full_name="Alice Example")


class _StubProvider(OAuth2Provider):
    """In-memory OAuth2 provider that records calls and never touches the network."""

    def __init__(
        self,
        *,
        user: User = _ALICE,
        exchange_error: Exception | None = None,
        extract_error: Exception | None = None,
        authorize_error: Exception | None = None,
    ) -> None:
        super().__init__(
            OAuth2Config(
                oauth2_enabled=True,
                oauth2_client_id="stub-client",
                oauth2_client_secret="stub-secret",  # pragma: allowlist secret
                oauth2_redirect_uri="http://testserver/auth/oauth2/callback",
                oauth2_authorization_endpoint=_AUTHORIZATION_ENDPOINT,
            )
        )
        self.user = user
        self.exchange_error = exchange_error
        self.extract_error = extract_error
        self.authorize_error = authorize_error
        self.exchanged_codes: list[str] = []

    def get_provider_name(self) -> str:
        return "stub"

    def generate_authorization_url(self, state: str | None = None) -> tuple[str, str]:
        if self.authorize_error:
            raise self.authorize_error
        return super().generate_authorization_url(state)

    async def exchange_code_for_token(self, code: str) -> dict[str, Any]:
        self.exchanged_codes.append(code)
        if self.exchange_error:
            raise self.exchange_error
        return {"id_token": "stub-id-token", "access_token": "stub-access-token"}

    async def extract_user_from_token(self, token_data: dict[str, Any]) -> User:
        if self.extract_error:
            raise self.extract_error
        return self.user


@pytest.fixture
def stub_provider() -> _StubProvider:
    return _StubProvider()


@pytest.fixture
def oauth_app(stub_provider) -> FastAPI:
    from docpipe.api.auth.oauth2_routes import router

    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(DocpipeException, docpipe_exception_handler)
    app.dependency_overrides[get_oauth2_provider_instance] = lambda: stub_provider
    return app


@pytest.fixture
def client(oauth_app) -> TestClient:
    test_client = TestClient(oauth_app, follow_redirects=False)
    test_client.cookies.set(NONCE_COOKIE_NAME, _NONCE, path="/auth/oauth2")
    return test_client


@pytest.fixture
def jwt_env(monkeypatch, tmp_path) -> JWTConfig:
    """Provide a JWT secret via the environment (as in production) and no .env file."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JWT_SECRET_KEY", _JWT_SECRET)
    return JWTConfig()


_NONCE = "browser-nonce-value"


def _issue_state(*, redirect_url: str = "", nonce: str = _NONCE) -> str:
    state = f"state-{len(_state_store)}-{time.monotonic_ns()}"
    _store_state(state=state, redirect_url=redirect_url, nonce=nonce)
    return state


# ---------------------------------------------------------------------------
# get_oauth2_provider_instance
# ---------------------------------------------------------------------------


class TestGetOAuth2ProviderInstance:
    @staticmethod
    def _config(**overrides: Any) -> OAuth2Config:
        values: dict[str, Any] = {
            "oauth2_enabled": True,
            "oauth2_provider": "generic",
            "oauth2_client_id": "cid",
            "oauth2_client_secret": "csecret",  # pragma: allowlist secret
        }
        values.update(overrides)
        return OAuth2Config(**values)

    def test_disabled_oauth2_raises_503(self):
        with patch.object(oauth2_routes, "get_oauth2_config", return_value=self._config(oauth2_enabled=False)):
            with pytest.raises(HTTPException) as exc_info:
                get_oauth2_provider_instance(None)

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail == "OAuth2 authentication is not enabled"

    @pytest.mark.parametrize(
        "overrides",
        [{"oauth2_client_id": ""}, {"oauth2_client_secret": ""}],
        ids=["missing_client_id", "missing_client_secret"],
    )
    def test_incomplete_client_credentials_raise_503(self, overrides):
        with patch.object(oauth2_routes, "get_oauth2_config", return_value=self._config(**overrides)):
            with pytest.raises(HTTPException) as exc_info:
                get_oauth2_provider_instance(None)

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail == "OAuth2 is not properly configured"

    @pytest.mark.parametrize(
        ("provider_name", "expected_cls"),
        [("google", GoogleOAuth2Provider), ("azure", AzureADOAuth2Provider), ("generic", GenericOIDCProvider)],
    )
    def test_returns_provider_for_requested_name(self, *, provider_name, expected_cls):
        config = self._config(oauth2_provider=provider_name)
        with patch.object(oauth2_routes, "get_oauth2_config", return_value=config) as get_config:
            provider = get_oauth2_provider_instance(provider_name)

        get_config.assert_called_once_with(provider_name)
        assert isinstance(provider, expected_cls)
        assert provider.config is config

    def test_disabled_oauth2_blocks_authorize_without_storing_state(self):
        from docpipe.api.auth.oauth2_routes import router

        app = FastAPI()
        app.include_router(router)
        with patch.object(oauth2_routes, "get_oauth2_config", return_value=self._config(oauth2_enabled=False)):
            response = TestClient(app, follow_redirects=False).get("/auth/oauth2/authorize")

        assert response.status_code == 503
        assert _state_store == {}


# ---------------------------------------------------------------------------
# GET /auth/oauth2/authorize
# ---------------------------------------------------------------------------


class TestAuthorizeEndpoint:
    def test_redirects_to_provider_with_server_generated_state(self, client):
        response = client.get("/auth/oauth2/authorize", params={"redirect_after": "/dashboard"})

        assert response.status_code == 307
        location = urlparse(response.headers["location"])
        assert f"{location.scheme}://{location.netloc}{location.path}" == _AUTHORIZATION_ENDPOINT
        query = parse_qs(location.query)
        assert query["client_id"] == ["stub-client"]
        assert query["response_type"] == ["code"]
        (state,) = query["state"]
        assert len(state) >= 32
        assert _state_store[state][0] == "/dashboard"

    def test_each_request_gets_a_fresh_state(self, client):
        states = {
            parse_qs(urlparse(client.get("/auth/oauth2/authorize").headers["location"]).query)["state"][0]
            for _ in range(3)
        }

        assert len(states) == 3
        assert set(_state_store) == states

    def test_return_to_is_stored(self, client):
        response = client.get("/auth/oauth2/authorize", params={"return_to": "/flows/abc?x=1"})

        state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
        assert _state_store[state][0] == "/flows/abc?x=1"

    def test_return_to_wins_over_redirect_after(self, client):
        response = client.get("/auth/oauth2/authorize", params={"return_to": "/flows/a", "redirect_after": "/flows/b"})

        state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
        assert _state_store[state][0] == "/flows/a"

    @pytest.mark.parametrize("parameter", ["return_to", "redirect_after"])
    @pytest.mark.parametrize(
        "value", ["https://evil.example/", "//evil.example/x", "/\\evil.example", "http://evil.example"]
    )
    def test_unsafe_value_is_dropped_not_rejected(self, client, parameter, value):
        response = client.get("/auth/oauth2/authorize", params={parameter: value})

        assert response.status_code == 307
        state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
        assert _state_store[state][0] == ""

    def test_sets_httponly_nonce_cookie_tied_to_state(self, client):
        client.cookies.clear()

        response = client.get("/auth/oauth2/authorize")

        header = response.headers["set-cookie"].lower()
        assert header.startswith(f"{NONCE_COOKIE_NAME}=")
        assert "httponly" in header
        assert "samesite=lax" in header
        assert "path=/auth/oauth2" in header
        assert "max-age=600" in header
        state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
        assert response.cookies.get(NONCE_COOKIE_NAME) == _state_store[state][2]
        assert len(_state_store[state][2]) >= 32

    def test_each_request_gets_a_fresh_nonce(self, client):
        client.cookies.clear()
        nonces = {client.get("/auth/oauth2/authorize").cookies.get(NONCE_COOKIE_NAME) for _ in range(3)}
        client.cookies.clear()

        assert len(nonces) == 3

    def test_nonce_cookie_is_secure_over_https(self, client):
        https_client = TestClient(client.app, base_url="https://testserver", follow_redirects=False)

        assert "; secure" in https_client.get("/auth/oauth2/authorize").headers["set-cookie"].lower()

    def test_without_redirect_after_stores_empty_redirect(self, client):
        response = client.get("/auth/oauth2/authorize")

        state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
        assert _state_store[state][0] == ""

    def test_full_state_store_returns_429(self, client):
        future = time.monotonic() + _STATE_TTL_SECONDS
        for i in range(_MAX_STATE_ENTRIES):
            _state_store[f"pending-{i}"] = ("", future, "n")

        response = client.get("/auth/oauth2/authorize")

        assert response.status_code == 429
        assert "location" not in response.headers
        assert len(_state_store) == _MAX_STATE_ENTRIES

    def test_unexpected_provider_error_returns_generic_500(self, *, oauth_app, stub_provider):
        stub_provider.authorize_error = RuntimeError("internal detail: secret-ish")

        response = TestClient(oauth_app, follow_redirects=False).get("/auth/oauth2/authorize")

        assert response.status_code == 500
        assert response.json() == {"detail": "Failed to initiate OAuth2 flow"}

    def test_docpipe_errors_are_propagated_not_masked(self, *, oauth_app, stub_provider):
        stub_provider.authorize_error = ConfigurationError("authorization endpoint missing")

        response = TestClient(oauth_app, follow_redirects=False).get("/auth/oauth2/authorize")

        assert response.status_code == 400
        assert "authorization endpoint missing" in response.text


# ---------------------------------------------------------------------------
# GET /auth/oauth2/callback
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("jwt_env")
class TestCallbackEndpoint:
    def test_success_sets_session_cookie_and_redirects_to_default(self, *, client, stub_provider, jwt_env):
        state = _issue_state()

        response = client.get("/auth/oauth2/callback", params={"code": "auth-code", "state": state})

        assert response.status_code == 302
        assert response.headers["location"] == "/ui/projects"
        token = response.cookies.get("docpipe_access_token")
        claims = verify_token(token, jwt_env)
        assert claims is not None
        assert (claims["username"], claims["email"], claims["full_name"]) == (
            "alice",
            "alice@example.com",
            "Alice Example",
        )
        assert claims["roles"] == ["viewer"]
        assert stub_provider.exchanged_codes == ["auth-code"]

    def test_session_cookie_flags(self, *, client):
        response = client.get("/auth/oauth2/callback", params={"code": "c", "state": _issue_state()})

        session_cookie = next(
            value for value in response.headers.get_list("set-cookie") if value.startswith("docpipe_access_token=")
        ).lower()
        assert "httponly" in session_cookie
        assert "samesite=lax" in session_cookie
        assert "path=/;" in session_cookie or session_cookie.endswith("path=/")

    def test_nonce_cookie_is_cleared(self, *, client):
        response = client.get("/auth/oauth2/callback", params={"code": "c", "state": _issue_state()})

        nonce_cookie = next(
            value for value in response.headers.get_list("set-cookie") if value.startswith(f"{NONCE_COOKIE_NAME}=")
        ).lower()
        assert "max-age=0" in nonce_cookie

    def test_provider_roles_are_carried_into_the_token(self, *, client, stub_provider, jwt_env):
        stub_provider.user = User(username="root", email="r@example.com", full_name="R", roles=[Role.ADMIN])

        response = client.get("/auth/oauth2/callback", params={"code": "c", "state": _issue_state()})

        claims = verify_token(response.cookies.get("docpipe_access_token"), jwt_env)
        assert claims is not None
        assert claims["roles"] == ["admin"]

    @pytest.mark.parametrize(
        ("stored", "expected"),
        [
            ("/flows/abc", "/ui/flows/abc"),
            ("/flows/x?a=1", "/ui/flows/x?a=1"),
            ("/dashboard?tab=flows", "/ui/dashboard?tab=flows"),
            ("/ui/flows/abc", "/ui/flows/abc"),
            ("/ui", "/ui"),
            ("", "/ui/projects"),
        ],
    )
    def test_redirects_to_validated_return_to_below_ui(self, *, client, stored, expected):
        state = _issue_state(redirect_url=stored)

        response = client.get("/auth/oauth2/callback", params={"code": "c", "state": state})

        assert response.status_code == 302
        assert response.headers["location"] == expected

    @pytest.mark.parametrize(
        "unsafe", ["https://evil.example/", "//evil.example/x", "/\\evil.example", "http://evil.example"]
    )
    def test_unsafe_return_to_redirects_to_default_end_to_end(self, *, client, unsafe):
        authorize = client.get("/auth/oauth2/authorize", params={"return_to": unsafe})
        state = parse_qs(urlparse(authorize.headers["location"]).query)["state"][0]

        response = client.get("/auth/oauth2/callback", params={"code": "c", "state": state})

        assert response.status_code == 302
        assert response.headers["location"] == "/ui/projects"

    def test_unsafe_value_in_the_store_is_revalidated_by_the_callback(self, *, client):
        state = _issue_state(redirect_url="https://evil.example/")

        response = client.get("/auth/oauth2/callback", params={"code": "c", "state": state})

        assert response.headers["location"] == "/ui/projects"

    def test_token_never_appears_in_the_redirect_url(self, *, client):
        response = client.get("/auth/oauth2/callback", params={"code": "c", "state": _issue_state()})

        token = response.cookies.get("docpipe_access_token")
        assert token and token not in response.headers["location"]
        assert "#" not in response.headers["location"]
        assert "access_token" not in response.headers["location"]

    def test_matching_nonce_completes_the_login(self, *, client):
        client.cookies.clear()
        authorize = client.get("/auth/oauth2/authorize")  # the browser receives the nonce cookie here
        state = parse_qs(urlparse(authorize.headers["location"]).query)["state"][0]

        response = client.get("/auth/oauth2/callback", params={"code": "c", "state": state})

        assert response.status_code == 302
        assert response.cookies.get("docpipe_access_token")

    def test_missing_nonce_cookie_is_rejected_without_session_cookie(self, *, client, stub_provider):
        client.cookies.clear()
        state = _issue_state()

        response = client.get("/auth/oauth2/callback", params={"code": "c", "state": state})

        assert response.status_code == 400
        assert "docpipe_access_token" not in response.headers.get("set-cookie", "")
        assert stub_provider.exchanged_codes == []

    def test_mismatched_nonce_cookie_is_rejected_without_session_cookie(self, *, client, stub_provider):
        client.cookies.clear()
        client.cookies.set(NONCE_COOKIE_NAME, "another-browsers-nonce", path="/auth/oauth2")
        state = _issue_state()

        response = client.get("/auth/oauth2/callback", params={"code": "c", "state": state})

        assert response.status_code == 400
        assert "docpipe_access_token" not in response.headers.get("set-cookie", "")
        assert stub_provider.exchanged_codes == []
        assert state not in _state_store

    def test_state_is_single_use(self, *, client, stub_provider):
        state = _issue_state()
        first = client.get("/auth/oauth2/callback", params={"code": "c1", "state": state})

        replay = client.get("/auth/oauth2/callback", params={"code": "c2", "state": state})

        assert first.status_code == 302
        assert replay.status_code == 400
        assert stub_provider.exchanged_codes == ["c1"]

    def test_unknown_state_is_rejected_before_code_exchange(self, *, client, stub_provider):
        """CSRF guard: a forged callback must never reach the token endpoint."""
        _issue_state()

        response = client.get("/auth/oauth2/callback", params={"code": "c", "state": "attacker-chosen"})

        assert response.status_code == 400
        assert response.json() == {"detail": "Invalid or expired state parameter"}
        assert stub_provider.exchanged_codes == []

    def test_expired_state_is_rejected(self, *, client, stub_provider):
        _state_store["stale"] = ("", time.monotonic() - 1, _NONCE)

        response = client.get("/auth/oauth2/callback", params={"code": "c", "state": "stale"})

        assert response.status_code == 400
        assert stub_provider.exchanged_codes == []
        assert "stale" not in _state_store

    @pytest.mark.parametrize(
        "params",
        [
            pytest.param({"state": "s"}, id="missing_code"),
            pytest.param({"code": "c"}, id="missing_state"),
            pytest.param(
                {"error": "access_denied", "error_description": "User cancelled", "state": "s"},
                id="provider_error_response",
            ),
        ],
    )
    def test_incomplete_callbacks_are_rejected_without_token(self, *, client, stub_provider, params):
        response = client.get("/auth/oauth2/callback", params=params)

        assert response.status_code == 422
        assert "access_token" not in response.text
        assert stub_provider.exchanged_codes == []

    def test_token_exchange_failure_returns_502_and_burns_state(self, *, client, stub_provider):
        stub_provider.exchange_error = ExternalServiceError("Token exchange failed: invalid_grant")
        state = _issue_state()

        response = client.get("/auth/oauth2/callback", params={"code": "bad", "state": state})

        assert response.status_code == 502
        assert "access_token" not in response.text
        assert "docpipe_access_token" not in response.headers.get("set-cookie", "")
        assert state not in _state_store

    def test_id_token_validation_failure_returns_502(self, *, client, stub_provider):
        stub_provider.extract_error = ExternalServiceError("ID token validation failed: Signature verification failed")

        response = client.get("/auth/oauth2/callback", params={"code": "c", "state": _issue_state()})

        assert response.status_code == 502
        assert "access_token" not in response.text

    def test_unexpected_error_returns_generic_500(self, *, client, stub_provider):
        stub_provider.extract_error = KeyError("email")

        response = client.get("/auth/oauth2/callback", params={"code": "c", "state": _issue_state()})

        assert response.status_code == 500
        assert response.json() == {"detail": "OAuth2 authentication failed"}

    def test_missing_jwt_secret_returns_503(self, *, client, monkeypatch):
        monkeypatch.delenv("JWT_SECRET_KEY")

        response = client.get("/auth/oauth2/callback", params={"code": "c", "state": _issue_state()})

        assert response.status_code == 503
        assert response.json() == {"detail": "JWT configuration not available"}

    @pytest.mark.parametrize("redirect_after", ["/\\evil.example.com", "/\\/evil.example.com"])
    def test_backslash_redirect_cannot_become_cross_origin(self, *, client, redirect_after):
        """Browsers treat ``/\\host`` as ``//host``; the emitted Location must stay same-origin."""
        authorize = client.get("/auth/oauth2/authorize", params={"redirect_after": redirect_after})
        state = parse_qs(urlparse(authorize.headers["location"]).query)["state"][0]

        response = client.get("/auth/oauth2/callback", params={"code": "c", "state": state})

        location = response.headers["location"]
        normalised = location.replace("\\", "/")
        assert normalised == "/ui/projects"


# ---------------------------------------------------------------------------
# GET /auth/oauth2/providers
# ---------------------------------------------------------------------------


class TestListProvidersEndpoint:
    def test_lists_only_enabled_providers_with_client_id(self, client):
        configs = {
            "google": OAuth2Config(oauth2_enabled=True, oauth2_client_id="g-id"),
            "azure": OAuth2Config(oauth2_enabled=True, oauth2_client_id=""),
        }

        def fake_get_config(provider_name):
            if provider_name == "generic":
                raise ValueError("malformed settings")
            return configs[provider_name]

        with patch.object(oauth2_routes, "get_oauth2_config", side_effect=fake_get_config):
            response = client.get("/auth/oauth2/providers")

        assert response.status_code == 200
        assert response.json() == {
            "providers": [
                {
                    "name": "google",
                    "display_name": "Google",
                    "authorize_url": "/auth/oauth2/authorize?provider=google",
                }
            ]
        }

    def test_returns_empty_list_when_nothing_configured(self, client):
        with patch.object(oauth2_routes, "get_oauth2_config", return_value=OAuth2Config(oauth2_enabled=False)):
            response = client.get("/auth/oauth2/providers")

        assert response.json() == {"providers": []}


# ---------------------------------------------------------------------------
# GET /auth/oauth2/discovery/{provider}
# ---------------------------------------------------------------------------


class TestDiscoveryEndpoint:
    @pytest.fixture
    def discovery_app(self, oauth_app) -> tuple[FastAPI, list[str | None]]:
        requested: list[str | None] = []

        def fake_get_config(provider: str | None = None) -> OAuth2Config:
            requested.append(provider)
            return OAuth2Config(oauth2_enabled=True, oauth2_provider=provider or "generic")

        oauth_app.dependency_overrides[get_oauth2_config] = fake_get_config
        return oauth_app, requested

    def test_returns_discovery_document_for_path_provider(self, discovery_app):
        app, requested = discovery_app
        provider = MagicMock()
        provider.discover_endpoints = AsyncMock(return_value={"issuer": "https://accounts.google.com"})

        with patch.object(oauth2_routes, "get_oauth2_provider", return_value=provider) as factory:
            response = TestClient(app).get("/auth/oauth2/discovery/google")

        assert response.status_code == 200
        assert response.json() == {"issuer": "https://accounts.google.com"}
        assert requested == ["google"]
        assert factory.call_args.args[0].oauth2_provider == "google"

    def test_external_failure_returns_502(self, discovery_app):
        app, _ = discovery_app
        provider = MagicMock()
        provider.discover_endpoints = AsyncMock(side_effect=ExternalServiceError("OIDC discovery failed: timeout"))

        with patch.object(oauth2_routes, "get_oauth2_provider", return_value=provider):
            response = TestClient(app).get("/auth/oauth2/discovery/google")

        assert response.status_code == 502

    def test_unexpected_failure_returns_generic_500(self, discovery_app):
        app, _ = discovery_app

        with patch.object(oauth2_routes, "get_oauth2_provider", side_effect=RuntimeError("boom")):
            response = TestClient(app).get("/auth/oauth2/discovery/google")

        assert response.status_code == 500
        assert response.json() == {"detail": "Failed to fetch discovery document"}
