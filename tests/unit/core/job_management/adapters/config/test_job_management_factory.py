# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Tests for JobManagementFactory configuration and store selection.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

import docpipe.core.job_management.adapters.config.job_management_factory as _factory_mod
from docpipe.core.job_management.adapters.config import JobManagementFactory, StorageBackend
from docpipe.core.job_management.adapters.config.job_management_factory import FrameworkType, get_default_factory
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader


@pytest.fixture(autouse=True)
def reset_config_loader():
    """Clear the DocpipeConfigLoader cache before and after each test."""
    DocpipeConfigLoader.reset()
    yield
    DocpipeConfigLoader.reset()


class TestJobManagementFactoryStoreSelection:
    """Test factory store selection logic."""

    def test_inmemory_store_creation(self):
        """Test InMemoryJobStatsStore creation."""
        factory = JobManagementFactory(storage_backend=StorageBackend.IN_MEMORY)
        store = factory.create_job_stats_store()

        assert store is not None
        assert store.__class__.__name__ == "InMemoryJobStatsStore"

    def test_filesystem_store_creation(self):
        """Test JsonJobStatsStore creation."""
        factory = JobManagementFactory(storage_backend=StorageBackend.FILESYSTEM)
        store = factory.create_job_stats_store()

        assert store is not None
        assert store.__class__.__name__ == "JsonJobStatsStore"

    @patch("docpipe.core.job_management.adapters.config.job_management_factory.run_migrations")
    @patch("docpipe.core.job_management.adapters.stores.postgres.postgres_job_stats_store.create_session_factory")
    @patch("docpipe.core.job_management.adapters.stores.postgres.postgres_job_stats_store.create_postgres_engine")
    @patch(
        "docpipe.core.job_management.adapters.stores.postgres.postgres_job_stats_store.get_postgres_connection_string"
    )
    def test_postgresql_store_creation_with_config(
        self, mock_conn_string, mock_engine, mock_session_factory, mock_run_migrations
    ):
        """Test PostgresJobStatsStore creation with config."""
        # Mock successful PostgreSQL setup
        mock_conn_string.return_value = (
            "postgresql+psycopg2://user:pass@localhost:5432/docpipe"  # pragma: allowlist secret
        )
        mock_engine_instance = MagicMock()
        mock_engine.return_value = mock_engine_instance
        mock_session_factory.return_value = MagicMock()

        config = {
            "postgres": {
                "host": "localhost",
                "port": 5432,
                "database": "docpipe",
                "user": "test_user",
                "password": "test_password",  # pragma: allowlist secret
            }
        }

        factory = JobManagementFactory(storage_backend=StorageBackend.POSTGRESQL, config=config)
        store = factory.create_job_stats_store()

        assert store is not None
        assert store.__class__.__name__ == "PostgresJobStatsStore"
        mock_conn_string.assert_called_once_with(config=config)
        mock_engine.assert_called_once()
        mock_session_factory.assert_called_once_with(engine=mock_engine_instance)

    def test_postgresql_store_creation_without_password_raises_error(self):
        """Test PostgresJobStatsStore creation fails without password."""
        factory = JobManagementFactory(storage_backend=StorageBackend.POSTGRESQL)

        from docpipe.exceptions.docpipe_exceptions import (
            JobStatsStoreInitializationException,
        )

        with pytest.raises(
            JobStatsStoreInitializationException,
            match="PostgreSQL connection not configured",
        ):
            factory.create_job_stats_store()

    def test_singleton_behavior(self):
        """Test that factory returns same store instance."""
        factory = JobManagementFactory(storage_backend=StorageBackend.IN_MEMORY)

        store1 = factory.create_job_stats_store()
        store2 = factory.create_job_stats_store()

        assert store1 is store2


class TestCreateDefaultFactory:
    """Tests for JobManagementFactory.create_default_factory()."""

    def test_creates_inmemory_factory_when_no_config(self, *, tmp_path, monkeypatch):
        """Falls back to 'inmemory' storage (nothing persisted) when no config file exists."""
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "absent.yaml"))

        factory = JobManagementFactory.create_default_factory()

        assert factory.storage_backend == StorageBackend.IN_MEMORY

    def test_creates_inmemory_factory_when_config_has_no_storage(self, *, tmp_path, monkeypatch):
        """A config with no job_management storage and no global_storage still defaults to 'inmemory'."""
        config_path = tmp_path / "config.yaml"
        with Path(config_path).open("w") as f:
            yaml.dump({"job_management": {"framework": {"type": "default"}}}, f)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        factory = JobManagementFactory.create_default_factory()

        assert factory.storage_backend == StorageBackend.IN_MEMORY

    def test_explicit_filesystem_storage_is_still_honoured(self, *, tmp_path, monkeypatch):
        """The inmemory default applies only when nothing is configured."""
        config_path = tmp_path / "config.yaml"
        with Path(config_path).open("w") as f:
            yaml.dump({"job_management": {"storage": {"type": "filesystem"}}}, f)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        factory = JobManagementFactory.create_default_factory()

        assert factory.storage_backend == StorageBackend.FILESYSTEM

    def test_reads_storage_backend_from_service_specific_config(self, *, tmp_path, monkeypatch):
        """Service-specific storage type is used to create the factory."""
        config_data = {
            "job_management": {
                "storage": {"type": "inmemory"},
                "framework": {"type": "default"},
            }
        }
        config_path = tmp_path / "config.yaml"
        with Path(config_path).open("w") as f:
            yaml.dump(config_data, f)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        factory = JobManagementFactory.create_default_factory()

        assert factory.storage_backend == StorageBackend.IN_MEMORY

    def test_reads_storage_backend_from_global_storage_fallback(self, *, tmp_path, monkeypatch):
        """Falls back to global_storage when no service-specific storage block."""
        config_data = {
            "global_storage": {"type": "inmemory", "config": {}},
            "job_management": {"framework": {"type": "default"}},
        }
        config_path = tmp_path / "config.yaml"
        with Path(config_path).open("w") as f:
            yaml.dump(config_data, f)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        factory = JobManagementFactory.create_default_factory()

        assert factory.storage_backend == StorageBackend.IN_MEMORY

    def test_reads_framework_type_from_config(self, *, tmp_path, monkeypatch):
        """Framework type from the config file is correctly parsed."""
        config_data = {
            "job_management": {
                "storage": {"type": "inmemory"},
                "framework": {"type": "default"},
            }
        }
        config_path = tmp_path / "config.yaml"
        with Path(config_path).open("w") as f:
            yaml.dump(config_data, f)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        factory = JobManagementFactory.create_default_factory()

        assert factory.framework_type == FrameworkType.DEFAULT

    def test_raises_value_error_for_invalid_storage_backend(self, *, tmp_path, monkeypatch):
        """Invalid storage backend value raises ValueError."""
        config_data = {
            "job_management": {
                "storage": {"type": "not_a_valid_backend"},
            }
        }
        config_path = tmp_path / "config.yaml"
        with Path(config_path).open("w") as f:
            yaml.dump(config_data, f)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        with pytest.raises(ValueError, match="Invalid storage backend 'not_a_valid_backend'"):
            JobManagementFactory.create_default_factory()

    def test_raises_value_error_for_invalid_framework_type(self, *, tmp_path, monkeypatch):
        """Invalid framework type value raises ValueError."""
        config_data = {
            "job_management": {
                "storage": {"type": "inmemory"},
                "framework": {"type": "not_a_valid_framework"},
            }
        }
        config_path = tmp_path / "config.yaml"
        with Path(config_path).open("w") as f:
            yaml.dump(config_data, f)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        with pytest.raises(ValueError, match="Invalid framework type"):
            JobManagementFactory.create_default_factory()

    def test_storage_config_stored_in_merged_config(self, *, tmp_path, monkeypatch):
        """Storage config keys are merged flat (top level) into the factory config."""
        config_data = {
            "job_management": {
                "storage": {"type": "inmemory", "config": {"base_dir": "/tmp/custom-jobs", "lock_timeout": 7}},
                "framework": {"type": "default"},
            }
        }
        config_path = tmp_path / "config.yaml"
        with Path(config_path).open("w") as f:
            yaml.dump(config_data, f)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        factory = JobManagementFactory.create_default_factory()

        # store factories read these from the top level of self.config
        assert factory.config.get("base_dir") == "/tmp/custom-jobs"
        assert factory.config.get("lock_timeout") == 7
        assert "storage" not in factory.config


class TestGetDefaultFactoryJobManagement:
    """Tests for the module-level get_default_factory() singleton."""

    def test_returns_factory_instance(self, *, tmp_path, monkeypatch):
        """get_default_factory() returns a JobManagementFactory."""
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "absent.yaml"))
        monkeypatch.setattr(_factory_mod, "_default_factory", None)

        factory = get_default_factory()

        assert isinstance(factory, JobManagementFactory)

    def test_returns_same_instance_on_repeated_calls(self, *, tmp_path, monkeypatch):
        """get_default_factory() is a singleton — repeated calls return the same object."""
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "absent.yaml"))
        monkeypatch.setattr(_factory_mod, "_default_factory", None)

        assert get_default_factory() is get_default_factory()


# =======
#     def test_from_environment_invalid_backend_raises_error(self):
#         """Test invalid storage backend raises ValueError."""
#         with patch.dict(os.environ, {"DOCPIPE_STORAGE_BACKEND": "invalid_backend"}):
#             with pytest.raises(ValueError, match="Invalid DOCPIPE_STORAGE_BACKEND"):
#                 JobManagementFactory.from_environment()


class TestJobManagementFactoryInitializeStorage:
    """Tests for initialize_storage() and resolve_worker_env() to boost coverage."""

    def test_initialize_storage_noop_for_non_postgresql(self):
        """initialize_storage does nothing for non-PostgreSQL backends."""
        factory = JobManagementFactory(storage_backend=StorageBackend.IN_MEMORY)
        # Should not raise — just returns immediately
        factory.initialize_storage()

    def test_initialize_storage_skips_when_already_initialized(self):
        """initialize_storage skips if STORAGE_INITIALIZED flag is set."""
        factory = JobManagementFactory(
            storage_backend=StorageBackend.POSTGRESQL,
            config={"storage_initialized": True},
        )
        factory.initialize_storage()  # should return without calling run_migrations

    @patch("docpipe.core.job_management.adapters.config.job_management_factory.run_migrations")
    @patch("docpipe.core.job_management.adapters.config.job_management_factory.get_postgres_connection_string")
    def test_initialize_storage_skips_migrations_when_no_connection_string(self, mock_conn_str, mock_migrations):
        """initialize_storage exits early when connection string is empty."""
        mock_conn_str.return_value = ""
        factory = JobManagementFactory(storage_backend=StorageBackend.POSTGRESQL)
        factory.initialize_storage()
        mock_migrations.assert_not_called()

    @patch("docpipe.core.job_management.adapters.config.job_management_factory.run_migrations")
    @patch("docpipe.core.job_management.adapters.config.job_management_factory.get_postgres_connection_string")
    def test_initialize_storage_skips_migrations_when_disabled(self, mock_conn_str, mock_migrations):
        """initialize_storage skips migrations when run_migrations=False."""
        mock_conn_str.return_value = "postgresql://user:pass@localhost/db"  # pragma: allowlist secret
        factory = JobManagementFactory(
            storage_backend=StorageBackend.POSTGRESQL,
            config={"run_migrations": False},
        )
        factory.initialize_storage()
        mock_migrations.assert_not_called()

    def test_resolve_worker_env_includes_backend_and_framework(self):
        """resolve_worker_env always includes storage backend and framework type."""
        factory = JobManagementFactory(storage_backend=StorageBackend.IN_MEMORY)
        env = factory.resolve_worker_env()
        assert "DOCPIPE_STORAGE_BACKEND" in env
        assert "DOCPIPE_FRAMEWORK_TYPE" in env

    # def test_resolve_worker_env_filesystem_with_env_override(self):
    #     """resolve_worker_env picks up ENV_JOB_STATS_BASE_DIR_KEY for filesystem backend."""
    #     factory = JobManagementFactory(storage_backend=StorageBackend.FILESYSTEM)
    #     with patch.dict(os.environ, {"DOCPIPE_JOB_STATS_BASE_DIR": "/data/jobs"}):
    #         env = factory.resolve_worker_env()
    #     assert "DOCPIPE_STORAGE_BACKEND" in env

    def test_resolve_worker_env_postgresql_includes_connection_params(self):
        """resolve_worker_env includes postgres params when configured."""
        config = {
            "postgres": {
                "host": "localhost",
                "port": "5432",
                "database": "docpipe",
                "user": "admin",
                "password": "secret",  # pragma: allowlist secret
            }
        }
        factory = JobManagementFactory(storage_backend=StorageBackend.POSTGRESQL, config=config)
        env = factory.resolve_worker_env()
        assert env.get("DOCPIPE_POSTGRES_HOST") == "localhost"


class TestResolveFilesystemBaseDir:
    """Tests for JobManagementFactory._resolve_filesystem_base_dir."""

    def test_returns_env_override_when_set(self, tmp_path):
        """Environment variable takes priority over config."""
        factory = JobManagementFactory(storage_backend=StorageBackend.FILESYSTEM)
        with patch.dict(os.environ, {"DOCPIPE_JOB_STATS_BASE_DIR": str(tmp_path)}):
            result = factory._resolve_filesystem_base_dir()
        assert result == str(tmp_path)

    def test_returns_absolute_config_path_unchanged(self, tmp_path):
        """Absolute path in config is returned as-is."""
        factory = JobManagementFactory(
            storage_backend=StorageBackend.FILESYSTEM,
            config={"base_dir": str(tmp_path)},
        )
        with patch.dict(os.environ, {}, clear=True):
            result = factory._resolve_filesystem_base_dir()
        assert result == str(tmp_path)

    def test_resolves_relative_config_path(self):
        """Relative path in config is resolved to an absolute path."""
        factory = JobManagementFactory(
            storage_backend=StorageBackend.FILESYSTEM,
            config={"base_dir": "some/relative/path"},
        )
        with patch.dict(os.environ, {}, clear=True):
            result = factory._resolve_filesystem_base_dir()
        assert result is not None
        from pathlib import Path

        assert Path(result).is_absolute()

    def test_returns_none_when_no_config_and_no_env(self):
        """Returns None when neither env var nor config base_dir is set."""
        factory = JobManagementFactory(storage_backend=StorageBackend.FILESYSTEM)
        with patch.dict(os.environ, {}, clear=True):
            result = factory._resolve_filesystem_base_dir()
        assert result is None

    def test_env_override_takes_priority_over_config(self, tmp_path):
        """Env var wins even when config also has a base_dir."""
        env_path = str(tmp_path / "from_env")
        factory = JobManagementFactory(
            storage_backend=StorageBackend.FILESYSTEM,
            config={"base_dir": str(tmp_path / "from_config")},
        )
        with patch.dict(os.environ, {"DOCPIPE_JOB_STATS_BASE_DIR": env_path}):
            result = factory._resolve_filesystem_base_dir()
        assert result == env_path


class TestJobManagementFactory:
    def test_resolve_worker_env_filesystem_with_base_dir(self, tmp_path):
        """FILESYSTEM backend adds DOCPIPE_JOB_STATS_BASE_DIR when base_dir configured."""
        from unittest.mock import patch

        factory = JobManagementFactory(
            storage_backend=StorageBackend.FILESYSTEM,
            config={"base_dir": str(tmp_path)},
        )
        with patch.dict(os.environ, {}, clear=True):
            env = factory.resolve_worker_env()
        assert "DOCPIPE_JOB_STATS_BASE_DIR" in env
        assert env["DOCPIPE_JOB_STATS_BASE_DIR"] == str(tmp_path)
        assert env["DOCPIPE_STORAGE_BACKEND"] == "filesystem"

    def test_resolve_worker_env_filesystem_no_base_dir(self):
        """FILESYSTEM backend omits DOCPIPE_JOB_STATS_BASE_DIR when not configured."""
        from unittest.mock import patch

        factory = JobManagementFactory(storage_backend=StorageBackend.FILESYSTEM)
        with patch.dict(os.environ, {}, clear=True):
            env = factory.resolve_worker_env()
        assert "DOCPIPE_JOB_STATS_BASE_DIR" not in env

    def test_resolve_worker_env_postgresql_from_config(self):
        """POSTGRESQL backend propagates postgres config values into env dict."""
        from unittest.mock import patch

        config = {
            "postgres": {
                "host": "pg-host",
                "port": 5432,
                "database": "mydb",
                "user": "user1",
                "password": "secret",  # pragma: allowlist secret
            }
        }
        factory = JobManagementFactory(storage_backend=StorageBackend.POSTGRESQL, config=config)
        with patch.dict(os.environ, {}, clear=True):
            env = factory.resolve_worker_env()
        assert env.get("DOCPIPE_POSTGRES_HOST") == "pg-host"
        assert env.get("DOCPIPE_POSTGRES_DB") == "mydb"

    def test_resolve_worker_env_postgresql_env_overrides_config(self):
        """Env var beats config value for postgres keys."""
        from unittest.mock import patch

        config = {"postgres": {"host": "config-host"}}
        factory = JobManagementFactory(storage_backend=StorageBackend.POSTGRESQL, config=config)
        with patch.dict(os.environ, {"DOCPIPE_POSTGRES_HOST": "env-host"}, clear=False):
            env = factory.resolve_worker_env()
        assert env.get("DOCPIPE_POSTGRES_HOST") == "env-host"

    @patch("docpipe.core.job_management.adapters.config.job_management_factory.run_migrations")
    @patch("docpipe.core.job_management.adapters.config.job_management_factory.get_postgres_connection_string")
    def test_initialize_storage_skips_migrations_when_disabled(self, mock_conn, mock_migrate):
        """initialize_storage logs skip when run_migrations=False."""
        mock_conn.return_value = "postgresql://user:pass@host/db"  # pragma: allowlist secret
        factory = JobManagementFactory(
            storage_backend=StorageBackend.POSTGRESQL,
            config={"run_migrations": False},
        )
        factory.initialize_storage()
        mock_migrate.assert_not_called()
        assert factory.config.get("storage_initialized") is True
