# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for document set factories."""

from unittest.mock import MagicMock, patch

import pytest

import docpipe.core.assets.document_sets.adapters.duckdb  # noqa: F401
from docpipe.core.assets.common.factories.asset_repository_factory import AssetRepositoryFactory
from docpipe.core.assets.document_sets.domain.models.document_set import DocumentSet
from docpipe.core.assets.document_sets.domain.types import DataStoreConfig
from docpipe.core.assets.document_sets.factories import DataStoreFactory
from docpipe.exceptions.docpipe_exceptions import DocpipeException, RepositoryConfigurationException


class TestRepositoryFactoryDocumentSet:
    """Test RepositoryFactory for DocumentSet — replaces TestMetadataRepositoryFactory."""

    def test_create_duckdb_repository(self, tmp_path):
        """Test creating DuckDB repository via RepositoryFactory."""
        import os

        os.environ["DOCPIPE_CONFIG_PATH"] = str(tmp_path / "nonexistent.yaml")
        # Without YAML the factory falls back to DUCKDB default for documentset
        # We need to point it at a real db path — use adapter_name override + env
        os.environ["DOCUMENTSET_REPOSITORY_TYPE"] = "duckdb"
        os.environ["DOCUMENTSET_REPOSITORY_BASE_DIR"] = str(tmp_path / "test.db")
        try:
            # Provide a valid database_path via env override mechanism
            # Use from_config directly to keep the test self-contained
            from docpipe.core.assets.common.adapters.repositories.duckdb_asset_repository import (
                DuckDBAssetRepository,
            )

            repository = DuckDBAssetRepository.from_config(
                asset_type=DocumentSet,
                config={"database_path": str(tmp_path / "test.db")},
            )
            assert repository is not None
            assert hasattr(repository, "save")
            assert hasattr(repository, "find_by_id")
            assert hasattr(repository, "update")
            assert hasattr(repository, "delete")
            assert repository._collection == "document_sets"
        finally:
            os.environ.pop("DOCUMENTSET_REPOSITORY_TYPE", None)
            os.environ.pop("DOCUMENTSET_REPOSITORY_BASE_DIR", None)
            os.environ.pop("DOCPIPE_CONFIG_PATH", None)

    def test_create_duckdb_repository_memory(self):
        """Test creating DuckDB repository with in-memory database."""
        from docpipe.core.assets.common.adapters.repositories.duckdb_asset_repository import (
            DuckDBAssetRepository,
        )

        repository = DuckDBAssetRepository.from_config(
            asset_type=DocumentSet,
            config={"database_path": ":memory:"},
        )
        assert repository is not None
        assert repository._collection == "document_sets"

    def test_collection_name_is_document_sets(self):
        """collection must be 'document_sets', not the auto-generated 'documentsets'."""
        from docpipe.core.assets.common.adapters.repositories.duckdb_asset_repository import (
            DuckDBAssetRepository,
        )

        repo = DuckDBAssetRepository.from_config(asset_type=DocumentSet, config={"database_path": ":memory:"})
        assert repo._collection == "document_sets"

    def test_create_unknown_adapter_raises(self):
        """RepositoryFactory raises for unknown adapter type."""
        with pytest.raises(RepositoryConfigurationException):
            AssetRepositoryFactory.create_repository(asset_type=DocumentSet, adapter_name="unknown_adapter")

    def test_invalid_config_missing_path_raises(self):
        """DuckDBAssetRepository.from_config raises for missing database_path."""
        from docpipe.core.assets.common.adapters.repositories.duckdb_asset_repository import (
            DuckDBAssetRepository,
        )

        with pytest.raises(DocpipeException) as exc_info:
            DuckDBAssetRepository.from_config(asset_type=DocumentSet, config={})
        assert exc_info.value.status_code == 400
        assert "database_path" in str(exc_info.value).lower()

    def test_invalid_config_empty_path_raises(self):
        """DuckDBAssetRepository.from_config raises for empty database_path."""
        from docpipe.core.assets.common.adapters.repositories.duckdb_asset_repository import (
            DuckDBAssetRepository,
        )

        with pytest.raises(DocpipeException) as exc_info:
            DuckDBAssetRepository.from_config(asset_type=DocumentSet, config={"database_path": ""})
        assert exc_info.value.status_code == 400


class TestDataStoreFactory:
    """Test DataStoreFactory."""

    def test_list_adapters(self):
        """Test listing registered adapters."""
        adapters = DataStoreFactory.list_adapters()
        assert len(adapters) > 0
        assert any(a["name"] == "duckdb" for a in adapters)

        # Verify adapter metadata structure
        duckdb_adapter = next(a for a in adapters if a["name"] == "duckdb")
        assert "display_name" in duckdb_adapter
        assert "class" in duckdb_adapter
        assert duckdb_adapter["display_name"] == "DuckDB"

    def test_create_duckdb_adapter(self, tmp_path):
        """Test creating DuckDB adapter."""
        config: DataStoreConfig = {"database_path": str(tmp_path / "test.db")}
        data_store = DataStoreFactory.create(adapter_name="duckdb", config=config)

        assert data_store is not None
        assert hasattr(data_store, "store")
        assert hasattr(data_store, "load")
        assert hasattr(data_store, "delete")
        assert hasattr(data_store, "get_metrics")
        assert hasattr(data_store, "exists")

    def test_create_duckdb_adapter_memory(self):
        """Test creating DuckDB adapter with in-memory database."""
        config: DataStoreConfig = {"database_path": ":memory:"}
        data_store = DataStoreFactory.create(adapter_name="duckdb", config=config)

        assert data_store is not None

    def test_create_unknown_adapter(self):
        """Test creating unknown adapter raises error."""
        with pytest.raises(DocpipeException) as exc_info:
            DataStoreFactory.create(adapter_name="unknown_adapter", config={"database_path": "test.db"})

        assert exc_info.value.status_code == 400
        assert "unknown_adapter" in str(exc_info.value).lower()

    def test_create_invalid_config_missing_path(self):
        """Test creating adapter with missing database_path raises error."""
        with pytest.raises(DocpipeException) as exc_info:
            DataStoreFactory.create(adapter_name="duckdb", config={})

        assert exc_info.value.status_code == 400
        assert "database_path" in str(exc_info.value).lower()

    def test_create_invalid_config_empty_path(self):
        """Test creating adapter with empty database_path raises error."""
        with pytest.raises(DocpipeException) as exc_info:
            DataStoreFactory.create(adapter_name="duckdb", config={"database_path": ""})

        assert exc_info.value.status_code == 400

    def test_create_invalid_config_wrong_type(self):
        """Test creating adapter with wrong type for database_path raises error."""
        with pytest.raises(DocpipeException) as exc_info:
            DataStoreFactory.create(adapter_name="duckdb", config={"database_path": 123})

        assert exc_info.value.status_code == 400

    def test_get_adapter_info(self):
        """Test getting adapter information."""
        info = DataStoreFactory.get_adapter_info(adapter_name="duckdb")

        assert info["name"] == "duckdb"
        assert info["display_name"] == "DuckDB"
        assert "class" in info

    def test_get_adapter_info_unknown(self):
        """Test getting info for unknown adapter raises error."""
        with pytest.raises(DocpipeException) as exc_info:
            DataStoreFactory.get_adapter_info(adapter_name="unknown")

        assert exc_info.value.status_code == 400

    def test_create_delegates_to_from_config(self):
        """DataStoreFactory.create() delegates construction to adapter_class.from_config()."""
        mock_instance = MagicMock()
        with patch(
            "docpipe.core.assets.document_sets.adapters.duckdb.data_store.DuckDBDocumentSetStorage.from_config",
            return_value=mock_instance,
        ) as mock_from_config:
            result = DataStoreFactory.create(
                adapter_name="duckdb",
                config={"database_path": "/tmp/test.duckdb"},
            )

        mock_from_config.assert_called_once_with(config={"database_path": "/tmp/test.duckdb"})
        assert result is mock_instance


@pytest.fixture
def isolated_data_store_registry(monkeypatch):
    """Run against copies of the adapter registry so test adapters do not leak."""
    monkeypatch.setattr(DataStoreFactory, "_adapters", dict(DataStoreFactory._adapters))
    monkeypatch.setattr(DataStoreFactory, "_adapter_metadata", dict(DataStoreFactory._adapter_metadata))


class _BrokenStore:
    """Adapter whose configuration is valid but whose construction fails."""

    error: Exception = RuntimeError("backend unreachable")

    @staticmethod
    def validate_config(*, config):
        return []

    @classmethod
    def from_config(cls, *, config):
        raise cls.error


@pytest.mark.usefixtures("isolated_data_store_registry")
class TestDataStoreFactoryRegistry:
    """Re-registration and construction failures."""

    def test_re_registration_replaces_the_adapter(self):
        DataStoreFactory.register(name="broken", display_name="Broken")(_BrokenStore)
        replacement = type("ReplacementStore", (_BrokenStore,), {})

        DataStoreFactory.register(name="broken", display_name="Broken v2")(replacement)

        assert DataStoreFactory._adapters["broken"] is replacement
        assert DataStoreFactory.get_adapter_info(adapter_name="broken")["display_name"] == "Broken v2"

    def test_construction_error_is_wrapped(self):
        DataStoreFactory.register(name="broken", display_name="Broken")(_BrokenStore)

        with pytest.raises(DocpipeException, match="Failed to create data store adapter 'broken'") as exc_info:
            DataStoreFactory.create(adapter_name="broken", config={})

        assert exc_info.value.status_code == 500
        assert isinstance(exc_info.value.__cause__, RuntimeError)

    def test_construction_docpipe_exception_is_kept(self, monkeypatch):
        error = DocpipeException("database path is read-only", status_code=400)
        monkeypatch.setattr(_BrokenStore, "error", error)
        DataStoreFactory.register(name="broken", display_name="Broken")(_BrokenStore)

        with pytest.raises(DocpipeException) as exc_info:
            DataStoreFactory.create(adapter_name="broken", config={})

        assert exc_info.value is error
