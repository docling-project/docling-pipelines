# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for AuthSettings."""

from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from docpipe.api.auth.config import (
    DEFAULT_COOKIE_NAME,
    AuthSettings,
    get_auth_settings,
)
from docpipe.api.auth.roles import Role
from docpipe.core.constants.constants import EnvironmentVariables

_ALL_VARIABLES = [
    EnvironmentVariables.DOCPIPE_AUTH_ENABLED,
    EnvironmentVariables.DOCPIPE_AUTH_DEFAULT_ROLE,
    EnvironmentVariables.DOCPIPE_AUTH_ROLE_MAPPING_VIEWER,
    EnvironmentVariables.DOCPIPE_AUTH_ROLE_MAPPING_EDITOR,
    EnvironmentVariables.DOCPIPE_AUTH_ROLE_MAPPING_ADMIN,
    EnvironmentVariables.DOCPIPE_AUTH_COOKIE_NAME,
    EnvironmentVariables.DOCPIPE_AUTH_COOKIE_SECURE,
    EnvironmentVariables.DOCPIPE_TRUST_PROXY_HEADERS,
    EnvironmentVariables.DOCPIPE_AUTH_BOOTSTRAP_USERNAME,
    EnvironmentVariables.DOCPIPE_AUTH_BOOTSTRAP_PASSWORD_HASH,
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Remove every auth variable so each test starts from the defaults."""
    for name in _ALL_VARIABLES:
        monkeypatch.delenv(name, raising=False)


class TestDefaults:
    def test_defaults(self):
        settings = AuthSettings.from_env()

        assert settings.enabled is False
        assert settings.default_role is Role.VIEWER
        assert settings.role_mapping == {Role.VIEWER: (), Role.EDITOR: (), Role.ADMIN: ()}
        assert settings.cookie_name == DEFAULT_COOKIE_NAME == "docpipe_access_token"
        assert settings.cookie_secure is False
        assert settings.trust_proxy_headers is False
        assert settings.bootstrap_username is None
        assert settings.bootstrap_password_hash is None

    def test_settings_are_immutable(self):
        with pytest.raises(AttributeError):
            AuthSettings.from_env().enabled = True  # type: ignore[misc]


class TestParsing:
    @pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on", " true "])
    def test_truthy_values_enable(self, monkeypatch, value):
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_AUTH_ENABLED, value)
        assert AuthSettings.from_env().enabled is True

    @pytest.mark.parametrize("value", ["false", "0", "no", "off", "", "garbage"])
    def test_other_values_disable(self, monkeypatch, value):
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_AUTH_ENABLED, value)
        assert AuthSettings.from_env().enabled is False

    def test_cookie_and_proxy_flags(self, monkeypatch):
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_AUTH_COOKIE_SECURE, "true")
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_TRUST_PROXY_HEADERS, "true")
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_AUTH_COOKIE_NAME, "custom_cookie")

        settings = AuthSettings.from_env()

        assert settings.cookie_secure is True
        assert settings.trust_proxy_headers is True
        assert settings.cookie_name == "custom_cookie"

    def test_bootstrap_variables(self, monkeypatch):
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_AUTH_BOOTSTRAP_USERNAME, " root ")
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_AUTH_BOOTSTRAP_PASSWORD_HASH, "$2b$12$abc")

        settings = AuthSettings.from_env()

        assert settings.bootstrap_username == "root"
        assert settings.bootstrap_password_hash == "$2b$12$abc"

    def test_blank_bootstrap_values_are_unset(self, monkeypatch):
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_AUTH_BOOTSTRAP_USERNAME, "   ")
        assert AuthSettings.from_env().bootstrap_username is None

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("editor", Role.EDITOR),
            (" ADMIN ", Role.ADMIN),
            ("viewer", Role.VIEWER),
        ],
    )
    def test_default_role(self, monkeypatch, raw, expected):
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_AUTH_DEFAULT_ROLE, raw)
        assert AuthSettings.from_env().default_role is expected

    def test_invalid_default_role_falls_back_to_viewer(self, monkeypatch):
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_AUTH_DEFAULT_ROLE, "superuser")
        assert AuthSettings.from_env().default_role is Role.VIEWER

    def test_role_mapping_semicolon_separated_and_trimmed(self, monkeypatch):
        monkeypatch.setenv(
            EnvironmentVariables.DOCPIPE_AUTH_ROLE_MAPPING_EDITOR,
            " cn=editors,ou=groups,dc=example,dc=com ; team-b ;; ",
        )
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_AUTH_ROLE_MAPPING_ADMIN, "admins")

        mapping = AuthSettings.from_env().role_mapping

        assert mapping[Role.EDITOR] == ("cn=editors,ou=groups,dc=example,dc=com", "team-b")
        assert mapping[Role.ADMIN] == ("admins",)
        assert mapping[Role.VIEWER] == ()


class TestReadPerRequest:
    def test_env_change_between_calls_is_observed(self, monkeypatch):
        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_AUTH_ENABLED, "false")
        assert get_auth_settings().enabled is False

        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_AUTH_ENABLED, "true")
        assert get_auth_settings().enabled is True

    def test_env_change_between_two_requests_is_observed(self, monkeypatch):
        app = FastAPI()

        @app.get("/enabled")
        def read_enabled(settings: Annotated[AuthSettings, Depends(get_auth_settings)]) -> dict[str, bool]:
            return {"enabled": settings.enabled}

        client = TestClient(app)

        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_AUTH_ENABLED, "false")
        assert client.get("/enabled").json() == {"enabled": False}

        monkeypatch.setenv(EnvironmentVariables.DOCPIPE_AUTH_ENABLED, "true")
        assert client.get("/enabled").json() == {"enabled": True}
