# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Failure-path tests for DuckDBTableStorage against real DuckDB files."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pytest

from docpipe.storage.duck_db import duckdb_table_storage
from docpipe.storage.duck_db.duckdb_table_storage import DuckDBTableStorage
from docpipe.storage.exceptions import StorageConnectionError, StorageException, StorageValidationError


def _prepare_database(db_path: Path, *statements: str) -> None:
    """Run SQL statements on a short-lived DuckDB connection and close it."""
    conn = duckdb.connect(str(db_path))
    try:
        for statement in statements:
            conn.execute(statement)
    finally:
        conn.close()


class _FailingConnection:
    """Real DuckDB connection whose ``execute`` raises for one kind of statement."""

    def __init__(self, *, connection: duckdb.DuckDBPyConnection, statement_prefix: str, error: Exception) -> None:
        self._connection = connection
        self._statement_prefix = statement_prefix
        self._error = error

    def execute(self, query: str, *args: Any) -> Any:
        """Raise the configured error for matching statements, delegate otherwise."""
        if query.lstrip().startswith(self._statement_prefix):
            raise self._error
        return self._connection.execute(query, *args)


class _FailingConnectionManager:
    """Connection manager that hands out real connections failing on one statement.

    DuckDB itself only raises ``duckdb.Error`` for the fixed statements of the
    read and drop methods; this double injects the non-DuckDB error (e.g. the
    ``RuntimeError`` duckdb's binding layer raises for values it cannot cast)
    needed to reach their generic error handlers.
    """

    def __init__(self, *, real_manager: Any, statement_prefix: str, error: Exception) -> None:
        self._real_manager = real_manager
        self._statement_prefix = statement_prefix
        self._error = error

    @contextmanager
    def get_connection(self, database_path: str, read_only: bool = False) -> Iterator[_FailingConnection]:
        """Yield a wrapped real connection."""
        with self._real_manager.get_connection(database_path, read_only=read_only) as connection:
            yield _FailingConnection(connection=connection, statement_prefix=self._statement_prefix, error=self._error)


@pytest.fixture
def db_path(tmp_path):
    """Path of a fresh DuckDB database file."""
    return tmp_path / "tables.duckdb"


@pytest.fixture
def storage(db_path):
    """DuckDBTableStorage on a fresh database file."""
    return DuckDBTableStorage(database_path=str(db_path))


@pytest.fixture
def documents_schema():
    """Schema with an id primary key and one payload column."""
    return pa.schema([("id", pa.string()), ("size", pa.int64())])


@pytest.fixture
def documents(storage, documents_schema):
    """Name of a created 'documents' table holding two rows."""
    storage.create_table(table_name="documents", schema=documents_schema)
    storage.upsert_data(
        table_name="documents",
        data=pa.table({"id": ["doc1", "doc2"], "size": [10, 20]}, schema=documents_schema),
    )
    return "documents"


def _inject_failure(*, monkeypatch, storage, statement_prefix: str, error: Exception) -> None:
    """Make statements starting with ``statement_prefix`` raise ``error``."""
    monkeypatch.setattr(
        storage,
        "connection_manager",
        _FailingConnectionManager(
            real_manager=storage.connection_manager, statement_prefix=statement_prefix, error=error
        ),
    )


class _RecordCollector(logging.Handler):
    """Logging handler that keeps every record it receives."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Store the record."""
        self.records.append(record)


@pytest.fixture
def module_log_records():
    """Records logged by the duckdb_table_storage module logger during the test."""
    collector = _RecordCollector()
    module_logger = logging.getLogger(duckdb_table_storage.__name__)
    module_logger.addHandler(collector)
    try:
        yield collector.records
    finally:
        module_logger.removeHandler(collector)


class TestValidateDatabasePath:
    """validate_database_path checks each path once and only warns."""

    def test_missing_directory_is_reported_but_not_created(self, tmp_path, module_log_records):
        """A missing parent directory triggers a warning; nothing is created."""
        db_path = tmp_path / "not-yet" / "tables.duckdb"

        DuckDBTableStorage.validate_database_path(db_path=str(db_path))

        assert not db_path.parent.exists()
        warnings = [record for record in module_log_records if record.levelno == logging.WARNING]
        assert [record.getMessage() for record in warnings] == [f"Database directory does not exist: {db_path.parent}"]

    def test_second_validation_of_same_path_is_a_no_op(self, tmp_path, module_log_records):
        """A path that was already validated is not checked or logged again."""
        db_path = str(tmp_path / "missing" / "tables.duckdb")
        DuckDBTableStorage.validate_database_path(db_path=db_path)
        logged_after_first_call = len(module_log_records)

        DuckDBTableStorage.validate_database_path(db_path=db_path)

        assert logged_after_first_call > 0
        assert len(module_log_records) == logged_after_first_call

    def test_constructor_creates_missing_directory(self, tmp_path):
        """The storage creates the database directory that validation warned about."""
        db_path = tmp_path / "created-on-init" / "tables.duckdb"

        DuckDBTableStorage(database_path=str(db_path))

        assert db_path.parent.is_dir()


class TestCreateTableFailures:
    """create_table validates column names and wraps errors in StorageException."""

    def test_empty_column_name_is_rejected(self, storage):
        """A schema field without a name is rejected before any SQL runs."""
        schema = pa.schema([("id", pa.string()), ("", pa.string())])

        with pytest.raises(StorageValidationError, match="Column name cannot be empty"):
            storage.create_table(table_name="documents", schema=schema)

        assert storage.table_exists(table_name="documents") is False

    def test_column_name_with_invalid_characters_is_rejected(self, storage):
        """Column names that are not plain identifiers are rejected."""
        schema = pa.schema([("id", pa.string()), ("file-name", pa.string())])

        with pytest.raises(StorageValidationError, match="Invalid column name: file-name"):
            storage.create_table(table_name="documents", schema=schema)

        assert storage.table_exists(table_name="documents") is False

    def test_os_error_is_wrapped_as_unexpected_error(self, tmp_path):
        """A file occupying the database directory surfaces as StorageException."""
        db_dir = tmp_path / "db"
        storage = DuckDBTableStorage(database_path=str(db_dir / "tables.duckdb"))
        db_dir.rmdir()
        db_dir.write_text("a file where the database directory should be", encoding="utf-8")

        with pytest.raises(StorageException, match="Unexpected error creating table documents") as exc_info:
            storage.create_table(table_name="documents", schema=pa.schema([("id", pa.string())]))

        assert isinstance(exc_info.value.__cause__, OSError)


class TestUpsertDataFailures:
    """upsert_data validates evolving schemas and wraps unexpected errors."""

    def test_new_column_with_invalid_name_is_rejected(self, storage, documents):
        """Schema evolution refuses to add a column with an invalid name."""
        data = pa.table({"id": ["doc3"], "page-count": [3]})

        with pytest.raises(StorageValidationError, match="Invalid column name: page-count"):
            storage.upsert_data(table_name=documents, data=data)

        assert storage.get_table_schema(table_name=documents).names == ["id", "size"]
        assert storage.get_row_count(table_name=documents) == 2

    def test_value_that_does_not_fit_column_type_is_wrapped(self, storage, documents):
        """DuckDB rejects a string that cannot be cast to the BIGINT column."""
        data = pa.table({"id": ["doc3"], "size": ["not a number"]})

        with pytest.raises(StorageException, match=f"Failed to upsert data into {documents}") as exc_info:
            storage.upsert_data(table_name=documents, data=data)

        assert isinstance(exc_info.value.__cause__, duckdb.Error)
        assert storage.get_row_count(table_name=documents) == 2

    def test_duplicate_new_column_is_wrapped_as_unexpected_error(self, storage, documents):
        """A table with a duplicated new column name fails schema evolution."""
        data = pa.table(
            [pa.array(["doc3"]), pa.array(["a"]), pa.array(["b"])],
            names=["id", "label", "label"],
        )

        with pytest.raises(StorageException, match=f"Unexpected error upserting data into {documents}") as exc_info:
            storage.upsert_data(table_name=documents, data=data)

        assert isinstance(exc_info.value.__cause__, KeyError)
        assert storage.get_row_count(table_name=documents) == 2


class TestReadDataFailures:
    """read_data wraps DuckDB and unexpected errors in StorageException."""

    def test_negative_limit_is_wrapped_as_storage_exception(self, storage, documents):
        """DuckDB rejects a negative LIMIT."""
        with pytest.raises(StorageException, match=f"Failed to read data from {documents}") as exc_info:
            storage.read_data(table_name=documents, limit=-1)

        assert isinstance(exc_info.value.__cause__, duckdb.Error)

    def test_unexpected_error_is_wrapped(self, monkeypatch, storage, documents):
        """A non-DuckDB error while reading is reported as unexpected."""
        _inject_failure(
            monkeypatch=monkeypatch, storage=storage, statement_prefix="SELECT *", error=RuntimeError("boom")
        )

        with pytest.raises(StorageException, match=f"Unexpected error reading data from {documents}: boom"):
            storage.read_data(table_name=documents)


class TestDeleteTableFailures:
    """delete_table wraps DuckDB and unexpected errors in StorageException."""

    def test_table_referenced_by_foreign_key_cannot_be_dropped(self, db_path, storage, documents):
        """DuckDB refuses to drop a table that another table references."""
        _prepare_database(db_path, f"CREATE TABLE pages (document_id VARCHAR REFERENCES {documents}(id))")

        with pytest.raises(StorageException, match=f"Failed to delete table {documents}") as exc_info:
            storage.delete_table(table_name=documents)

        assert isinstance(exc_info.value.__cause__, duckdb.Error)
        assert storage.table_exists(table_name=documents) is True

    def test_unexpected_error_is_wrapped(self, monkeypatch, storage, documents):
        """A non-DuckDB error while dropping is reported as unexpected."""
        _inject_failure(monkeypatch=monkeypatch, storage=storage, statement_prefix="DROP", error=RuntimeError("boom"))

        with pytest.raises(StorageException, match=f"Unexpected error deleting table {documents}: boom"):
            storage.delete_table(table_name=documents)

        monkeypatch.undo()
        assert storage.table_exists(table_name=documents) is True


class TestStaleViewFailures:
    """Row count and schema of a view whose base table was dropped."""

    @pytest.fixture
    def stale_view(self, db_path, storage):
        """Name of a view that references a table which no longer exists."""
        _prepare_database(
            db_path,
            "CREATE TABLE base_documents (id VARCHAR)",
            "CREATE VIEW stale_documents AS SELECT * FROM base_documents",
            "DROP TABLE base_documents",
        )
        return "stale_documents"

    def test_get_row_count_wraps_duckdb_error(self, storage, stale_view):
        """Counting rows of a broken view raises StorageException."""
        with pytest.raises(StorageException, match=f"Failed to get row count for {stale_view}") as exc_info:
            storage.get_row_count(table_name=stale_view)

        assert isinstance(exc_info.value.__cause__, duckdb.Error)

    def test_get_table_schema_wraps_duckdb_error(self, storage, stale_view):
        """Reading the schema of a broken view raises StorageException."""
        with pytest.raises(StorageException, match=f"Failed to get schema for {stale_view}") as exc_info:
            storage.get_table_schema(table_name=stale_view)

        assert isinstance(exc_info.value.__cause__, duckdb.Error)


class TestUnexpectedReadErrors:
    """get_row_count and get_table_schema report non-DuckDB errors as unexpected."""

    def test_get_row_count_wraps_unexpected_error(self, monkeypatch, storage, documents):
        """A non-DuckDB error while counting is reported as unexpected."""
        _inject_failure(
            monkeypatch=monkeypatch,
            storage=storage,
            statement_prefix="SELECT COUNT(*) as total",
            error=RuntimeError("boom"),
        )

        with pytest.raises(StorageException, match=f"Unexpected error getting row count for {documents}: boom"):
            storage.get_row_count(table_name=documents)

    def test_get_table_schema_wraps_unexpected_error(self, monkeypatch, storage, documents):
        """A non-DuckDB error while reading the schema is reported as unexpected."""
        _inject_failure(
            monkeypatch=monkeypatch, storage=storage, statement_prefix="SELECT *", error=RuntimeError("boom")
        )

        with pytest.raises(StorageException, match=f"Unexpected error getting schema for {documents}: boom"):
            storage.get_table_schema(table_name=documents)


class TestExecuteQueryFailures:
    """execute_query wraps DuckDB and unexpected errors in StorageException."""

    def test_invalid_sql_is_wrapped_as_storage_exception(self, storage, documents):
        """A syntax error is reported as a failed query."""
        with pytest.raises(StorageException, match="Failed to execute query") as exc_info:
            storage.execute_query(query=f"SELEC id FROM {documents}")

        assert isinstance(exc_info.value.__cause__, duckdb.Error)

    def test_query_without_statement_is_wrapped_as_unexpected_error(self, storage, documents):
        """A query string that holds only a comment produces no result set."""
        with pytest.raises(StorageException, match="Unexpected error executing query"):
            storage.execute_query(query="-- nothing to run")


class TestTableExistsFailures:
    """table_exists reports a database that cannot be read, instead of a missing table."""

    def test_database_file_that_does_not_exist_yet_has_no_tables(self, tmp_path):
        """The first write creates the file, so a missing file only means no tables."""
        storage = DuckDBTableStorage(database_path=str(tmp_path / "not_created_yet.duckdb"))

        assert storage.table_exists(table_name="documents") is False

    def test_read_error_is_raised_as_connection_error(self, monkeypatch, storage, documents):
        """A failed check is not taken for a missing table, which callers would then create."""
        _inject_failure(
            monkeypatch=monkeypatch,
            storage=storage,
            statement_prefix="SELECT COUNT(*) FROM information_schema.tables",
            error=duckdb.IOException("disk error"),
        )

        with pytest.raises(StorageConnectionError, match=f"Failed to check if table {documents} exists: disk error"):
            storage.table_exists(table_name=documents)
