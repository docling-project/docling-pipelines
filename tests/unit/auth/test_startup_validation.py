# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for the authentication startup validation."""

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from docpipe.api.auth import startup_validation
from docpipe.api.auth.config import AuthSettings
from docpipe.api.auth.startup_validation import is_placeholder_secret, validate_auth_startup
from docpipe.exceptions.docpipe_exceptions import ConfigurationError

_STRONG_SECRET = "k3j9x0Qw7vB2nM5pL8rT1yU4iO6eA9sD3fG7hJ0z"  # pragma: allowlist secret
_SRC_DIR = Path(__file__).resolve().parents[3] / "src"

_ENABLED = AuthSettings(enabled=True, cookie_secure=True)
_DISABLED = AuthSettings(enabled=False)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Start every test without a secret or JWT file settings."""
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("JWT_ALGORITHM", raising=False)
    monkeypatch.delenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", raising=False)
    # Keep a developer .env file from supplying a secret.
    monkeypatch.chdir(Path(__file__).parent)


@pytest.fixture
def startup_log(caplog):
    """Capture records of the startup module logger.

    The ``docpipe`` logger hierarchy may have propagation disabled by ``setup_logging()``,
    so the caplog handler is attached to the module logger directly.
    """
    module_logger = logging.getLogger(startup_validation.__name__)
    module_logger.addHandler(caplog.handler)
    caplog.set_level(logging.DEBUG, logger=startup_validation.__name__)
    yield caplog
    module_logger.removeHandler(caplog.handler)


def _warnings(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]


class TestEnabled:
    def test_strong_secret_returns_config(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", _STRONG_SECRET)

        config = validate_auth_startup(settings=_ENABLED, cors_origins=["http://localhost:3000"])

        assert config is not None
        assert config.jwt_secret_key == _STRONG_SECRET

    def test_unset_secret_fails(self):
        with pytest.raises(ConfigurationError, match="JWT_SECRET_KEY must be set to a value of at least 32"):
            validate_auth_startup(settings=_ENABLED, cors_origins=[])

    def test_empty_secret_fails(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "")

        with pytest.raises(ConfigurationError, match="at least 32 characters"):
            validate_auth_startup(settings=_ENABLED, cors_origins=[])

    def test_short_secret_fails_without_leaking_it(self, monkeypatch):
        short_secret = "too-short-secret"  # pragma: allowlist secret
        monkeypatch.setenv("JWT_SECRET_KEY", short_secret)

        with pytest.raises(ConfigurationError) as excinfo:
            validate_auth_startup(settings=_ENABLED, cors_origins=[])

        assert "at least 32 characters" in str(excinfo.value)
        assert short_secret not in str(excinfo.value)

    def test_31_characters_fails_and_32_passes(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p")  # pragma: allowlist secret
        with pytest.raises(ConfigurationError):
            validate_auth_startup(settings=_ENABLED, cors_origins=[])

        monkeypatch.setenv("JWT_SECRET_KEY", "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6")  # pragma: allowlist secret
        assert validate_auth_startup(settings=_ENABLED, cors_origins=[]) is not None

    @pytest.mark.parametrize(
        "placeholder",
        [
            "local-dev-secret-key-change-this-in-production!!",  # pragma: allowlist secret
            "your-secret-key-here-change-this-in-production",  # pragma: allowlist secret
            "your-jwt-secret-key-which-is-long-enough-x",  # pragma: allowlist secret
            "CHANGEME-CHANGEME-CHANGEME-CHANGEME-1234",  # pragma: allowlist secret
            "replace-me-with-a-real-secret-of-length-32",  # pragma: allowlist secret
        ],
    )
    def test_long_placeholder_fails_without_leaking_it(self, monkeypatch, placeholder):
        monkeypatch.setenv("JWT_SECRET_KEY", placeholder)

        with pytest.raises(ConfigurationError) as excinfo:
            validate_auth_startup(settings=_ENABLED, cors_origins=[])

        assert "known placeholder" in str(excinfo.value)
        assert placeholder not in str(excinfo.value)

    def test_broken_jwt_setting_fails_instead_of_disabling_login(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", _STRONG_SECRET)
        monkeypatch.setenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "not-a-number")

        with pytest.raises(ConfigurationError, match="Invalid JWT configuration: jwt_access_token_expire_minutes"):
            validate_auth_startup(settings=_ENABLED, cors_origins=[])


class TestDisabled:
    def test_starts_without_a_secret(self):
        assert validate_auth_startup(settings=_DISABLED, cors_origins=[]) is None

    def test_returns_config_when_a_secret_is_present(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", _STRONG_SECRET)

        assert validate_auth_startup(settings=_DISABLED, cors_origins=[]) is not None

    def test_weak_secret_does_not_block_startup(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "short")  # pragma: allowlist secret

        assert validate_auth_startup(settings=_DISABLED, cors_origins=[]) is None

    def test_no_cookie_warning_when_disabled(self, startup_log):
        validate_auth_startup(settings=_DISABLED, cors_origins=[])

        assert _warnings(startup_log) == []


class TestCorsWarning:
    def test_wildcard_origin_logs_a_security_warning(self, monkeypatch, startup_log):
        monkeypatch.setenv("JWT_SECRET_KEY", _STRONG_SECRET)

        validate_auth_startup(settings=_ENABLED, cors_origins=["*"])

        assert any("CORS_ORIGINS contains '*'" in message for message in _warnings(startup_log))

    def test_wildcard_among_other_origins_warns(self, startup_log):
        validate_auth_startup(settings=_DISABLED, cors_origins=["http://localhost:3000", "*"])

        assert any("CORS_ORIGINS contains '*'" in message for message in _warnings(startup_log))

    def test_explicit_origins_do_not_warn(self, monkeypatch, startup_log):
        monkeypatch.setenv("JWT_SECRET_KEY", _STRONG_SECRET)

        validate_auth_startup(settings=_ENABLED, cors_origins=["https://app.example.test"])

        assert _warnings(startup_log) == []


class TestSecureCookieWarning:
    @pytest.mark.parametrize(
        "settings",
        [
            AuthSettings(enabled=True, cookie_secure=True),
            AuthSettings(enabled=True, trust_proxy_headers=True),
            AuthSettings(enabled=True, cookie_secure=True, trust_proxy_headers=True),
        ],
    )
    def test_no_warning_with_a_secure_signal(self, monkeypatch, startup_log, settings):
        monkeypatch.setenv("JWT_SECRET_KEY", _STRONG_SECRET)

        validate_auth_startup(settings=settings, cors_origins=[])

        assert _warnings(startup_log) == []

    def test_warns_when_enabled_without_a_secure_signal(self, monkeypatch, startup_log):
        monkeypatch.setenv("JWT_SECRET_KEY", _STRONG_SECRET)

        validate_auth_startup(settings=AuthSettings(enabled=True), cors_origins=[])

        warnings = _warnings(startup_log)
        assert len(warnings) == 1
        assert "DOCPIPE_AUTH_COOKIE_SECURE" in warnings[0]
        assert "DOCPIPE_TRUST_PROXY_HEADERS" in warnings[0]


class TestPlaceholderDetection:
    def test_random_secret_is_not_a_placeholder(self):
        assert is_placeholder_secret(secret=_STRONG_SECRET) is False

    def test_detection_is_case_insensitive(self):
        assert is_placeholder_secret(secret="Change-This-Please") is True  # pragma: allowlist secret


class TestApplicationImport:
    """The app module must fail loudly at import when auth is enabled with a bad configuration."""

    @staticmethod
    def _import_app(*, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        child_env = {key: value for key, value in os.environ.items() if not key.startswith(("JWT_", "DOCPIPE_AUTH_"))}
        child_env.update(env)
        child_env["PYTHONPATH"] = str(_SRC_DIR)
        return subprocess.run(  # nosec B603
            [sys.executable, "-c", "import docpipe.api.main"],
            env=child_env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            cwd=str(Path(__file__).parent),
        )

    def test_enabled_with_weak_secret_fails_to_start(self):
        result = self._import_app(env={"DOCPIPE_AUTH_ENABLED": "true", "JWT_SECRET_KEY": "weak"})

        assert result.returncode != 0
        assert "ConfigurationError" in result.stderr
        assert "JWT_SECRET_KEY must be set to a value of at least 32 characters" in result.stderr

    def test_enabled_with_strong_secret_starts(self):
        result = self._import_app(env={"DOCPIPE_AUTH_ENABLED": "true", "JWT_SECRET_KEY": _STRONG_SECRET})

        assert result.returncode == 0, result.stderr

    def test_disabled_without_secret_starts(self):
        result = self._import_app(env={"DOCPIPE_AUTH_ENABLED": "false"})

        assert result.returncode == 0, result.stderr
