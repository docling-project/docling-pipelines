"""DuckDB storage implementation for PyArrow tables."""

import re
import threading
from pathlib import Path
from typing import Any, ClassVar

import duckdb
import pyarrow as pa

from docpipe.storage.exceptions import StorageException, StorageValidationError
from docpipe.storage.interfaces.table_storage_port import TableStoragePort
from docpipe.utils.duckdb import DuckDBConnectionManager
from docpipe.utils.infrastructure.logging import get_logger

_IN_MEMORY_DB = ":memory:"

logger = get_logger(__name__)

# Mapping of PyArrow types to DuckDB type strings — keeps _pyarrow_to_duckdb_type simple.
_PYARROW_TO_DUCKDB: list[tuple[Any, str]] = [
    (pa.types.is_string, "VARCHAR"),
    (pa.types.is_large_string, "VARCHAR"),
    (pa.types.is_int64, "BIGINT"),
    (pa.types.is_int32, "INTEGER"),
    (pa.types.is_int16, "SMALLINT"),
    (pa.types.is_int8, "TINYINT"),
    (pa.types.is_float64, "DOUBLE"),
    (pa.types.is_float32, "FLOAT"),
    (pa.types.is_boolean, "BOOLEAN"),
    (pa.types.is_binary, "BLOB"),
    (pa.types.is_large_binary, "BLOB"),
    (pa.types.is_timestamp, "TIMESTAMP"),
    (pa.types.is_date, "DATE"),
    (pa.types.is_time, "TIME"),
    (pa.types.is_list, "JSON"),
    (pa.types.is_large_list, "JSON"),
    (pa.types.is_struct, "JSON"),
    (pa.types.is_map, "JSON"),
]

_IDENTIFIER_RE = re.compile(r"^\w+$")


class DuckDBTableStorage(TableStoragePort):
    """
    Thread-safe singleton DuckDB storage implementation for PyArrow tables.

    Provides storage for PyArrow tables with support for table creation,
    data operations (upsert, read, delete), schema evolution, and SQL queries.

    Implements singleton pattern per database path to ensure only one instance
    exists for each unique database, preventing redundant initializations and
    connection overhead.

    Key Features:
        - Singleton pattern per database path (thread-safe)
        - Data table creation from PyArrow schemas
        - Upsert operations with automatic schema evolution
        - Read operations with pagination support
        - Row and table deletion
        - SQL injection prevention through identifier validation
        - SQL query execution
    """

    # Class-level cache for singleton instances per database path
    _instances: ClassVar[dict[str, "DuckDBTableStorage"]] = {}
    _lock: ClassVar[threading.Lock] = threading.Lock()

    # Class-level cache to track which paths have been validated
    _validated_paths: ClassVar[set[str]] = set()

    # Instance variable to track initialization state
    _initialized: bool

    def __new__(cls, *, database_path: str) -> "DuckDBTableStorage":
        """
        Singleton pattern - one instance per database path.

        Args:
            database_path: Path to DuckDB database file

        Returns:
            Singleton instance for the given database path
        """
        normalized_path = str(Path(database_path).resolve()) if database_path != _IN_MEMORY_DB else database_path

        with cls._lock:
            if normalized_path not in cls._instances:
                instance = super().__new__(cls)
                cls._instances[normalized_path] = instance
                instance._initialized = False
            return cls._instances[normalized_path]

    @classmethod
    def validate_database_path(cls, *, db_path: str) -> None:
        """
        Validate database path and log warnings if issues detected.

        Args:
            db_path: Path to DuckDB database file

        Logs:
            - INFO: Database path being used (only once per unique path)
            - WARNING: If database directory doesn't exist
        """
        if db_path in cls._validated_paths:
            return

        cls._validated_paths.add(db_path)
        logger.info("Using DuckDB database at: %s", db_path)

        if db_path == _IN_MEMORY_DB:
            return

        db_dir = Path(db_path).parent
        if not db_dir.exists():
            logger.warning("Database directory does not exist: %s", db_dir)
            logger.info("Directory will be created on first write")

    def __init__(self, *, database_path: str) -> None:
        """
        Initialize DuckDB table storage.

        Only initializes once per database path due to singleton pattern.

        Args:
            database_path: Path to DuckDB database file
        """
        if self._initialized:
            return

        self.validate_database_path(db_path=database_path)

        db_path = Path(database_path)
        if database_path != _IN_MEMORY_DB:
            db_path.parent.mkdir(parents=True, exist_ok=True)

        self.database_path = database_path
        self.connection_manager = DuckDBConnectionManager()
        self._initialized = True
        logger.info("Initialized DuckDBTableStorage at: %s", database_path)

    def _validate_table_name(self, *, table_name: str) -> None:
        """
        Validate table name to prevent SQL injection.

        Args:
            table_name: Name of the table to validate
        """
        if not table_name or not isinstance(table_name, str):
            raise StorageValidationError(message="Table name cannot be empty")

        if not _IDENTIFIER_RE.match(table_name):
            raise StorageValidationError(
                message=(
                    f"Invalid table name: {table_name}. Must start with letter or underscore "
                    "and contain only alphanumeric characters and underscores."
                )
            )

    def _validate_column_name(self, *, column_name: str) -> None:
        """
        Validate column name to prevent SQL injection.

        Args:
            column_name: Name of the column to validate
        """
        if not column_name or not isinstance(column_name, str):
            raise StorageValidationError(message="Column name cannot be empty")

        if not _IDENTIFIER_RE.match(column_name):
            raise StorageValidationError(
                message=(
                    f"Invalid column name: {column_name}. Must start with letter or underscore "
                    "and contain only alphanumeric characters and underscores."
                )
            )

    def _quote_identifier(self, *, identifier: str) -> str:
        """
        Quote SQL identifier for safe interpolation.

        Args:
            identifier: SQL identifier to quote

        Returns:
            Quoted identifier safe for SQL interpolation
        """
        return f'"{identifier}"'

    def create_table(self, *, table_name: str, schema: pa.Schema) -> None:
        """
        Create a data table from PyArrow schema.

        Args:
            table_name: Name of the table to create
            schema: PyArrow schema defining the table structure
        """
        self._validate_table_name(table_name=table_name)

        try:
            columns = []
            for field in schema:
                col_name = field.name
                self._validate_column_name(column_name=col_name)
                quoted_col = self._quote_identifier(identifier=col_name)
                duckdb_type = self._pyarrow_to_duckdb_type(pa_type=field.type)

                if col_name == "id":
                    columns.append(f"{quoted_col} {duckdb_type} PRIMARY KEY")
                else:
                    columns.append(f"{quoted_col} {duckdb_type}")

            quoted_table = self._quote_identifier(identifier=table_name)
            create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS {quoted_table} (
                {", ".join(columns)}
            )
            """

            with self.connection_manager.get_connection(self.database_path) as conn:
                conn.execute(create_table_sql)
                logger.info("Created data table: %s", table_name)
        except StorageException:
            raise
        except duckdb.Error as e:
            raise StorageException(message=f"Failed to create table {table_name}: {e}") from e
        except Exception as e:
            raise StorageException(message=f"Unexpected error creating table {table_name}: {e}") from e

    def upsert_data(self, *, table_name: str, data: pa.Table) -> None:
        """
        Insert or update rows in a data table by id column.

        Args:
            table_name: Name of the table to upsert into
            data: PyArrow table containing the data to upsert
        """
        self._validate_table_name(table_name=table_name)
        if not self.table_exists(table_name=table_name):
            raise StorageException(message=f"Table {table_name} does not exist")

        if "id" not in data.schema.names:
            raise StorageValidationError(message="Data must contain an 'id' column for upsert")

        try:
            self._handle_schema_evolution(table_name=table_name, new_schema=data.schema)

            with self.connection_manager.get_connection(self.database_path) as conn:
                conn.register("temp_data", data)

                for col_name in data.schema.names:
                    self._validate_column_name(column_name=col_name)

                quoted_columns = [self._quote_identifier(identifier=col) for col in data.schema.names]
                column_names = ", ".join(quoted_columns)
                quoted_table = self._quote_identifier(identifier=table_name)

                upsert_sql = f"""
                INSERT OR REPLACE INTO {quoted_table} ({column_names})
                SELECT {column_names} FROM temp_data
                """  # nosec B608 — table_name is validated and quoted via _quote_identifier(); column names are validated via _validate_column_name()

                conn.execute(upsert_sql)
                conn.unregister("temp_data")

                logger.debug("Upserted %s rows into %s", len(data), table_name)
        except StorageException:
            raise
        except duckdb.Error as e:
            raise StorageException(message=f"Failed to upsert data into {table_name}: {e}") from e
        except Exception as e:
            raise StorageException(message=f"Unexpected error upserting data into {table_name}: {e}") from e

    def read_data(self, *, table_name: str, limit: int | None = None, offset: int | None = None) -> pa.Table:
        """
        Read data from a table with pagination support.

        Args:
            table_name: Name of the table to read from
            limit: Maximum number of rows to return
            offset: Number of rows to skip

        Returns:
            PyArrow table containing the requested data
        """
        self._validate_table_name(table_name=table_name)
        if not self.table_exists(table_name=table_name):
            raise StorageException(message=f"Table {table_name} does not exist")

        try:
            quoted_table = self._quote_identifier(identifier=table_name)
            query = f"SELECT * FROM {quoted_table}"  # nosec B608 — table_name is validated and quoted via _quote_identifier()

            if limit is not None:
                query += f" LIMIT {limit}"
            if offset is not None:
                query += f" OFFSET {offset}"

            read_only = self.database_path != _IN_MEMORY_DB
            with self.connection_manager.get_connection(self.database_path, read_only=read_only) as conn:
                result = conn.execute(query).fetch_arrow_table()
                logger.debug("Read %s rows from %s (limit=%s, offset=%s)", len(result), table_name, limit, offset)
                return result
        except duckdb.Error as e:
            raise StorageException(message=f"Failed to read data from {table_name}: {e}") from e
        except Exception as e:
            raise StorageException(message=f"Unexpected error reading data from {table_name}: {e}") from e

    def delete_table(self, *, table_name: str) -> bool:
        """
        Delete a data table.

        Args:
            table_name: Name of the table to delete

        Returns:
            True if table was deleted, False if it did not exist
        """
        self._validate_table_name(table_name=table_name)
        if not self.table_exists(table_name=table_name):
            return False

        try:
            quoted_table = self._quote_identifier(identifier=table_name)
            with self.connection_manager.get_connection(self.database_path) as conn:
                conn.execute(f"DROP TABLE IF EXISTS {quoted_table}")
                logger.info("Deleted table: %s", table_name)
                return True
        except duckdb.Error as e:
            raise StorageException(message=f"Failed to delete table {table_name}: {e}") from e
        except Exception as e:
            raise StorageException(message=f"Unexpected error deleting table {table_name}: {e}") from e

    def table_exists(self, *, table_name: str) -> bool:
        """
        Check if a table exists.

        Args:
            table_name: Name of the table to check

        Returns:
            True if table exists, False otherwise
        """
        self._validate_table_name(table_name=table_name)
        try:
            read_only = self.database_path != _IN_MEMORY_DB
            with self.connection_manager.get_connection(self.database_path, read_only=read_only) as conn:
                query = """
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_name = ?
                """
                result = conn.execute(query, [table_name]).fetchone()
                return result[0] > 0 if result else False
        except Exception as e:
            logger.error("Failed to check if table %s exists: %s", table_name, e)
            return False

    def get_row_count(self, *, table_name: str) -> int:
        """
        Get the number of rows in a table.

        Args:
            table_name: Name of the table

        Returns:
            Number of rows in the table
        """
        self._validate_table_name(table_name=table_name)
        if not self.table_exists(table_name=table_name):
            raise StorageException(message=f"Table {table_name} does not exist")

        try:
            quoted_table = self._quote_identifier(identifier=table_name)
            read_only = self.database_path != _IN_MEMORY_DB
            with self.connection_manager.get_connection(self.database_path, read_only=read_only) as conn:
                count_query = f"SELECT COUNT(*) as total FROM {quoted_table}"  # nosec B608 — table_name is validated and quoted via _quote_identifier()
                count_result = conn.execute(count_query).fetchone()
                return count_result[0] if count_result else 0
        except duckdb.Error as e:
            raise StorageException(message=f"Failed to get row count for {table_name}: {e}") from e
        except Exception as e:
            raise StorageException(message=f"Unexpected error getting row count for {table_name}: {e}") from e

    def execute_query(self, *, query: str, params: list[Any] | None = None) -> pa.Table:
        """
        Execute a SQL query and return results as PyArrow table.

        Args:
            query: SQL query to execute
            params: Optional query parameters

        Returns:
            Query results as PyArrow table
        """
        try:
            read_only = self.database_path != _IN_MEMORY_DB
            with self.connection_manager.get_connection(self.database_path, read_only=read_only) as conn:
                if params:
                    result = conn.execute(query, params).fetch_arrow_table()
                else:
                    result = conn.execute(query).fetch_arrow_table()
                logger.debug("Executed query, returned %s rows", len(result))
                return result
        except duckdb.Error as e:
            raise StorageException(message=f"Failed to execute query: {e}") from e
        except Exception as e:
            raise StorageException(message=f"Unexpected error executing query: {e}") from e

    def get_table_schema(self, *, table_name: str) -> pa.Schema:
        """
        Get the current schema of a table.

        Args:
            table_name: Name of the table

        Returns:
            PyArrow schema of the table
        """
        self._validate_table_name(table_name=table_name)
        if not self.table_exists(table_name=table_name):
            raise StorageException(message=f"Table {table_name} does not exist")

        try:
            quoted_table = self._quote_identifier(identifier=table_name)
            read_only = self.database_path != _IN_MEMORY_DB
            with self.connection_manager.get_connection(self.database_path, read_only=read_only) as conn:
                query = f"SELECT * FROM {quoted_table} LIMIT 1"  # nosec B608 — table_name is validated and quoted via _quote_identifier()
                result = conn.execute(query).fetch_arrow_table()
                return result.schema
        except duckdb.Error as e:
            raise StorageException(message=f"Failed to get schema for {table_name}: {e}") from e
        except Exception as e:
            raise StorageException(message=f"Unexpected error getting schema for {table_name}: {e}") from e

    @staticmethod
    def _pyarrow_to_duckdb_type(*, pa_type: pa.DataType) -> str:
        """
        Convert PyArrow type to DuckDB type string.

        Args:
            pa_type: PyArrow data type

        Returns:
            DuckDB type string
        """
        for type_check, duckdb_type in _PYARROW_TO_DUCKDB:
            if type_check(pa_type):
                return duckdb_type

        logger.warning("Unknown PyArrow type %s, defaulting to VARCHAR", pa_type)
        return "VARCHAR"

    def _handle_schema_evolution(self, *, table_name: str, new_schema: pa.Schema) -> None:
        """
        Handle schema evolution by adding new columns if needed.

        Args:
            table_name: Name of the table
            new_schema: New PyArrow schema with potential new columns
        """
        current_schema = self.get_table_schema(table_name=table_name)
        current_columns = set(current_schema.names)
        new_columns = set(new_schema.names)

        columns_to_add = new_columns - current_columns

        if columns_to_add:
            quoted_table = self._quote_identifier(identifier=table_name)
            with self.connection_manager.get_connection(self.database_path) as conn:
                for col_name in columns_to_add:
                    self._validate_column_name(column_name=col_name)
                    quoted_col = self._quote_identifier(identifier=col_name)

                    field = new_schema.field(col_name)
                    duckdb_type = self._pyarrow_to_duckdb_type(pa_type=field.type)

                    alter_sql = f"ALTER TABLE {quoted_table} ADD COLUMN {quoted_col} {duckdb_type}"
                    conn.execute(alter_sql)
                    logger.info("Added column %s to %s", col_name, table_name)
