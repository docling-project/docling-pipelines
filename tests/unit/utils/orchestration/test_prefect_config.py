# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for Prefect environment configuration helpers.

Tests cover:
- Telemetry and API-logging environment variables in ephemeral and server mode
- Server mode with and without PREFECT_API_URL
- Ephemeral mode with in-memory and file-backed SQLite, and debug mode
- Cleanup of the temporary Prefect home and the _safe_rmtree guards

No Prefect server is started: the helpers only set environment variables. Every
variable they touch is cleared through monkeypatch so the real environment is
restored afterwards, and the system temp directory is redirected to tmp_path.
"""

import os
import tempfile
from pathlib import Path

import pytest

from docpipe.utils.orchestration import prefect_config
from docpipe.utils.orchestration.prefect_config import (
    PREFECT_API_DATABASE_CONNECTION_URL,
    PREFECT_API_SERVICES_FLOW_RUN_NOTIFICATIONS_ENABLED,
    PREFECT_API_URL,
    PREFECT_CLOUD_ENABLE_ORCHESTRATION_TELEMETRY,
    PREFECT_DEBUG,
    PREFECT_EPHEMERAL_DB,
    PREFECT_HOME,
    PREFECT_HOME_PREFIX,
    PREFECT_LOG_TO_API,
    PREFECT_LOGGING_TO_API_ENABLED,
    PREFECT_MODE,
    PREFECT_SERVER_ANALYTICS_ENABLED,
    PREFECT_SERVER_EPHEMERAL_STARTUP_TIMEOUT_SECONDS,
    _safe_rmtree,
    clean_up_prefect_home,
    set_prefect_env_variables,
)

EXTRA_LOGGERS = "PREFECT_LOGGING_EXTRA_LOGGERS"

_TOUCHED_VARS = (
    PREFECT_API_DATABASE_CONNECTION_URL,
    PREFECT_API_SERVICES_FLOW_RUN_NOTIFICATIONS_ENABLED,
    PREFECT_API_URL,
    PREFECT_CLOUD_ENABLE_ORCHESTRATION_TELEMETRY,
    PREFECT_DEBUG,
    PREFECT_EPHEMERAL_DB,
    PREFECT_HOME,
    PREFECT_LOG_TO_API,
    PREFECT_LOGGING_TO_API_ENABLED,
    PREFECT_MODE,
    PREFECT_SERVER_ANALYTICS_ENABLED,
    PREFECT_SERVER_EPHEMERAL_STARTUP_TIMEOUT_SECONDS,
    EXTRA_LOGGERS,
)


@pytest.fixture(autouse=True)
def isolated_prefect_env(monkeypatch, tmp_path):
    """Clear every Prefect variable the helpers touch and redirect the system temp dir."""
    for name in _TOUCHED_VARS:
        monkeypatch.delenv(name, raising=False)
    temp_root = tmp_path / "systemp"
    temp_root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp_root))
    return temp_root


class TestSetPrefectEnvVariables:
    """Test set_prefect_env_variables."""

    def test_default_ephemeral_mode_uses_in_memory_sqlite(self, isolated_prefect_env):
        """Without PREFECT_MODE, telemetry is off, API logging is off and an in-memory DB is used."""
        os.environ[EXTRA_LOGGERS] = "stale"

        set_prefect_env_variables()

        assert os.environ[PREFECT_CLOUD_ENABLE_ORCHESTRATION_TELEMETRY] == "false"
        assert os.environ[PREFECT_SERVER_ANALYTICS_ENABLED] == "false"
        assert os.environ[PREFECT_SERVER_EPHEMERAL_STARTUP_TIMEOUT_SECONDS] == "120"
        assert os.environ[PREFECT_LOGGING_TO_API_ENABLED] == "False"
        assert EXTRA_LOGGERS not in os.environ
        assert os.environ[PREFECT_API_SERVICES_FLOW_RUN_NOTIFICATIONS_ENABLED] == "False"
        assert os.environ[PREFECT_API_DATABASE_CONNECTION_URL] == "sqlite+aiosqlite:///:memory:"
        home = Path(os.environ[PREFECT_HOME])
        assert home.is_dir()
        assert home.parent == isolated_prefect_env
        assert home.name.startswith(PREFECT_HOME_PREFIX)

    def test_ephemeral_file_db_points_into_prefect_home(self, monkeypatch):
        """PREFECT_EPHEMERAL_DB=file (any case) stores the SQLite file under PREFECT_HOME."""
        monkeypatch.setenv(PREFECT_EPHEMERAL_DB, "FILE")

        set_prefect_env_variables()

        home = os.environ[PREFECT_HOME]
        assert os.environ[PREFECT_API_DATABASE_CONNECTION_URL] == f"sqlite+aiosqlite:///{home}/prefect.db"

    def test_debug_mode_keeps_default_home_and_database(self, monkeypatch):
        """With PREFECT_DEBUG set, no temp home or database URL is configured."""
        monkeypatch.setenv(PREFECT_DEBUG, "true")

        set_prefect_env_variables()

        assert PREFECT_HOME not in os.environ
        assert PREFECT_API_DATABASE_CONNECTION_URL not in os.environ
        assert PREFECT_API_SERVICES_FLOW_RUN_NOTIFICATIONS_ENABLED not in os.environ

    def test_log_to_api_is_ignored_in_ephemeral_mode(self, monkeypatch):
        """PREFECT_LOG_TO_API=true has no effect outside server mode."""
        monkeypatch.setenv(PREFECT_LOG_TO_API, "true")

        set_prefect_env_variables()

        assert os.environ[PREFECT_LOGGING_TO_API_ENABLED] == "False"
        assert EXTRA_LOGGERS not in os.environ

    def test_server_mode_with_api_url_enables_api_logging(self, monkeypatch):
        """Server mode with PREFECT_LOG_TO_API=true routes DOCPIPE logs to the API and skips ephemeral setup."""
        monkeypatch.setenv(PREFECT_MODE, "Server")
        monkeypatch.setenv(PREFECT_API_URL, "http://prefect.example:4200/api")
        monkeypatch.setenv(PREFECT_LOG_TO_API, "TRUE")

        set_prefect_env_variables()

        assert os.environ[EXTRA_LOGGERS] == "DOCPIPE"
        assert os.environ[PREFECT_LOGGING_TO_API_ENABLED] == "True"
        assert os.environ[PREFECT_API_URL] == "http://prefect.example:4200/api"
        assert PREFECT_HOME not in os.environ
        assert PREFECT_API_DATABASE_CONNECTION_URL not in os.environ

    def test_server_mode_without_log_to_api_keeps_api_logging_off(self, monkeypatch):
        """Server mode alone does not enable API logging."""
        monkeypatch.setenv(PREFECT_MODE, "server")
        monkeypatch.setenv(PREFECT_API_URL, "http://prefect.example:4200/api")

        set_prefect_env_variables()

        assert os.environ[PREFECT_LOGGING_TO_API_ENABLED] == "False"
        assert EXTRA_LOGGERS not in os.environ
        assert PREFECT_HOME not in os.environ

    def test_server_mode_without_api_url_falls_back_to_ephemeral(self, monkeypatch):
        """Server mode without PREFECT_API_URL configures the ephemeral in-memory setup instead."""
        monkeypatch.setenv(PREFECT_MODE, "server")

        set_prefect_env_variables()

        assert os.environ[PREFECT_API_DATABASE_CONNECTION_URL] == "sqlite+aiosqlite:///:memory:"
        assert Path(os.environ[PREFECT_HOME]).is_dir()


class TestCleanUpPrefectHome:
    """Test clean_up_prefect_home."""

    def test_removes_temp_home_in_ephemeral_mode(self, isolated_prefect_env, monkeypatch):
        """The prefixed temp home is deleted when running ephemerally."""
        home = isolated_prefect_env / f"{PREFECT_HOME_PREFIX}abc"
        (home / "nested").mkdir(parents=True)
        monkeypatch.setenv(PREFECT_HOME, str(home))

        clean_up_prefect_home()

        assert not home.exists()

    def test_keeps_home_in_debug_mode(self, isolated_prefect_env, monkeypatch):
        """PREFECT_DEBUG keeps the home directory for later inspection."""
        home = isolated_prefect_env / f"{PREFECT_HOME_PREFIX}abc"
        home.mkdir()
        monkeypatch.setenv(PREFECT_HOME, str(home))
        monkeypatch.setenv(PREFECT_DEBUG, "true")

        clean_up_prefect_home()

        assert home.exists()

    def test_skips_cleanup_in_server_mode(self, isolated_prefect_env, monkeypatch):
        """Server mode never deletes the home directory."""
        home = isolated_prefect_env / f"{PREFECT_HOME_PREFIX}abc"
        home.mkdir()
        monkeypatch.setenv(PREFECT_HOME, str(home))
        monkeypatch.setenv(PREFECT_MODE, "server")

        clean_up_prefect_home()

        assert home.exists()

    def test_without_prefect_home_does_nothing(self, monkeypatch):
        """No PREFECT_HOME means there is nothing to remove."""
        calls = []
        monkeypatch.setattr(prefect_config, "_safe_rmtree", lambda **kwargs: calls.append(kwargs))

        clean_up_prefect_home()

        assert calls == []


class TestSafeRmtree:
    """Test the _safe_rmtree guards."""

    def test_refuses_path_outside_temp_dir(self, tmp_path):
        """Directories outside the system temp dir are never deleted."""
        outside = tmp_path / f"{PREFECT_HOME_PREFIX}outside"
        outside.mkdir()

        assert _safe_rmtree(path=str(outside), prefix=PREFECT_HOME_PREFIX) is False
        assert outside.exists()

    def test_refuses_directory_without_prefix(self, isolated_prefect_env):
        """A directory inside the temp dir is kept when its name lacks the prefix."""
        other = isolated_prefect_env / "unrelated"
        other.mkdir()

        assert _safe_rmtree(path=str(other), prefix=PREFECT_HOME_PREFIX) is False
        assert other.exists()

    def test_removes_directory_without_prefix_requirement(self, isolated_prefect_env):
        """Without a prefix, any directory inside the temp dir is removed."""
        target = isolated_prefect_env / "anything"
        target.mkdir()

        assert _safe_rmtree(path=str(target)) is True
        assert not target.exists()

    def test_missing_directory_returns_false(self, isolated_prefect_env):
        """A path that does not exist is reported as not removed."""
        missing = isolated_prefect_env / f"{PREFECT_HOME_PREFIX}gone"

        assert _safe_rmtree(path=str(missing), prefix=PREFECT_HOME_PREFIX) is False
