"""Failure-path tests for DuckDBKeyValueStorage against real DuckDB files.

The collection tables used here are created with plain DuckDB connections that
are closed again before the storage touches the file, mimicking a database
file that already holds a table of the same name with a different layout.
"""

from pathlib import Path

import duckdb
import pytest

from docpipe.exceptions.docpipe_exceptions import DocpipeException
from docpipe.exceptions.error_codes import ErrorCode
from docpipe.storage.duck_db.duckdb_key_value_storage import DuckDBKeyValueStorage


def _prepare_database(db_path: Path, *statements: str) -> None:
    """Run SQL statements on a short-lived DuckDB connection and close it."""
    conn = duckdb.connect(str(db_path))
    try:
        for statement in statements:
            conn.execute(statement)
    finally:
        conn.close()


@pytest.fixture
def db_path(tmp_path):
    """Path of a fresh DuckDB database file."""
    return tmp_path / "records.duckdb"


class TestSaveRecordFailures:
    """save_record wraps serialisation and database errors in DocpipeException."""

    def test_non_duckdb_file_raises_storage_error_when_creating_collection(self, tmp_path):
        """A database path that holds a non-DuckDB file cannot get a collection table."""
        db_file = tmp_path / "notes.duckdb"
        db_file.write_text("this is not a duckdb database\n" * 10, encoding="utf-8")
        storage = DuckDBKeyValueStorage(database_path=str(db_file))

        with pytest.raises(DocpipeException, match="Failed to create collection table flows") as exc_info:
            storage.save_record(collection="flows", key="flow-1", data={"name": "flow"})

        assert exc_info.value.error_code == ErrorCode.STORAGE_ERROR
        assert isinstance(exc_info.value.__cause__, duckdb.Error)

    def test_unserialisable_data_raises_validation_error_and_stores_nothing(self, db_path):
        """Data that json.dumps rejects is reported as a validation error."""
        storage = DuckDBKeyValueStorage(database_path=str(db_path))

        with pytest.raises(DocpipeException, match="Failed to serialize data for flows/flow-1") as exc_info:
            storage.save_record(collection="flows", key="flow-1", data={"handle": object()})

        assert exc_info.value.error_code == ErrorCode.STORAGE_VALIDATION_ERROR
        assert isinstance(exc_info.value.__cause__, TypeError)
        assert storage.record_exists(collection="flows", key="flow-1") is False

    def test_existing_table_with_other_columns_raises_storage_error(self, db_path):
        """An existing table without key/data columns makes the insert fail."""
        _prepare_database(db_path, "CREATE TABLE flows (id VARCHAR, payload VARCHAR)")
        storage = DuckDBKeyValueStorage(database_path=str(db_path))

        with pytest.raises(DocpipeException, match="Failed to save record flows/flow-1") as exc_info:
            storage.save_record(collection="flows", key="flow-1", data={"name": "flow"})

        assert exc_info.value.error_code == ErrorCode.STORAGE_ERROR
        assert isinstance(exc_info.value.__cause__, duckdb.Error)


class TestGetRecordFailures:
    """get_record reports unreadable rows and tables as storage errors."""

    def test_row_with_invalid_json_raises_corrupted_data_error(self, db_path):
        """A data value that is not valid JSON is reported as corrupted."""
        _prepare_database(
            db_path,
            "CREATE TABLE flows (key VARCHAR PRIMARY KEY, data VARCHAR)",
            "INSERT INTO flows VALUES ('flow-1', 'not json at all')",
        )
        storage = DuckDBKeyValueStorage(database_path=str(db_path))

        with pytest.raises(DocpipeException, match="Corrupted data for flows/flow-1") as exc_info:
            storage.get_record(collection="flows", key="flow-1")

        assert exc_info.value.error_code == ErrorCode.STORAGE_ERROR

    def test_table_without_data_column_raises_storage_error(self, db_path):
        """Selecting the data column from a table that lacks it fails."""
        _prepare_database(db_path, "CREATE TABLE flows (key VARCHAR PRIMARY KEY, payload VARCHAR)")
        storage = DuckDBKeyValueStorage(database_path=str(db_path))

        with pytest.raises(DocpipeException, match="Failed to get record flows/flow-1") as exc_info:
            storage.get_record(collection="flows", key="flow-1")

        assert exc_info.value.error_code == ErrorCode.STORAGE_ERROR
        assert isinstance(exc_info.value.__cause__, duckdb.Error)


class TestListRecordsFailures:
    """list_records skips corrupted rows and wraps database errors."""

    def test_rows_with_invalid_json_are_skipped(self, db_path):
        """Only rows whose data parses as JSON are returned."""
        _prepare_database(
            db_path,
            "CREATE TABLE flows (key VARCHAR PRIMARY KEY, data VARCHAR)",
            """INSERT INTO flows VALUES
                ('flow-1', '{"name": "first"}'), ('flow-2', '{broken'), ('flow-3', '{"name": "third"}')""",
        )
        storage = DuckDBKeyValueStorage(database_path=str(db_path))

        records = storage.list_records(collection="flows")

        assert sorted(records, key=lambda record: record["name"]) == [{"name": "first"}, {"name": "third"}]

    def test_table_without_data_column_raises_storage_error(self, db_path):
        """Listing a table that has no data column fails with a storage error."""
        _prepare_database(db_path, "CREATE TABLE flows (key VARCHAR PRIMARY KEY, payload VARCHAR)")
        storage = DuckDBKeyValueStorage(database_path=str(db_path))

        with pytest.raises(DocpipeException, match="Failed to list records in flows") as exc_info:
            storage.list_records(collection="flows")

        assert exc_info.value.error_code == ErrorCode.STORAGE_ERROR
        assert isinstance(exc_info.value.__cause__, duckdb.Error)


class TestKeyColumnMissing:
    """delete_record and record_exists on a table that has no key column."""

    @pytest.fixture
    def storage(self, db_path):
        """Storage whose 'flows' table has data but no key column."""
        _prepare_database(
            db_path,
            "CREATE TABLE flows (id VARCHAR PRIMARY KEY, data JSON)",
            """INSERT INTO flows VALUES ('flow-1', '{"name": "first"}')""",
        )
        return DuckDBKeyValueStorage(database_path=str(db_path))

    def test_delete_record_raises_storage_error(self, storage):
        """Deleting by key from a table without a key column fails."""
        with pytest.raises(DocpipeException, match="Failed to delete record flows/flow-1") as exc_info:
            storage.delete_record(collection="flows", key="flow-1")

        assert exc_info.value.error_code == ErrorCode.STORAGE_ERROR
        assert isinstance(exc_info.value.__cause__, duckdb.Error)

    def test_record_exists_returns_false(self, storage):
        """A failing existence query is reported as 'record does not exist'."""
        assert storage.collection_exists(collection="flows") is True
        assert storage.record_exists(collection="flows", key="flow-1") is False
