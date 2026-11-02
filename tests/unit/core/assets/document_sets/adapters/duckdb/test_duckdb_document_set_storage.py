"""Unit tests for DuckDBDocumentSetStorage.

All storage interactions are mocked — no real DuckDB or disk I/O.
Tests verify observable behaviour of store(), delete(), get_metrics(),
exists(), load(), health_check(), validate_config(), and from_config().
"""

from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest

from docpipe.core.assets.common.domain.models.attachment_ref import AttachmentRef
from docpipe.core.assets.document_sets.adapters.duckdb.data_store import DuckDBDocumentSetStorage
from docpipe.exceptions.docpipe_exceptions import DocpipeException

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DB_PATH = "/tmp/test.duckdb"
_TABLE_NAME = "my_docs"


def _make_ref(table_name: str = _TABLE_NAME) -> AttachmentRef:
    return AttachmentRef(
        backend_type="duckdb",
        name=table_name,
        details={"database_path": _DB_PATH, "table_name": table_name},
    )


def _make_storage(*, table_exists: bool = True) -> MagicMock:
    storage = MagicMock()
    storage.table_exists.return_value = table_exists
    return storage


def _make_sut(*, storage: MagicMock | None = None) -> DuckDBDocumentSetStorage:
    if storage is None:
        storage = _make_storage()
    return DuckDBDocumentSetStorage(table_storage=storage, database_path=_DB_PATH)


# ---------------------------------------------------------------------------
# store()
# ---------------------------------------------------------------------------


class TestStore:
    def test_store_creates_table_when_missing(self):
        storage = _make_storage(table_exists=False)
        sut = _make_sut(storage=storage)
        data = pa.table({"id": ["doc1"], "content": ["text"]})

        sut.store(doc_set_name="My Docs", data=data)

        storage.create_table.assert_called_once()
        storage.upsert_data.assert_called_once()

    def test_store_skips_create_when_table_exists(self):
        storage = _make_storage(table_exists=True)
        sut = _make_sut(storage=storage)
        data = pa.table({"id": ["doc1"], "content": ["text"]})

        sut.store(doc_set_name="My Docs", data=data)

        storage.create_table.assert_not_called()
        storage.upsert_data.assert_called_once()

    def test_store_raises_when_no_id_column(self):
        sut = _make_sut()
        data = pa.table({"content": ["text"]})

        with pytest.raises(DocpipeException, match="id"):
            sut.store(doc_set_name="My Docs", data=data)

    def test_store_wraps_unexpected_exception(self):
        storage = _make_storage(table_exists=True)
        storage.upsert_data.side_effect = RuntimeError("disk full")
        sut = _make_sut(storage=storage)
        data = pa.table({"id": ["doc1"]})

        with pytest.raises(DocpipeException, match="Failed to store data"):
            sut.store(doc_set_name="My Docs", data=data)

    def test_store_returns_attachment_ref(self):
        sut = _make_sut()
        data = pa.table({"id": ["doc1"]})

        ref = sut.store(doc_set_name="My Docs", data=data)

        assert ref.backend_type == "duckdb"
        assert ref.details["database_path"] == _DB_PATH
        assert "table_name" in ref.details


# ---------------------------------------------------------------------------
# delete()
# ---------------------------------------------------------------------------


class TestDelete:
    def test_delete_drops_existing_table(self):
        storage = _make_storage(table_exists=True)
        sut = _make_sut(storage=storage)

        result = sut.delete(attachment_ref=_make_ref())

        storage.delete_table.assert_called_once_with(table_name=_TABLE_NAME)
        assert result is True

    def test_delete_returns_false_when_table_missing(self):
        storage = _make_storage(table_exists=False)
        sut = _make_sut(storage=storage)

        result = sut.delete(attachment_ref=_make_ref())

        storage.delete_table.assert_not_called()
        assert result is False

    def test_delete_wraps_unexpected_exception(self):
        storage = _make_storage(table_exists=True)
        storage.delete_table.side_effect = RuntimeError("io error")
        sut = _make_sut(storage=storage)

        with pytest.raises(DocpipeException, match="Failed to delete table"):
            sut.delete(attachment_ref=_make_ref())


# ---------------------------------------------------------------------------
# get_metrics()
# ---------------------------------------------------------------------------


class TestGetMetrics:
    def _col_result(self) -> pa.Table:
        return pa.table({"column_name": ["id", "size", "pages_processed"]})

    def _agg_result(self, *, total_docs: int = 5, size: int = 100, pages: int = 10) -> pa.Table:
        return pa.table(
            {
                "total_documents": [total_docs],
                "total_size_bytes": [size],
                "total_pages": [pages],
            }
        )

    def test_get_metrics_returns_correct_values(self):
        storage = _make_storage(table_exists=True)
        storage.execute_query.side_effect = [self._col_result(), self._agg_result()]
        sut = _make_sut(storage=storage)

        metrics = sut.get_metrics(attachment_ref=_make_ref())

        assert metrics["total_documents"] == 5
        assert metrics["total_size_bytes"] == 100
        assert metrics["total_pages"] == 10

    def test_get_metrics_raises_when_table_missing(self):
        sut = _make_sut(storage=_make_storage(table_exists=False))

        with pytest.raises(DocpipeException, match="does not exist"):
            sut.get_metrics(attachment_ref=_make_ref())

    def test_get_metrics_wraps_unexpected_exception(self):
        storage = _make_storage(table_exists=True)
        storage.execute_query.side_effect = RuntimeError("query failed")
        sut = _make_sut(storage=storage)

        with pytest.raises(DocpipeException, match="Failed to compute metrics"):
            sut.get_metrics(attachment_ref=_make_ref())


# ---------------------------------------------------------------------------
# exists()
# ---------------------------------------------------------------------------


class TestExists:
    def test_exists_returns_true_when_table_exists(self):
        sut = _make_sut(storage=_make_storage(table_exists=True))
        assert sut.exists(attachment_ref=_make_ref()) is True

    def test_exists_returns_false_when_table_missing(self):
        sut = _make_sut(storage=_make_storage(table_exists=False))
        assert sut.exists(attachment_ref=_make_ref()) is False


# ---------------------------------------------------------------------------
# load()
# ---------------------------------------------------------------------------


class TestLoad:
    def test_load_returns_table_data(self):
        storage = _make_storage(table_exists=True)
        expected = pa.table({"id": ["doc1"], "content": ["text"]})
        storage.read_data.return_value = expected
        sut = _make_sut(storage=storage)

        result = sut.load(attachment_ref=_make_ref())

        assert result.equals(expected)

    def test_load_raises_when_table_missing(self):
        sut = _make_sut(storage=_make_storage(table_exists=False))

        with pytest.raises(DocpipeException, match="does not exist"):
            sut.load(attachment_ref=_make_ref())

    def test_load_wraps_unexpected_exception(self):
        storage = _make_storage(table_exists=True)
        storage.read_data.side_effect = RuntimeError("read error")
        sut = _make_sut(storage=storage)

        with pytest.raises(DocpipeException, match="Failed to load data"):
            sut.load(attachment_ref=_make_ref())


# ---------------------------------------------------------------------------
# health_check()
# ---------------------------------------------------------------------------


class TestHealthCheck:
    def test_health_check_returns_healthy(self):
        sut = _make_sut(storage=_make_storage())
        result = sut.health_check()
        assert result["healthy"] is True

    def test_health_check_returns_unhealthy_on_exception(self):
        storage = _make_storage()
        storage.execute_query.side_effect = RuntimeError("connection refused")
        sut = _make_sut(storage=storage)

        result = sut.health_check()

        assert result["healthy"] is False
        assert "connection refused" in result["message"]


# ---------------------------------------------------------------------------
# validate_config()
# ---------------------------------------------------------------------------


class TestValidateConfig:
    def test_valid_config_returns_empty_errors(self):
        errors = DuckDBDocumentSetStorage.validate_config(config={"database_path": "/data/test.duckdb"})
        assert errors == []

    def test_missing_database_path_returns_error(self):
        errors = DuckDBDocumentSetStorage.validate_config(config={})
        assert len(errors) == 1
        assert "database_path" in errors[0]

    def test_empty_database_path_returns_error(self):
        errors = DuckDBDocumentSetStorage.validate_config(config={"database_path": ""})
        assert len(errors) == 1


# ---------------------------------------------------------------------------
# from_config()
# ---------------------------------------------------------------------------


class TestFromConfig:
    def test_from_config_returns_instance(self):
        """from_config() returns a DuckDBDocumentSetStorage instance."""
        mock_storage = MagicMock()
        with patch(
            "docpipe.storage.StorageFactory.create_table_storage",
            return_value=mock_storage,
        ):
            instance = DuckDBDocumentSetStorage.from_config(config={"database_path": _DB_PATH})
        assert isinstance(instance, DuckDBDocumentSetStorage)

    def test_from_config_sets_database_path(self):
        """from_config() sets _database_path from config."""
        mock_storage = MagicMock()
        with patch(
            "docpipe.storage.StorageFactory.create_table_storage",
            return_value=mock_storage,
        ):
            instance = DuckDBDocumentSetStorage.from_config(config={"database_path": _DB_PATH})
        assert instance._database_path == _DB_PATH

    def test_from_config_raises_on_missing_database_path(self):
        """from_config() raises DocpipeException when database_path is absent."""
        with pytest.raises(DocpipeException, match="database_path"):
            DuckDBDocumentSetStorage.from_config(config={})

    def test_from_config_raises_on_empty_database_path(self):
        """from_config() raises DocpipeException when database_path is empty."""
        with pytest.raises(DocpipeException, match="database_path"):
            DuckDBDocumentSetStorage.from_config(config={"database_path": ""})


# ---------------------------------------------------------------------------
# DocpipeException pass-through and exists() failures
# ---------------------------------------------------------------------------


class TestStorageErrors:
    """DocpipeExceptions from the table storage keep their status; other errors are wrapped."""

    def test_store_keeps_docpipe_exception(self):
        storage = _make_storage(table_exists=True)
        error = DocpipeException("storage is read-only", status_code=503)
        storage.upsert_data.side_effect = error
        sut = _make_sut(storage=storage)

        with pytest.raises(DocpipeException) as exc_info:
            sut.store(doc_set_name="My Docs", data=pa.table({"id": ["doc1"]}))

        assert exc_info.value is error

    def test_delete_keeps_docpipe_exception(self):
        storage = _make_storage(table_exists=True)
        error = DocpipeException("storage is read-only", status_code=503)
        storage.delete_table.side_effect = error
        sut = _make_sut(storage=storage)

        with pytest.raises(DocpipeException) as exc_info:
            sut.delete(attachment_ref=_make_ref())

        assert exc_info.value is error

    def test_exists_keeps_docpipe_exception(self):
        storage = _make_storage()
        error = DocpipeException("storage is offline", status_code=503)
        storage.table_exists.side_effect = error
        sut = _make_sut(storage=storage)

        with pytest.raises(DocpipeException) as exc_info:
            sut.exists(attachment_ref=_make_ref())

        assert exc_info.value is error

    def test_exists_wraps_unexpected_exception(self):
        storage = _make_storage()
        storage.table_exists.side_effect = RuntimeError("connection lost")
        sut = _make_sut(storage=storage)

        with pytest.raises(DocpipeException, match="Failed to check table existence: connection lost") as exc_info:
            sut.exists(attachment_ref=_make_ref())

        assert exc_info.value.status_code == 500
