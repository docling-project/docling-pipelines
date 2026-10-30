# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Tests for ContentStorageFactory, get_default_factory(), get_report_storage(),
and the register_content_storage decorator.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

import docpipe.core.job_management.adapters.config.report_storage_factory as _factory_mod
from docpipe.core.job_management.adapters.config.report_storage_factory import (
    ContentStorageFactory,
    get_default_factory,
    get_report_storage,
    register_content_storage,
    reset_report_storage,
)
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.storage.file_system.content_file_system_storage import ContentFileSystemStorage
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_all():
    """Reset the module singleton and DocpipeConfigLoader before and after each test."""
    reset_report_storage()
    DocpipeConfigLoader.reset()
    yield
    reset_report_storage()
    DocpipeConfigLoader.reset()


@pytest.fixture(autouse=True)
def restore_registry():
    """
    Restore the ContentStorageFactory registry to its original state after
    each test so that custom backends registered in one test do not bleed
    into the next.
    """
    original = dict(ContentStorageFactory._stores)
    yield
    ContentStorageFactory._stores.clear()
    ContentStorageFactory._stores.update(original)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_backend(*, backend_name: str) -> type:
    """Return a minimal ContentStoragePort subclass with STORAGE_BACKEND set."""

    class _MockStorage:
        STORAGE_BACKEND = backend_name

        def __init__(self, *, base_dir: str) -> None:
            self.base_dir = base_dir

    return _MockStorage


# ---------------------------------------------------------------------------
# ContentStorageFactory.register()
# ---------------------------------------------------------------------------


class TestContentStorageFactoryRegister:
    """Tests for the class-level adapter registry."""

    def test_register_stores_class_by_backend_name(self):
        """register() maps STORAGE_BACKEND → class."""
        mock_backend = _make_mock_backend(backend_name="mock_fs")
        ContentStorageFactory.register(mock_backend)

        assert "mock_fs" in ContentStorageFactory.list_storage_types()

    def test_register_raises_type_error_when_storage_backend_missing(self):
        """register() raises TypeError when the class lacks STORAGE_BACKEND."""

        class BadBackend:
            pass

        with pytest.raises(TypeError, match="must define STORAGE_BACKEND"):
            ContentStorageFactory.register(BadBackend)

    def test_register_returns_class_unchanged(self):
        """register() returns the same class it was given (supports decorator chaining)."""
        mock_backend = _make_mock_backend(backend_name="ret_test")
        result = ContentStorageFactory.register(mock_backend)

        assert result is mock_backend

    def test_register_overwrites_duplicate_backend_name(self):
        """Registering the same backend name a second time overwrites the first."""
        first = _make_mock_backend(backend_name="dup_backend")
        second = _make_mock_backend(backend_name="dup_backend")

        ContentStorageFactory.register(first)
        ContentStorageFactory.register(second)

        assert ContentStorageFactory._stores["dup_backend"] is second

    def test_filesystem_backend_registered_by_default(self):
        """The built-in 'filesystem' backend is present in the initial registry."""
        assert "filesystem" in ContentStorageFactory.list_storage_types()
        assert ContentStorageFactory._stores["filesystem"] is ContentFileSystemStorage

    def test_clear_registry_empties_stores(self):
        """clear_registry() removes all registered backends."""
        ContentStorageFactory.clear_registry()

        assert ContentStorageFactory.list_storage_types() == []


# ---------------------------------------------------------------------------
# register_content_storage decorator
# ---------------------------------------------------------------------------


class TestRegisterContentStorageDecorator:
    """Tests for the module-level @register_content_storage decorator."""

    def test_decorator_registers_backend(self):
        """@register_content_storage adds the class to the registry."""

        @register_content_storage
        class DecoratedStorage:
            STORAGE_BACKEND = "decorated"

        assert "decorated" in ContentStorageFactory.list_storage_types()


# ---------------------------------------------------------------------------
# ContentStorageFactory.list_storage_types()
# ---------------------------------------------------------------------------


class TestListStorageTypes:
    """Tests for the list_storage_types() class method."""

    def test_returns_list_of_strings(self):
        result = ContentStorageFactory.list_storage_types()

        assert isinstance(result, list)
        assert all(isinstance(name, str) for name in result)

    def test_includes_registered_custom_backend(self):
        ContentStorageFactory.register(_make_mock_backend(backend_name="listed"))

        assert "listed" in ContentStorageFactory.list_storage_types()


# ---------------------------------------------------------------------------
# ContentStorageFactory.get_store()
# ---------------------------------------------------------------------------


class TestGetStore:
    """Tests for instance-level get_store()."""

    def test_get_store_returns_content_file_system_storage(self, *, tmp_path):
        """get_store() returns a ContentFileSystemStorage for the 'filesystem' type."""
        factory = ContentStorageFactory(storage_type="filesystem", config={"data_root": str(tmp_path)})

        store = factory.get_store()

        assert isinstance(store, ContentFileSystemStorage)

    def test_get_store_is_singleton(self, *, tmp_path):
        """Repeated calls to get_store() return the identical object."""
        factory = ContentStorageFactory(storage_type="filesystem", config={"data_root": str(tmp_path)})

        assert factory.get_store() is factory.get_store()

    def test_get_store_raises_for_unknown_backend(self):
        """get_store() raises DocpipeException for an unregistered storage type."""
        factory = ContentStorageFactory(storage_type="nonexistent_backend")

        with pytest.raises(DocpipeException, match="Unknown report content storage backend"):
            factory.get_store()

    def test_get_store_error_message_lists_available_backends(self):
        """The error message for an unknown backend lists the available backends."""
        factory = ContentStorageFactory(storage_type="nonexistent_backend")

        with pytest.raises(DocpipeException, match="filesystem"):
            factory.get_store()


# ---------------------------------------------------------------------------
# ContentStorageFactory.create_default_factory()
# ---------------------------------------------------------------------------


class TestCreateDefaultFactory:
    """Tests for the classmethod create_default_factory()."""

    def test_returns_factory_instance_with_no_config_file(self, *, tmp_path, monkeypatch):
        """Falls back to 'filesystem' (default) when no config file exists."""
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "absent.yaml"))

        factory = ContentStorageFactory.create_default_factory()

        assert isinstance(factory, ContentStorageFactory)
        assert factory._storage_type == "filesystem"

    def test_reads_storage_type_from_service_specific_config(self, *, tmp_path, monkeypatch):
        """Service-specific job_run_report.storage.type overrides the default."""
        mock_backend = _make_mock_backend(backend_name="custom_type")
        ContentStorageFactory.register(mock_backend)

        config_data = {"job_run_report": {"storage": {"type": "custom_type", "config": {"data_root": str(tmp_path)}}}}
        config_path = tmp_path / "config.yaml"
        with Path(config_path).open("w") as f:
            yaml.dump(config_data, f)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        factory = ContentStorageFactory.create_default_factory()

        assert factory._storage_type == "custom_type"

    def test_reads_storage_type_from_global_storage_fallback(self, *, tmp_path, monkeypatch):
        """global_storage.type is used when no service-specific block exists."""
        config_data = {"global_storage": {"type": "filesystem", "config": {}}}
        config_path = tmp_path / "config.yaml"
        with Path(config_path).open("w") as f:
            yaml.dump(config_data, f)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        factory = ContentStorageFactory.create_default_factory()

        assert factory._storage_type == "filesystem"

    def test_raises_docpipe_exception_for_invalid_storage_type(self, *, tmp_path, monkeypatch):
        """create_default_factory() raises DocpipeException for an unregistered type."""
        config_data = {"job_run_report": {"storage": {"type": "totally_unknown_backend"}}}
        config_path = tmp_path / "config.yaml"
        with Path(config_path).open("w") as f:
            yaml.dump(config_data, f)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        with pytest.raises(DocpipeException, match="Invalid storage type"):
            ContentStorageFactory.create_default_factory()

    def test_error_message_lists_available_backends_when_invalid_type(self, *, tmp_path, monkeypatch):
        """The error from create_default_factory lists 'filesystem' as available."""
        config_data = {"job_run_report": {"storage": {"type": "unknown_backend"}}}
        config_path = tmp_path / "config.yaml"
        with Path(config_path).open("w") as f:
            yaml.dump(config_data, f)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        with pytest.raises(DocpipeException, match="filesystem"):
            ContentStorageFactory.create_default_factory()

    def test_storage_config_forwarded_to_factory_instance(self, *, tmp_path, monkeypatch):
        """Sub-keys inside storage.config are stored in the factory _config."""
        config_data = {
            "job_run_report": {
                "storage": {
                    "type": "filesystem",
                    "config": {"data_root": str(tmp_path)},
                }
            }
        }
        config_path = tmp_path / "config.yaml"
        with Path(config_path).open("w") as f:
            yaml.dump(config_data, f)
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        factory = ContentStorageFactory.create_default_factory()

        assert factory._config.get("data_root") == str(tmp_path)


# ---------------------------------------------------------------------------
# get_default_factory() module-level singleton
# ---------------------------------------------------------------------------


class TestGetDefaultFactory:
    """Tests for the module-level get_default_factory() singleton."""

    def test_returns_content_storage_factory_instance(self, *, tmp_path, monkeypatch):
        """get_default_factory() returns a ContentStorageFactory."""
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "absent.yaml"))
        monkeypatch.setattr(_factory_mod, "_default_factory", None)

        factory = get_default_factory()

        assert isinstance(factory, ContentStorageFactory)

    def test_returns_same_instance_on_repeated_calls(self, *, tmp_path, monkeypatch):
        """get_default_factory() is a singleton — repeated calls return the same object."""
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "absent.yaml"))
        monkeypatch.setattr(_factory_mod, "_default_factory", None)

        assert get_default_factory() is get_default_factory()

    def test_reset_report_storage_clears_singleton(self, *, tmp_path, monkeypatch):
        """reset_report_storage() forces get_default_factory() to rebuild the singleton."""
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "absent.yaml"))
        monkeypatch.setattr(_factory_mod, "_default_factory", None)

        first = get_default_factory()
        reset_report_storage()

        # After reset the singleton is None, so next call creates a new instance.
        assert _factory_mod._default_factory is None
        second = get_default_factory()
        assert first is not second


# ---------------------------------------------------------------------------
# get_report_storage() convenience function
# ---------------------------------------------------------------------------


class TestGetReportStorage:
    """Tests for the get_report_storage() convenience function."""

    def test_returns_content_storage_port_instance(self, *, tmp_path, monkeypatch):
        """get_report_storage() returns a ContentStoragePort implementation."""
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "absent.yaml"))
        monkeypatch.setattr(_factory_mod, "_default_factory", None)

        from docpipe.storage.interfaces.content_storage_port import ContentStoragePort

        store = get_report_storage()

        assert isinstance(store, ContentStoragePort)

    def test_returns_same_store_on_repeated_calls(self, *, tmp_path, monkeypatch):
        """get_report_storage() is a singleton."""
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "absent.yaml"))
        monkeypatch.setattr(_factory_mod, "_default_factory", None)

        assert get_report_storage() is get_report_storage()

    def test_delegates_to_get_default_factory(self, *, tmp_path, monkeypatch):
        """get_report_storage() calls get_default_factory().get_store()."""
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "absent.yaml"))

        mock_store = MagicMock()
        mock_factory = MagicMock()
        mock_factory.get_store.return_value = mock_store
        monkeypatch.setattr(_factory_mod, "_default_factory", mock_factory)

        result = get_report_storage()

        mock_factory.get_store.assert_called_once()
        assert result is mock_store


# ---------------------------------------------------------------------------
# ContentStorageFactory — edge cases
# ---------------------------------------------------------------------------


class TestContentStorageFactoryEdgeCases:
    """Edge-case and defensive tests."""

    def test_empty_config_defaults_to_empty_dict(self, *, tmp_path):
        """Passing config=None is equivalent to passing an empty dict."""
        factory = ContentStorageFactory(storage_type="filesystem", config=None)

        # _config should default to {} (not None)
        assert factory._config == {}

    def test_get_store_error_when_registry_cleared(self):
        """get_store() raises DocpipeException listing 'none' when registry is empty."""
        ContentStorageFactory.clear_registry()
        factory = ContentStorageFactory(storage_type="filesystem")

        with pytest.raises(DocpipeException, match="none"):
            factory.get_store()

    def test_create_default_factory_raises_when_registry_empty_and_type_resolved(self, *, tmp_path, monkeypatch):
        """create_default_factory() raises DocpipeException when the registry is cleared."""
        ContentStorageFactory.clear_registry()
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "absent.yaml"))

        with pytest.raises(DocpipeException, match="Invalid storage type"):
            ContentStorageFactory.create_default_factory()
