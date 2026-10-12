# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for IncrementalMetadataFactory."""

from pathlib import Path

import pytest
import yaml

import docpipe.core.incremental_metadata.adapters.config.incremental_metadata_factory as _factory_mod
from docpipe.core.incremental_metadata.adapters.config.incremental_metadata_factory import (
    IncrementalMetadataFactory,
    get_default_factory,
)
from docpipe.core.incremental_metadata.adapters.stores.filesystem import FilesystemIncrementalMetadataStore
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.utils.infrastructure.config_utils import DocpipeConfigLoader


@pytest.fixture(autouse=True)
def reset_config_loader():
    """Clear the DocpipeConfigLoader cache before and after each test."""
    DocpipeConfigLoader.reset()
    yield
    DocpipeConfigLoader.reset()


class TestIncrementalMetadataFactory:
    """Test IncrementalMetadataFactory registry and get_store()."""

    def test_create_filesystem_store(self, *, tmp_path):
        """Test creating a filesystem store via the factory instance."""
        factory = IncrementalMetadataFactory(storage_type="filesystem", config={"base_dir": str(tmp_path)})
        store = factory.get_store()

        assert isinstance(store, FilesystemIncrementalMetadataStore)
        assert store._base_dir == tmp_path

    def test_create_store_with_lock_timeout(self, *, tmp_path):
        """Test that config is passed through to the store."""
        factory = IncrementalMetadataFactory(
            storage_type="filesystem", config={"base_dir": str(tmp_path), "lock_timeout": 10.0}
        )
        store = factory.get_store()

        assert isinstance(store, FilesystemIncrementalMetadataStore)
        assert store._lock_timeout == 10.0

    def test_get_store_returns_singleton(self, *, tmp_path):
        """get_store() returns the same instance on repeated calls."""
        factory = IncrementalMetadataFactory(storage_type="filesystem", config={"base_dir": str(tmp_path)})

        assert factory.get_store() is factory.get_store()

    def test_get_service_returns_singleton(self, *, tmp_path):
        """get_service() returns the same instance on repeated calls."""
        factory = IncrementalMetadataFactory(storage_type="filesystem", config={"base_dir": str(tmp_path)})

        assert factory.get_service() is factory.get_service()

    def test_create_unknown_backend_raises_error(self):
        """Test that get_store() with an unknown backend raises DocpipeException."""
        from docpipe.exceptions.docpipe_exceptions import DocpipeException

        factory = IncrementalMetadataFactory(storage_type="duckdb")
        with pytest.raises(DocpipeException, match="Unknown incremental metadata store backend"):
            factory.get_store()

    def test_list_backends_contains_registered(self):
        """Test that registered backends appear in list_backends()."""
        backends = IncrementalMetadataFactory.list_backends()
        assert "filesystem" in backends
        assert "postgresql" in backends


class TestGetDefaultFactory:
    """Test the process-wide singleton get_default_factory()."""

    def test_returns_filesystem_store_from_config(self, *, tmp_path, monkeypatch):
        """Singleton factory creates store from YAML config."""
        config_path = tmp_path / "config.yaml"
        config_data = {
            "incremental_metadata": {
                "storage": {"type": "filesystem", "config": {"base_dir": str(tmp_path / "metadata")}}
            }
        }
        with Path(config_path).open("w") as f:
            yaml.dump(config_data, f)

        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))
        monkeypatch.setattr(_factory_mod, "_default_factory", None)

        store = get_default_factory().get_store()

        assert isinstance(store, FilesystemIncrementalMetadataStore)

    def test_caching_returns_same_factory_instance(self, *, monkeypatch):
        """Repeated calls to get_default_factory() return the same instance."""
        monkeypatch.delenv("DOCPIPE_CONFIG_PATH", raising=False)
        monkeypatch.setattr(_factory_mod, "_default_factory", None)

        assert get_default_factory() is get_default_factory()

    def test_store_singleton_across_calls(self, *, monkeypatch):
        """get_store() on the singleton factory always returns the same store."""
        monkeypatch.delenv("DOCPIPE_CONFIG_PATH", raising=False)
        monkeypatch.setattr(_factory_mod, "_default_factory", None)

        store_a = get_default_factory().get_store()
        store_b = get_default_factory().get_store()

        assert store_a is store_b


class TestCreateDefaultFactory:
    """Tests for IncrementalMetadataFactory.create_default_factory()."""

    def test_creates_filesystem_store_from_service_specific_config(self, *, tmp_path, monkeypatch):
        """create_default_factory() uses service-specific storage config."""
        config_data = {
            "incremental_metadata": {
                "storage": {"type": "filesystem", "config": {"base_dir": str(tmp_path / "metadata")}}
            }
        }
        config_path = tmp_path / "config.yaml"
        with Path(config_path).open("w") as f:
            yaml.dump(config_data, f)

        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))
        monkeypatch.setattr(_factory_mod, "_default_factory", None)

        factory = IncrementalMetadataFactory.create_default_factory()
        store = factory.get_store()

        assert isinstance(store, FilesystemIncrementalMetadataStore)

    def test_creates_filesystem_store_from_global_storage_fallback(self, *, tmp_path, monkeypatch):
        """create_default_factory() falls back to global_storage when no service-specific block."""
        config_data = {"global_storage": {"type": "filesystem", "config": {"base_dir": str(tmp_path / "global")}}}
        config_path = tmp_path / "config.yaml"
        with Path(config_path).open("w") as f:
            yaml.dump(config_data, f)

        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))
        monkeypatch.setattr(_factory_mod, "_default_factory", None)

        factory = IncrementalMetadataFactory.create_default_factory()
        store = factory.get_store()

        assert isinstance(store, FilesystemIncrementalMetadataStore)

    def test_creates_filesystem_store_when_no_config_file(self, *, tmp_path, monkeypatch):
        """create_default_factory() falls back to 'filesystem' default when config is absent."""
        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "absent.yaml"))
        monkeypatch.setattr(_factory_mod, "_default_factory", None)

        factory = IncrementalMetadataFactory.create_default_factory()
        store = factory.get_store()

        assert isinstance(store, FilesystemIncrementalMetadataStore)

    def test_raises_docpipe_exception_for_unregistered_storage_type(self, *, tmp_path, monkeypatch):
        """create_default_factory() raises DocpipeException when storage type is not registered."""
        config_data = {"incremental_metadata": {"storage": {"type": "unknown_backend"}}}
        config_path = tmp_path / "config.yaml"
        with Path(config_path).open("w") as f:
            yaml.dump(config_data, f)

        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        with pytest.raises(DocpipeException, match="Invalid storage type 'unknown_backend'"):
            IncrementalMetadataFactory.create_default_factory()

    def test_storage_type_stored_on_instance(self, *, tmp_path, monkeypatch):
        """Factory instance has the storage_type attribute set correctly."""
        config_data = {"incremental_metadata": {"storage": {"type": "filesystem", "config": {}}}}
        config_path = tmp_path / "config.yaml"
        with Path(config_path).open("w") as f:
            yaml.dump(config_data, f)

        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        factory = IncrementalMetadataFactory.create_default_factory()

        assert factory._storage_type == "filesystem"

    def test_config_passed_through_to_store(self, *, tmp_path, monkeypatch):
        """Config dict from YAML is forwarded to the store constructor."""
        store_dir = tmp_path / "store"
        config_data = {
            "incremental_metadata": {
                "storage": {
                    "type": "filesystem",
                    "config": {"base_dir": str(store_dir), "lock_timeout": 5.0},
                }
            }
        }
        config_path = tmp_path / "config.yaml"
        with Path(config_path).open("w") as f:
            yaml.dump(config_data, f)

        monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(config_path))

        factory = IncrementalMetadataFactory.create_default_factory()
        store = factory.get_store()

        assert isinstance(store, FilesystemIncrementalMetadataStore)
        assert store._lock_timeout == 5.0
