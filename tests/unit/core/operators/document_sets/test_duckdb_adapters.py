# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for DuckDB adapters implementing hexagonal architecture ports."""

import types
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest

from docpipe.core.assets.common.adapters.repositories.duckdb_asset_repository import DuckDBAssetRepository
from docpipe.core.assets.common.domain.models.attachment_ref import AttachmentRef
from docpipe.core.assets.document_sets.adapters.duckdb.data_store import (
    DuckDBDocumentSetStorage,
)
from docpipe.core.assets.document_sets.adapters.duckdb.duckdb_utils import sanitize_table_name
from docpipe.core.assets.document_sets.domain.models.document_set import DocumentSet
from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.storage import StorageFactory


@pytest.fixture
def temp_db_path(*, tmp_path):
    """Create temporary database path."""
    return str(tmp_path / "test.db")


@pytest.fixture
def metadata_repository(*, temp_db_path):
    """Create DuckDBAssetRepository[DocumentSet] with pinned collection."""
    key_value_storage = StorageFactory.create_key_value_storage(storage_type="duckdb", database_path=temp_db_path)
    repo = DuckDBAssetRepository(
        asset_type=DocumentSet, key_value_storage=key_value_storage, database_path=temp_db_path
    )
    repo._collection = "document_sets"
    return repo


@pytest.fixture
def data_store(*, temp_db_path):
    """Create data store for testing with dependency injection."""
    table_storage = StorageFactory.create_table_storage(storage_type="duckdb", database_path=temp_db_path)
    return DuckDBDocumentSetStorage(table_storage=table_storage, database_path=temp_db_path)


@pytest.fixture
def sample_document_set():
    """Create a sample document set."""
    return DocumentSet(
        asset_id="test-id-1",
        name="Test Set",
    )


class TestDuckDBMetadataRepository:
    """Test DuckDBAssetRepository[DocumentSet] adapter."""

    def test_create_document_set(self, *, metadata_repository, sample_document_set):
        """Test saving a document set."""
        created = metadata_repository.save(asset=sample_document_set)

        assert created.asset_id == sample_document_set.asset_id
        assert created.name == sample_document_set.name

    def test_get_by_id(self, *, metadata_repository):
        """Test retrieving document set by ID."""
        doc_set = DocumentSet(
            asset_id="test-id-2",
            name="Test Set Two",
            description="Test",
        )
        metadata_repository.save(asset=doc_set)

        retrieved = metadata_repository.find_by_id(asset_id="test-id-2")

        assert retrieved is not None
        assert retrieved.asset_id == doc_set.asset_id
        assert retrieved.name == doc_set.name

    def test_get_by_name(self, *, metadata_repository):
        """Test retrieving document set by name."""
        doc_set = DocumentSet(
            asset_id="test-id-3",
            name="Unique Name",
            description="Test",
        )
        metadata_repository.save(asset=doc_set)

        retrieved = metadata_repository.find_by_name(name="Unique Name")

        assert retrieved is not None
        assert retrieved.asset_id == doc_set.asset_id
        assert retrieved.name == "Unique Name"

    def test_get_nonexistent_raises_error(self, *, metadata_repository):
        """Test getting nonexistent document set returns None."""
        result = metadata_repository.find_by_id(asset_id="nonexistent")
        assert result is None

    def test_get_by_name_nonexistent_raises_error(self, *, metadata_repository):
        """Test getting nonexistent document set by name returns None."""
        result = metadata_repository.find_by_name(name="missing_name")
        assert result is None

    def test_list_all(self, *, metadata_repository):
        """Test listing all document sets."""
        for i in range(3):
            doc_set = DocumentSet(
                asset_id=f"test-id-{i}",
                name=f"Test Set {i}",
                description=f"Test {i}",
            )
            metadata_repository.save(asset=doc_set)

        all_sets = metadata_repository.list_all()

        assert len(all_sets) == 3
        assert {document_set.name for document_set in all_sets} == {
            "Test Set 0",
            "Test Set 1",
            "Test Set 2",
        }

    def test_list_all_sorted_newest_first(self, *, metadata_repository):
        """list_all returns records ordered by created_at descending."""

        def _record(asset_id, name, created_at):
            return {
                "asset_id": asset_id,
                "name": name,
                "description": None,
                "storage_backend": "duckdb",
                "total_documents": 0,
                "total_size_bytes": 0,
                "total_pages": 0,
                "created_at": created_at,
                "updated_at": "2024-01-01T00:00:00+00:00",
                "metadata": {},
                "data_card": None,
            }

        records = [
            _record("sort-1", "Oldest", "2024-01-01T00:00:00+00:00"),
            _record("sort-2", "Newest", "2024-06-01T00:00:00+00:00"),
            _record("sort-3", "Middle", "2024-03-01T00:00:00+00:00"),
        ]
        with patch.object(metadata_repository._storage, "list_records", return_value=records):
            result = metadata_repository.list_all()

        assert [r.name for r in result] == ["Newest", "Middle", "Oldest"]

    def test_list_all_none_created_at_does_not_raise(self, *, metadata_repository):
        """list_all must not raise TypeError when a record has created_at=None."""
        records: list[dict[str, object]] = [
            {
                "asset_id": "none-1",
                "name": "With Date",
                "description": None,
                "storage_backend": "duckdb",
                "total_documents": 0,
                "total_size_bytes": 0,
                "total_pages": 0,
                "created_at": "2024-01-01T00:00:00+00:00",
                "updated_at": "2024-01-01T00:00:00+00:00",
                "metadata": {},
                "data_card": None,
            },
            {
                "asset_id": "none-2",
                "name": "No Date",
                "description": None,
                "storage_backend": "duckdb",
                "total_documents": 0,
                "total_size_bytes": 0,
                "total_pages": 0,
                "created_at": None,
                "updated_at": None,
                "metadata": {},
                "data_card": None,
            },
        ]
        with patch.object(metadata_repository._storage, "list_records", return_value=records):
            result = metadata_repository.list_all()

        assert len(result) == 2

    def test_update_document_set(self, *, metadata_repository):
        """Test updating document set metadata."""
        doc_set = DocumentSet(
            asset_id="test-id-update",
            name="Original Name",
            description="Original description",
        )
        created = metadata_repository.save(asset=doc_set)

        created.description = "Updated description"
        updated = metadata_repository.update(asset=created)

        assert updated.description == "Updated description"
        assert updated.name == "Original Name"

        retrieved = metadata_repository.find_by_id(asset_id="test-id-update")
        assert retrieved is not None
        assert retrieved.description == "Updated description"

    def test_update_nonexistent_document_set_raises_error(self, *, metadata_repository):
        """Test that updating a nonexistent document set raises AssetNotFoundException."""
        doc_set = DocumentSet(
            asset_id="missing-id",
            name="Missing Name",
            description="Missing",
        )

        with pytest.raises(DocpipeException) as exc_info:
            metadata_repository.update(asset=doc_set)
        # AssetNotFoundException maps "DocumentSet" -> DOCUMENT_SET_NOT_FOUND
        assert exc_info.value.error_code == ErrorCode.DOCUMENT_SET_NOT_FOUND

    def test_delete_document_set(self, *, metadata_repository):
        """Test deleting document set."""
        doc_set = DocumentSet(
            asset_id="test-id-delete",
            name="To Delete",
            description="Will be deleted",
        )
        metadata_repository.save(asset=doc_set)

        result = metadata_repository.delete(asset_id="test-id-delete")

        assert result is True
        assert metadata_repository.find_by_id(asset_id="test-id-delete") is None

    def test_delete_nonexistent_document_set_returns_false(self, *, metadata_repository):
        """Test deleting nonexistent document set returns False."""
        result = metadata_repository.delete(asset_id="missing-id")
        assert result is False

    def test_exists(self, *, metadata_repository, sample_document_set):
        """Test checking document set existence."""
        assert metadata_repository.exists(asset_id=sample_document_set.asset_id) is False

        metadata_repository.save(asset=sample_document_set)

        assert metadata_repository.exists(asset_id=sample_document_set.asset_id) is True

    def test_create_duplicate_name_raises_error(self, *, metadata_repository):
        """Test saving document sets with duplicate name raises error."""
        first = DocumentSet(
            asset_id="test-id-a",
            name="Duplicate Name",
            description="First",
        )
        second = DocumentSet(
            asset_id="test-id-b",
            name="Duplicate Name",
            description="Second",
        )

        metadata_repository.save(asset=first)

        with pytest.raises(DocpipeException) as exc_info:
            metadata_repository.save(asset=second)

        assert exc_info.value.error_code == ErrorCode.DOCUMENT_SET_ALREADY_EXISTS

    def test_health_check(self, *, metadata_repository, temp_db_path):
        """Test health check returns success."""
        result = metadata_repository.health_check()

        assert result["status"] == "healthy"
        assert result["details"]["database_path"] == temp_db_path

    def test_validate_config(self):
        """Test config validation on DuckDBAssetRepository."""
        assert DuckDBAssetRepository.validate_config(config={"database_path": "test.db"}) == []
        assert DuckDBAssetRepository.validate_config(config={}) == ["Missing required configuration: 'database_path'"]
        assert DuckDBAssetRepository.validate_config(config={"database_path": ""}) == [
            "Configuration 'database_path' cannot be empty"
        ]


class TestDuckDBDocumentSetStorage:
    """Test DuckDBDocumentSetStorage adapter."""

    def _make_attachment_ref(self, *, table_name: str, database_path: str) -> AttachmentRef:
        return AttachmentRef(
            backend_type="duckdb",
            name=table_name,
            details={"database_path": database_path, "table_name": table_name},
        )

    def test_store_creates_table_and_returns_ref(self, *, data_store, temp_db_path):
        """Test that store() creates backing table and returns an AttachmentRef."""
        data = pa.table({"id": ["1", "2"], "content": ["a", "b"]})

        ref = data_store.store(doc_set_name="My Documents", data=data)

        assert ref.name == "my_documents"
        assert ref.details["database_path"] == temp_db_path
        assert ref.backend_type == "duckdb"

    def test_store_without_id_column_raises_error(self, *, data_store):
        """Test that store() raises an error when data has no id column."""
        data = pa.table({"content": ["a", "b"]})

        with pytest.raises(DocpipeException) as exc_info:
            data_store.store(doc_set_name="My Documents", data=data)

        assert exc_info.value.error_code == ErrorCode.DOCUMENT_SET_SCHEMA_MISMATCH

    def test_exists_returns_false_before_store(self, *, data_store, temp_db_path):
        """Test exists() returns False when table has not been created yet."""
        ref = self._make_attachment_ref(table_name="nonexistent_table", database_path=temp_db_path)
        assert data_store.exists(attachment_ref=ref) is False

    def test_exists_returns_true_after_store(self, *, data_store):
        """Test exists() returns True after store() has been called."""
        data = pa.table({"id": ["1"]})
        ref = data_store.store(doc_set_name="Exists Table", data=data)

        assert data_store.exists(attachment_ref=ref) is True

    def test_load_returns_stored_data(self, *, data_store):
        """Test load() returns the data written by store()."""
        data = pa.table({"id": ["1", "2", "3"], "value": [10, 20, 30]})
        ref = data_store.store(doc_set_name="Load Table", data=data)

        loaded = data_store.load(attachment_ref=ref)

        assert loaded.num_rows == 3

    def test_load_with_limit(self, *, data_store):
        """Test load() respects the limit parameter."""
        data = pa.table({"id": ["1", "2", "3"], "value": [10, 20, 30]})
        ref = data_store.store(doc_set_name="Load Limit Table", data=data)

        loaded = data_store.load(attachment_ref=ref, limit=2)

        assert loaded.num_rows == 2

    def test_load_nonexistent_table_raises_error(self, *, data_store, temp_db_path):
        """Test load() raises an error when table does not exist."""
        ref = self._make_attachment_ref(table_name="missing_table", database_path=temp_db_path)

        with pytest.raises(DocpipeException) as exc_info:
            data_store.load(attachment_ref=ref)

        assert exc_info.value.error_code == ErrorCode.DOCUMENT_SET_TABLE_NOT_FOUND

    def test_delete_returns_true_for_existing_table(self, *, data_store):
        """Test delete() returns True when the table exists."""
        data = pa.table({"id": ["1"]})
        ref = data_store.store(doc_set_name="Delete Table", data=data)

        result = data_store.delete(attachment_ref=ref)

        assert result is True
        assert data_store.exists(attachment_ref=ref) is False

    def test_delete_returns_false_for_missing_table(self, *, data_store, temp_db_path):
        """Test delete() returns False when the table does not exist."""
        ref = self._make_attachment_ref(table_name="missing_table", database_path=temp_db_path)
        assert data_store.delete(attachment_ref=ref) is False

    def test_get_metrics(self, *, data_store):
        """Test get_metrics() returns correct aggregates."""
        data = pa.table(
            {
                "id": ["1", "2", "3"],
                "content": ["a", "b", "c"],
                "size": [100, 200, 300],
                "pages_processed": [1, 2, 3],
            }
        )
        ref = data_store.store(doc_set_name="Metrics Table", data=data)

        metrics = data_store.get_metrics(attachment_ref=ref)

        assert metrics["total_documents"] == 3
        assert metrics["total_size_bytes"] == 600
        assert metrics["total_pages"] == 6

    def test_get_metrics_empty_table(self, *, data_store):
        """Test get_metrics() returns zeros for empty table."""
        data = pa.table(
            {
                "id": pa.array([], type=pa.string()),
                "size": pa.array([], type=pa.int64()),
                "pages_processed": pa.array([], type=pa.int64()),
            }
        )
        ref = data_store.store(doc_set_name="Empty Metrics Table", data=data)

        metrics = data_store.get_metrics(attachment_ref=ref)

        assert metrics["total_documents"] == 0
        assert metrics["total_size_bytes"] == 0
        assert metrics["total_pages"] == 0

    def test_get_metrics_ignores_a_table_with_the_same_name_in_another_schema(self, *, data_store):
        """get_metrics() reads only the columns of the document set's own table."""
        ref = data_store.store(doc_set_name="Shared Name", data=pa.table({"id": ["1", "2"]}))
        data_store._storage.execute_query(query="CREATE SCHEMA other")
        data_store._storage.execute_query(
            query="CREATE TABLE other.shared_name (id VARCHAR, size BIGINT, pages_processed BIGINT)"
        )

        metrics = data_store.get_metrics(attachment_ref=ref)

        assert metrics == {"total_documents": 2, "total_size_bytes": 0, "total_pages": 0}

    def test_get_metrics_nonexistent_table_raises_error(self, *, data_store, temp_db_path):
        """Test get_metrics() raises error for nonexistent table."""
        ref = self._make_attachment_ref(table_name="missing_table", database_path=temp_db_path)

        with pytest.raises(DocpipeException) as exc_info:
            data_store.get_metrics(attachment_ref=ref)

        assert exc_info.value.error_code == ErrorCode.DOCUMENT_SET_TABLE_NOT_FOUND

    def test_health_check(self, *, data_store, temp_db_path):
        """Test health check after database file is initialized."""
        data = pa.table({"id": ["1"]})
        data_store.store(doc_set_name="Health Table", data=data)

        result = data_store.health_check()

        assert result["healthy"] is True
        assert result["details"]["database_path"] == temp_db_path

    def test_validate_config(self):
        """Test config validation."""
        assert DuckDBDocumentSetStorage.validate_config(config={"database_path": "test.db"}) == []
        assert DuckDBDocumentSetStorage.validate_config(config={}) == [
            "Missing required configuration: 'database_path'"
        ]
        assert DuckDBDocumentSetStorage.validate_config(config={"database_path": ""}) == [
            "Configuration 'database_path' cannot be empty"
        ]


class TestSanitizeTableName:
    """Test sanitize_table_name utility used by both DuckDB adapters."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("My Documents", "my_documents"),
            ("Documents 2024", "documents_2024"),
            ("Test-Data (v1)", "testdata_v1"),
            ("UPPER CASE", "upper_case"),
            ("already_valid", "already_valid"),
            # Starts with a digit — gets tbl_ prefix
            ("123 Documents", "tbl_123_documents"),
            ("1kb file", "tbl_1kb_file"),
            # Empty / only special chars — gets tbl_ prefix
            ("", "tbl_"),
            ("@#$%", "tbl_"),
            # Single letter
            ("A", "a"),
        ],
    )
    def test_sanitize_table_name(self, name: str, expected: str) -> None:
        """Test table name sanitization produces correct output."""
        assert sanitize_table_name(name) == expected


class TestDuckDBDocumentSetMetadataRepositorySorting:
    """Regression tests for the datetime.min -> datetime.min.replace(tzinfo=UTC) fix
    in DuckDBDocumentSetMetadataRepository.list_all() (DTZ001).

    Targets adapters/duckdb/metadata_repository.py directly, not the generic
    DuckDBAssetRepository, since that is the class whose sort line was changed.

    _dict_to_document_set uses a legacy DocumentSet constructor signature that no
    longer matches the current model, so it is patched to return controlled objects.
    The tests focus purely on the sort logic at metadata_repository.py:289.
    """

    @pytest.fixture
    def mock_storage(self) -> MagicMock:
        storage = MagicMock()
        storage.collection_exists.return_value = True
        return storage

    @pytest.fixture
    def ds_repo(self, mock_storage: MagicMock):
        from docpipe.core.assets.document_sets.adapters.duckdb.metadata_repository import (
            DuckDBDocumentSetMetadataRepository,
        )

        return DuckDBDocumentSetMetadataRepository(key_value_storage=mock_storage, database_path="data/test.duckdb")

    def test_list_all_sorted_newest_first(self, ds_repo, mock_storage: MagicMock) -> None:
        """list_all must return records sorted by created_at descending."""
        ds_oldest = types.SimpleNamespace(name="Oldest", created_at=datetime(2024, 1, 1, tzinfo=UTC))
        ds_newest = types.SimpleNamespace(name="Newest", created_at=datetime(2024, 6, 1, tzinfo=UTC))
        ds_middle = types.SimpleNamespace(name="Middle", created_at=datetime(2024, 3, 1, tzinfo=UTC))

        mock_storage.list_records.return_value = [{}, {}, {}]
        with patch.object(ds_repo, "_dict_to_document_set", side_effect=[ds_oldest, ds_newest, ds_middle]):
            result = ds_repo.list_all()

        assert [ds.name for ds in result] == ["Newest", "Middle", "Oldest"]

    def test_list_all_none_created_at_does_not_raise(self, ds_repo, mock_storage: MagicMock) -> None:
        """A record with created_at=None must not raise TypeError — the
        datetime.min.replace(tzinfo=UTC) sentinel allows comparison against
        timezone-aware datetimes without error."""
        ds_with = types.SimpleNamespace(name="With Date", created_at=datetime(2024, 1, 1, tzinfo=UTC))
        ds_none = types.SimpleNamespace(name="No Date", created_at=None)

        mock_storage.list_records.return_value = [{}, {}]
        with patch.object(ds_repo, "_dict_to_document_set", side_effect=[ds_with, ds_none]):
            result = ds_repo.list_all()

        assert len(result) == 2
        assert result[0].name == "With Date"
        assert result[1].name == "No Date"
