# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for DuckDBTableStorage (PyArrow table storage)."""

import pyarrow as pa
import pytest

from docpipe.storage.duck_db.duckdb_table_storage import DuckDBTableStorage
from docpipe.storage.exceptions import StorageException, StorageValidationError
from docpipe.storage.factory import StorageFactory


@pytest.fixture
def storage(tmp_path):
    """Create a DuckDBTableStorage instance."""
    return DuckDBTableStorage(database_path=str(tmp_path / "test.db"))


@pytest.fixture
def sample_schema():
    """Create a sample PyArrow schema."""
    return pa.schema(
        [
            ("id", pa.string()),
            ("name", pa.string()),
            ("content", pa.string()),
            ("size", pa.int64()),
            ("pages_processed", pa.int32()),
        ]
    )


@pytest.fixture
def sample_table():
    """Create a sample PyArrow table."""
    data = {
        "id": ["doc1", "doc2", "doc3"],
        "name": ["Document 1", "Document 2", "Document 3"],
        "content": ["Content 1", "Content 2", "Content 3"],
        "size": [100, 200, 300],
        "pages_processed": [1, 2, 3],
    }
    return pa.table(data)


class TestDuckDBTableStorageTableCreation:
    """Test table creation."""

    def test_create_table(self, storage, sample_schema):
        """Test creating a table from PyArrow schema."""
        table_name = "test_table"
        storage.create_table(table_name=table_name, schema=sample_schema)
        assert storage.table_exists(table_name=table_name)

    def test_create_table_with_id_primary_key(self, storage, sample_schema):
        """Test that id column becomes primary key."""
        table_name = "test_table"
        storage.create_table(table_name=table_name, schema=sample_schema)
        assert storage.table_exists(table_name=table_name)

    def test_create_table_empty_name(self, storage, sample_schema):
        """Test that empty table name raises error."""
        with pytest.raises(StorageValidationError, match="Table name cannot be empty"):
            storage.create_table(table_name="", schema=sample_schema)

    def test_create_table_idempotent(self, storage, sample_schema):
        """Test that creating table multiple times is safe."""
        table_name = "test_table"
        storage.create_table(table_name=table_name, schema=sample_schema)
        storage.create_table(table_name=table_name, schema=sample_schema)
        assert storage.table_exists(table_name=table_name)


class TestDuckDBTableStorageUpsertData:
    """Test insert and update operations."""

    def test_upsert_data_insert(self, storage, sample_schema, sample_table):
        """Test inserting new data."""
        table_name = "test_table"
        storage.create_table(table_name=table_name, schema=sample_schema)
        storage.upsert_data(table_name=table_name, data=sample_table)

        result = storage.read_data(table_name=table_name)
        assert result.num_rows == 3

    def test_upsert_data_update(self, storage, sample_schema):
        """Test updating existing data."""
        table_name = "test_table"
        storage.create_table(table_name=table_name, schema=sample_schema)

        initial_data = pa.table(
            {
                "id": ["doc1"],
                "name": ["Original Name"],
                "content": ["Original Content"],
                "size": [100],
                "pages_processed": [1],
            }
        )
        storage.upsert_data(table_name=table_name, data=initial_data)

        updated_data = pa.table(
            {
                "id": ["doc1"],
                "name": ["Updated Name"],
                "content": ["Updated Content"],
                "size": [200],
                "pages_processed": [2],
            }
        )
        storage.upsert_data(table_name=table_name, data=updated_data)

        result = storage.read_data(table_name=table_name)
        assert result.num_rows == 1
        assert result["name"][0].as_py() == "Updated Name"
        assert result["size"][0].as_py() == 200

    def test_upsert_data_missing_id_column(self, storage, sample_schema):
        """Test that upsert fails without id column."""
        table_name = "test_table"
        storage.create_table(table_name=table_name, schema=sample_schema)

        bad_data = pa.table({"name": ["Document 1"], "content": ["Content 1"]})

        with pytest.raises(StorageException, match="must contain an 'id' column"):
            storage.upsert_data(table_name=table_name, data=bad_data)

    def test_upsert_data_nonexistent_table(self, storage, sample_table):
        """Test that upsert fails for nonexistent table."""
        with pytest.raises(StorageException, match="does not exist"):
            storage.upsert_data(table_name="nonexistent_table", data=sample_table)


class TestDuckDBTableStorageReadData:
    """Test data reading with pagination."""

    def test_read_data_all(self, storage, sample_schema, sample_table):
        """Test reading all data."""
        table_name = "test_table"
        storage.create_table(table_name=table_name, schema=sample_schema)
        storage.upsert_data(table_name=table_name, data=sample_table)

        result = storage.read_data(table_name=table_name)

        assert result.num_rows == 3
        assert result.num_columns == 5

    def test_read_data_with_limit(self, storage, sample_schema, sample_table):
        """Test reading data with limit."""
        table_name = "test_table"
        storage.create_table(table_name=table_name, schema=sample_schema)
        storage.upsert_data(table_name=table_name, data=sample_table)

        result = storage.read_data(table_name=table_name, limit=2)

        assert result.num_rows == 2

    def test_read_data_with_offset(self, storage, sample_schema, sample_table):
        """Test reading data with offset."""
        table_name = "test_table"
        storage.create_table(table_name=table_name, schema=sample_schema)
        storage.upsert_data(table_name=table_name, data=sample_table)

        result = storage.read_data(table_name=table_name, offset=1)

        assert result.num_rows == 2

    def test_read_data_pagination(self, storage, sample_schema, sample_table):
        """Test reading data with limit and offset."""
        table_name = "test_table"
        storage.create_table(table_name=table_name, schema=sample_schema)
        storage.upsert_data(table_name=table_name, data=sample_table)

        result = storage.read_data(table_name=table_name, limit=1, offset=1)

        assert result.num_rows == 1
        assert result["id"][0].as_py() == "doc2"

    def test_read_data_nonexistent_table(self, storage):
        """Test that reading from nonexistent table raises error."""
        with pytest.raises(StorageException, match="does not exist"):
            storage.read_data(table_name="nonexistent_table")


class TestDuckDBTableStorageDeleteTable:
    """Test table deletion."""

    def test_delete_table(self, storage, sample_schema):
        """Test deleting a table."""
        table_name = "test_table"
        storage.create_table(table_name=table_name, schema=sample_schema)
        assert storage.table_exists(table_name=table_name)

        storage.delete_table(table_name=table_name)
        assert not storage.table_exists(table_name=table_name)

    def test_delete_nonexistent_table(self, storage):
        """Test deleting a nonexistent table."""
        # Should not raise error
        storage.delete_table(table_name="nonexistent_table")


class TestDuckDBTableStorageTableExists:
    """Test table existence checking."""

    def test_table_exists_true(self, storage, sample_schema):
        """Test checking if table exists."""
        table_name = "test_table"
        storage.create_table(table_name=table_name, schema=sample_schema)

        assert storage.table_exists(table_name=table_name) is True

    def test_table_exists_false(self, storage):
        """Test checking if nonexistent table exists."""
        assert storage.table_exists(table_name="nonexistent_table") is False


class TestDuckDBTableStorageGetRowCount:
    """Test row counting."""

    def test_get_row_count(self, storage, sample_schema, sample_table):
        """Test getting row count."""
        table_name = "test_table"
        storage.create_table(table_name=table_name, schema=sample_schema)
        storage.upsert_data(table_name=table_name, data=sample_table)

        count = storage.get_row_count(table_name=table_name)
        assert count == 3

    def test_get_row_count_empty_table(self, storage, sample_schema):
        """Test getting row count for empty table."""
        table_name = "test_table"
        storage.create_table(table_name=table_name, schema=sample_schema)

        count = storage.get_row_count(table_name=table_name)
        assert count == 0

    def test_get_row_count_nonexistent_table(self, storage):
        """Test that getting row count for nonexistent table raises error."""
        with pytest.raises(StorageException, match="does not exist"):
            storage.get_row_count(table_name="nonexistent_table")


class TestDuckDBTableStorageExecuteQuery:
    """Test SQL query execution."""

    def test_execute_query_select(self, storage, sample_schema, sample_table):
        """Test executing SELECT query."""
        table_name = "test_table"
        storage.create_table(table_name=table_name, schema=sample_schema)
        storage.upsert_data(table_name=table_name, data=sample_table)

        result = storage.execute_query(query=f"SELECT * FROM {table_name} WHERE size > 150")

        assert result.num_rows == 2

    def test_execute_query_with_parameters(self, storage, sample_schema, sample_table):
        """Test executing query with parameters."""
        table_name = "test_table"
        storage.create_table(table_name=table_name, schema=sample_schema)
        storage.upsert_data(table_name=table_name, data=sample_table)

        result = storage.execute_query(query=f"SELECT * FROM {table_name} WHERE id = ?", params=["doc2"])

        assert result.num_rows == 1
        assert result["id"][0].as_py() == "doc2"


class TestDuckDBTableStorageSchemaEvolution:
    """Test adding new columns (schema evolution)."""

    def test_schema_evolution_add_column(self, storage, sample_schema):
        """Test adding new columns to existing table."""
        table_name = "test_table"
        storage.create_table(table_name=table_name, schema=sample_schema)

        initial_data = pa.table(
            {
                "id": ["doc1"],
                "name": ["Document 1"],
                "content": ["Content 1"],
                "size": [100],
                "pages_processed": [1],
            }
        )
        storage.upsert_data(table_name=table_name, data=initial_data)

        new_data = pa.table(
            {
                "id": ["doc2"],
                "name": ["Document 2"],
                "content": ["Content 2"],
                "size": [200],
                "pages_processed": [2],
                "new_column": ["New Value"],
            }
        )
        storage.upsert_data(table_name=table_name, data=new_data)

        result = storage.read_data(table_name=table_name)
        assert result.num_rows == 2
        assert "new_column" in result.schema.names


class TestDuckDBTableStorageSingleton:
    """Test singleton pattern."""

    def test_same_path_returns_same_instance(self, tmp_path):
        """Test that same database path returns the same instance."""
        db_path = str(tmp_path / "test.db")

        storage1 = DuckDBTableStorage(database_path=db_path)
        storage2 = DuckDBTableStorage(database_path=db_path)

        assert storage1 is storage2

    def test_different_paths_return_different_instances(self, tmp_path):
        """Test that different database paths return different instances."""
        path1 = str(tmp_path / "db1.duckdb")
        path2 = str(tmp_path / "db2.duckdb")

        storage1 = DuckDBTableStorage(database_path=path1)
        storage2 = DuckDBTableStorage(database_path=path2)

        assert storage1 is not storage2

    def test_memory_database_singleton(self):
        """Test that :memory: database uses singleton pattern."""
        storage1 = DuckDBTableStorage(database_path=":memory:")
        storage2 = DuckDBTableStorage(database_path=":memory:")

        assert storage1 is storage2


class TestDuckDBTableStorageFactory:
    """Test factory integration."""

    def test_factory_create_table_storage(self, tmp_path):
        """Test creating DuckDBTableStorage through factory."""
        storage = StorageFactory.create_table_storage(storage_type="duckdb", database_path=str(tmp_path / "test.db"))

        assert isinstance(storage, DuckDBTableStorage)

        # Test it works
        schema = pa.schema([("id", pa.string()), ("value", pa.int64())])
        storage.create_table(table_name="test", schema=schema)
        assert storage.table_exists(table_name="test")

    def test_factory_singleton_consistency(self, tmp_path):
        """Test that factory and direct creation return same instance."""
        db_path = str(tmp_path / "test.db")

        storage1 = StorageFactory.create_table_storage(storage_type="duckdb", database_path=db_path)
        storage2 = DuckDBTableStorage(database_path=db_path)

        assert storage1 is storage2


class TestDuckDBTableStorageInMemory:
    """Test in-memory database operations."""

    def test_in_memory_database(self):
        """Test using in-memory database."""
        storage = DuckDBTableStorage(database_path=":memory:")

        schema = pa.schema([("id", pa.string()), ("value", pa.string())])
        storage.create_table(table_name="test_table", schema=schema)

        data = pa.table({"id": ["1"], "value": ["test"]})
        storage.upsert_data(table_name="test_table", data=data)

        result = storage.read_data(table_name="test_table")
        assert result.num_rows == 1


class TestDuckDBTableStorageValidation:
    """Test input validation."""

    def test_invalid_table_name_sql_injection(self, storage, sample_schema):
        """Test that SQL injection attempts in table name are rejected."""
        with pytest.raises(StorageValidationError, match="Invalid table name"):
            storage.create_table(table_name="test; DROP TABLE users;", schema=sample_schema)

    def test_invalid_table_name_empty(self, storage, sample_schema):
        """Test that empty table name is rejected."""
        with pytest.raises(StorageValidationError, match="Table name cannot be empty"):
            storage.create_table(table_name="", schema=sample_schema)


class TestDuckDBTableStorageErrorPaths:
    """Test error-handling paths for improved coverage."""

    def test_create_table_raises_on_invalid_name(self, storage, sample_schema):
        """Table names with invalid characters raise StorageValidationError."""
        with pytest.raises(StorageValidationError):
            storage.create_table(table_name="bad name!", schema=sample_schema)

    def test_upsert_data_raises_on_invalid_table_name(self, storage, sample_table):
        """upsert_data raises StorageValidationError for invalid table name."""
        with pytest.raises(StorageValidationError):
            storage.upsert_data(table_name="bad name!", data=sample_table)

    def test_read_data_raises_when_table_missing(self, storage):
        """read_data raises StorageException when table does not exist."""
        with pytest.raises(StorageException):
            storage.read_data(table_name="nonexistent_table")

    def test_get_row_count_raises_when_table_missing(self, storage):
        """get_row_count raises StorageException when table does not exist."""
        with pytest.raises(StorageException):
            storage.get_row_count(table_name="nonexistent_table")

    def test_get_table_schema_raises_when_table_missing(self, storage):
        """get_table_schema raises StorageException when table does not exist."""
        with pytest.raises(StorageException):
            storage.get_table_schema(table_name="nonexistent_table")

    def test_delete_table_returns_false_when_table_missing(self, storage):
        """delete_table returns False when table does not exist."""
        result = storage.delete_table(table_name="nonexistent_table")
        assert result is False


class TestDuckDBTableStorageExceptionReraise:
    """Cover except-reraise paths in create_table and upsert_data."""

    def test_create_table_raises_storage_exception_on_duckdb_error(self, storage, sample_schema):
        """duckdb.Error during create_table is wrapped in StorageException."""
        from unittest.mock import MagicMock, patch

        import duckdb

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = duckdb.Error("syntax error")
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = lambda s: mock_conn
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch.object(storage.connection_manager, "get_connection", return_value=mock_ctx):
            with pytest.raises(StorageException):
                storage.create_table(table_name="valid_table", schema=sample_schema)

    def test_upsert_data_raises_storage_exception_on_duckdb_error(self, storage, sample_table):
        """duckdb.Error during upsert_data is wrapped in StorageException."""
        from unittest.mock import MagicMock, patch

        import duckdb

        # First create the table so it exists
        storage.create_table(table_name="valid_table", schema=sample_table.schema)

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = duckdb.Error("write error")
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = lambda s: mock_conn
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch.object(storage.connection_manager, "get_connection", return_value=mock_ctx):
            with pytest.raises(StorageException):
                storage.upsert_data(table_name="valid_table", data=sample_table)


class TestDuckDBTableStorageTypeMapping:
    """Verify _pyarrow_to_duckdb_type is a pure static type-mapping helper."""

    def test_pyarrow_to_duckdb_type_is_static(self):
        """The type mapper must be a staticmethod (no instance state needed)."""
        import inspect

        assert isinstance(inspect.getattr_static(DuckDBTableStorage, "_pyarrow_to_duckdb_type"), staticmethod)

    @pytest.mark.parametrize(
        "pa_type,expected",
        [
            (pa.string(), "VARCHAR"),
            (pa.large_string(), "VARCHAR"),
            (pa.int64(), "BIGINT"),
            (pa.int32(), "INTEGER"),
            (pa.int16(), "SMALLINT"),
            (pa.int8(), "TINYINT"),
            (pa.float64(), "DOUBLE"),
            (pa.float32(), "FLOAT"),
            (pa.bool_(), "BOOLEAN"),
            (pa.binary(), "BLOB"),
            (pa.timestamp("us"), "TIMESTAMP"),
            (pa.date32(), "DATE"),
            (pa.time32("s"), "TIME"),
            (pa.list_(pa.string()), "JSON"),
            (pa.struct([("a", pa.string())]), "JSON"),
        ],
    )
    def test_known_type_mappings(self, pa_type, expected):
        """Known PyArrow types map to the documented DuckDB type strings."""
        assert DuckDBTableStorage._pyarrow_to_duckdb_type(pa_type=pa_type) == expected

    def test_unknown_type_defaults_to_varchar(self):
        """Unmapped PyArrow types fall back to VARCHAR."""
        # decimal128 is not present in the mapping table
        assert DuckDBTableStorage._pyarrow_to_duckdb_type(pa_type=pa.decimal128(10, 2)) == "VARCHAR"

    def test_instance_and_class_calls_agree(self, storage):
        """Instance access and class access return identical mappings."""
        assert storage._pyarrow_to_duckdb_type(pa_type=pa.int64()) == (
            DuckDBTableStorage._pyarrow_to_duckdb_type(pa_type=pa.int64())
        )


class TestSchemaWideningAndWrites:
    """Integer columns widen for float values, and execute_query commits writes."""

    def test_integer_column_is_widened_for_float_values(self, storage):
        """Without widening, DuckDB would round 5.5 to 6."""
        schema = pa.schema([("id", pa.string()), ("amount", pa.int64())])
        storage.create_table(table_name="totals", schema=schema)
        storage.upsert_data(table_name="totals", data=pa.table({"id": ["a"], "amount": [5]}, schema=schema))

        storage.upsert_data(table_name="totals", data=pa.table({"id": ["b"], "amount": [5.5]}))

        stored = storage.read_data(table_name="totals")
        assert stored.schema.field("amount").type == pa.float64()
        assert stored.column("amount").to_pylist() == [5.0, 5.5]

    def test_execute_query_commits_writes_on_a_database_file(self, storage):
        """Reads open the file read-only; writes open it read-write and are kept."""
        schema = pa.schema([("id", pa.string()), ("amount", pa.float64())])
        storage.create_table(table_name="totals", schema=schema)

        storage.execute_query(query="INSERT INTO totals VALUES (?, ?)", params=["a", 1.5])

        assert storage.execute_query(query="SELECT id, amount FROM totals").to_pylist() == [{"id": "a", "amount": 1.5}]
