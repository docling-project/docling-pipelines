"""PostgreSQL storage implementation for PyArrow tables.

``PostgresTableStorage`` is a backend-generic implementation of ``TableStoragePort``:
any component that stores PyArrow tables can use it through
``StorageFactory.create_table_storage(storage_type="postgres", ...)``.

Connection configuration (same keys as the other PostgreSQL components):
    postgres:
      host: localhost          # falls back to DOCPIPE_POSTGRES_HOST
      port: 5432               # falls back to DOCPIPE_POSTGRES_PORT
      database: docpipe        # falls back to DOCPIPE_POSTGRES_DB
      user: docpipe_user       # falls back to DOCPIPE_POSTGRES_USER
      password: secret         # falls back to DOCPIPE_POSTGRES_PASSWORD (required)
      pool_size: 5
      max_overflow: 10
      pool_timeout: 30

Every table lives in the configured PostgreSQL schema (default ``public``),
which is created on first use. All statements qualify the table with it.
"""

import json
import re
from typing import Any, ClassVar

import pyarrow as pa
from sqlalchemy import text

from docpipe.core.job_management.adapters.stores.postgres.database import (
    create_postgres_engine,
    get_postgres_connection_string,
)
from docpipe.storage.exceptions import StorageConnectionError, StorageException, StorageValidationError
from docpipe.storage.interfaces.table_storage_port import TableStoragePort
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

DEFAULT_SCHEMA = "public"

_IDENTIFIER_RE = re.compile(r"^\w+$")
# PostgreSQL truncates longer identifiers, so two long names could map to one table.
_MAX_IDENTIFIER_LENGTH = 63

# PyArrow type checks and the PostgreSQL type used to store them, in the order they are tested.
_PYARROW_TO_POSTGRES: list[tuple[Any, str]] = [
    (pa.types.is_string, "TEXT"),
    (pa.types.is_large_string, "TEXT"),
    (pa.types.is_int64, "BIGINT"),
    (pa.types.is_int32, "INTEGER"),
    (pa.types.is_int16, "SMALLINT"),
    (pa.types.is_int8, "SMALLINT"),
    (pa.types.is_float64, "DOUBLE PRECISION"),
    (pa.types.is_float32, "REAL"),
    (pa.types.is_boolean, "BOOLEAN"),
    (pa.types.is_binary, "BYTEA"),
    (pa.types.is_large_binary, "BYTEA"),
    (pa.types.is_timestamp, "TIMESTAMP"),
    (pa.types.is_date, "DATE"),
    (pa.types.is_time, "TIME"),
    (pa.types.is_list, "JSONB"),
    (pa.types.is_large_list, "JSONB"),
    (pa.types.is_struct, "JSONB"),
    (pa.types.is_map, "JSONB"),
    (pa.types.is_null, "TEXT"),
]

# The ``information_schema.columns.data_type`` name of each type used in DDL.
_INFORMATION_SCHEMA_TYPE = {
    "TEXT": "text",
    "BIGINT": "bigint",
    "INTEGER": "integer",
    "SMALLINT": "smallint",
    "DOUBLE PRECISION": "double precision",
    "REAL": "real",
    "BOOLEAN": "boolean",
    "BYTEA": "bytea",
    "TIMESTAMP": "timestamp without time zone",
    "DATE": "date",
    "TIME": "time without time zone",
    "JSONB": "jsonb",
}

_INTEGER_TYPES = frozenset({"smallint", "integer", "bigint"})
_FLOAT_TYPES = frozenset({"real", "double precision", "numeric"})

# PostgreSQL type OIDs (``cursor.description`` type codes) and the Arrow type of their values.
_JSON_OIDS = frozenset({114, 3802})
_NUMERIC_OID = 1700
_OID_TO_ARROW: dict[int, pa.DataType] = {
    16: pa.bool_(),
    17: pa.binary(),
    20: pa.int64(),
    21: pa.int16(),
    23: pa.int32(),
    25: pa.string(),
    700: pa.float32(),
    701: pa.float64(),
    1042: pa.string(),
    1043: pa.string(),
    1082: pa.date32(),
    1083: pa.time64("us"),
    1114: pa.timestamp("us"),
    1184: pa.timestamp("us", tz="UTC"),
    _NUMERIC_OID: pa.float64(),
    114: pa.string(),
    3802: pa.string(),
}


class PostgresTableStorage(TableStoragePort):
    """PostgreSQL implementation of PyArrow table storage.

    Nested Arrow values (lists, structs and maps) are stored as ``JSONB`` and read
    back as JSON text, as ``DuckDBTableStorage`` does. ``execute_query`` takes ``?``
    placeholders, which are translated for the psycopg2 driver.
    """

    _SCHEMA_LOCK_SQL: ClassVar[str] = "SELECT pg_advisory_xact_lock(hashtext(:schema))"

    def __init__(self, *, schema: str = DEFAULT_SCHEMA, postgres: dict[str, Any] | None = None) -> None:
        """Connect to PostgreSQL and create the schema if needed.

        Args:
            schema: PostgreSQL schema that holds the tables.
            postgres: Connection settings. A setting that is not given falls back to
                its ``DOCPIPE_POSTGRES_*`` environment variable.

        Raises:
            StorageValidationError: If the schema name is invalid.
            StorageConnectionError: If no password is configured or the database cannot be reached.
        """
        self._validate_identifier(identifier=schema, kind="schema name")
        self.schema = schema
        # Column types per table, read from information_schema and updated on changes.
        self._column_types: dict[str, dict[str, str]] = {}

        connection_config = {"postgres": dict(postgres or {})}
        connection_string = get_postgres_connection_string(config=connection_config)
        if not connection_string:
            raise StorageConnectionError(
                message="PostgreSQL connection is not configured. Set the password in config or DOCPIPE_POSTGRES_PASSWORD."
            )

        try:
            self.engine = create_postgres_engine(connection_string=connection_string, config=connection_config)
            # create_engine does not connect, so check the connection here: a misconfigured
            # backend then fails when the storage is created, not at its first use.
            with self.engine.begin() as connection:
                connection.execute(text("SELECT 1"))
                # The advisory lock lets several processes create the schema at the same time.
                connection.execute(text(self._SCHEMA_LOCK_SQL), {"schema": schema})
                connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {self._quote_identifier(identifier=schema)}"))
        except Exception as exc:
            raise StorageConnectionError(message=f"Failed to connect to PostgreSQL storage: {exc}") from exc

        logger.info("Initialized PostgresTableStorage in schema %s", schema)

    def close(self) -> None:
        """Dispose the connection pool. The storage reconnects if it is used again."""
        self.engine.dispose()

    @staticmethod
    def _validate_identifier(*, identifier: str, kind: str) -> None:
        """Check that an identifier is safe to quote into SQL.

        Args:
            identifier: Schema, table or column name.
            kind: What the identifier names, for the error message.

        Raises:
            StorageValidationError: If the identifier is empty, too long or has other characters
                than letters, digits and underscores.
        """
        if not identifier or not isinstance(identifier, str):
            raise StorageValidationError(message=f"{kind} cannot be empty")

        if not _IDENTIFIER_RE.match(identifier):
            raise StorageValidationError(
                message=f"Invalid {kind}: {identifier}. Must contain only alphanumeric characters and underscores."
            )

        if len(identifier) > _MAX_IDENTIFIER_LENGTH:
            raise StorageValidationError(
                message=f"Invalid {kind}: {identifier}. Must be at most {_MAX_IDENTIFIER_LENGTH} characters."
            )

    @staticmethod
    def _quote_identifier(*, identifier: str) -> str:
        """Return the identifier in double quotes."""
        return f'"{identifier}"'

    def _qualified_table(self, *, table_name: str) -> str:
        """Return the quoted table name qualified with the storage schema."""
        return f"{self._quote_identifier(identifier=self.schema)}.{self._quote_identifier(identifier=table_name)}"

    @staticmethod
    def _pyarrow_to_postgres_type(*, pa_type: pa.DataType) -> str:
        """Return the PostgreSQL type that stores values of a PyArrow type.

        Args:
            pa_type: PyArrow data type.

        Returns:
            PostgreSQL type name used in DDL.
        """
        for type_check, postgres_type in _PYARROW_TO_POSTGRES:
            if type_check(pa_type):
                return postgres_type

        logger.warning("Unknown PyArrow type %s, defaulting to TEXT", pa_type)
        return "TEXT"

    @staticmethod
    def _is_compatible_type(*, existing: str, incoming: pa.DataType) -> bool:
        """Return whether values of a PyArrow type can be written to an existing column.

        Args:
            existing: ``information_schema`` data type of the column.
            incoming: PyArrow type of the new values.

        Returns:
            True if the column can store the values.
        """
        if pa.types.is_null(incoming):
            return True

        target = _INFORMATION_SCHEMA_TYPE[PostgresTableStorage._pyarrow_to_postgres_type(pa_type=incoming)]
        if target == existing:
            return True
        if target in _INTEGER_TYPES:
            return existing in _INTEGER_TYPES or existing in _FLOAT_TYPES
        if target in _FLOAT_TYPES:
            return existing in _FLOAT_TYPES
        # JSON text, as read_data returns it, can be written back to a JSONB column.
        return target == "text" and existing == "jsonb"

    @staticmethod
    def _to_driver_sql(*, query: str) -> str:
        """Translate a query with ``?`` placeholders to the psycopg2 ``%s`` style.

        Every ``%`` is doubled, because psycopg2 reads it as a format character. A ``?``
        inside a quoted string or identifier is kept. Dollar-quoted strings, comments and
        the ``?`` JSONB operators are not recognized; use ``jsonb_exists()`` instead.

        Args:
            query: SQL with ``?`` placeholders.

        Returns:
            SQL for ``exec_driver_sql``.
        """
        parts: list[str] = []
        quote: str | None = None
        for char in query:
            if char == "%":
                parts.append("%%")
            elif quote is not None:
                parts.append(char)
                if char == quote:
                    quote = None
            elif char in ("'", '"'):
                quote = char
                parts.append(char)
            elif char == "?":
                parts.append("%s")
            else:
                parts.append(char)
        return "".join(parts)

    @staticmethod
    def _to_json_text(*, value: Any) -> str:
        """Serialize a JSON value compactly, as DuckDB returns JSON columns."""
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)

    @staticmethod
    def _result_to_arrow(*, description: Any, rows: list[Any]) -> pa.Table:
        """Build a PyArrow table with the column types reported by the driver.

        JSON and JSONB values are returned as JSON text, and ``numeric`` values as floats,
        so the result has the same types as ``DuckDBTableStorage`` for the same data.

        Args:
            description: DB-API ``cursor.description``.
            rows: Fetched rows.

        Returns:
            Query result as a PyArrow table, also when it has no rows.
        """
        names: list[str] = []
        arrays: list[pa.Array] = []
        for index, column in enumerate(description):
            values = [row[index] for row in rows]
            type_code = column[1]
            if type_code in _JSON_OIDS:
                values = [
                    None if value is None else PostgresTableStorage._to_json_text(value=value) for value in values
                ]
            elif type_code == _NUMERIC_OID:
                values = [None if value is None else float(value) for value in values]
            names.append(column[0])
            arrays.append(pa.array(values, type=_OID_TO_ARROW.get(type_code)))
        return pa.Table.from_arrays(arrays, names=names)

    def create_table(self, *, table_name: str, schema: pa.Schema) -> None:
        """Create a table from a PyArrow schema, if it does not exist yet.

        Args:
            table_name: Name of the table.
            schema: PyArrow schema. An ``id`` column becomes the primary key.
        """
        self._validate_identifier(identifier=table_name, kind="table name")

        try:
            columns = []
            for field in schema:
                self._validate_identifier(identifier=field.name, kind="column name")
                column_type = self._pyarrow_to_postgres_type(pa_type=field.type)
                quoted_column = self._quote_identifier(identifier=field.name)
                primary_key = " PRIMARY KEY" if field.name == "id" else ""
                columns.append(f"{quoted_column} {column_type}{primary_key}")

            query = f"CREATE TABLE IF NOT EXISTS {self._qualified_table(table_name=table_name)} ({', '.join(columns)})"

            with self.engine.begin() as connection:
                connection.execute(text(query))
            # The table can already have existed with other columns, so read them again on the next upsert.
            self._column_types.pop(table_name, None)

            logger.info("Created PostgreSQL table %s.%s", self.schema, table_name)

        except StorageException:
            raise
        except Exception as exc:
            raise StorageException(message=f"Failed to create table {table_name}: {exc}") from exc

    def _read_column_types(self, *, table_name: str) -> dict[str, str]:
        """Read the columns of a table and their types from ``information_schema``."""
        query = """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = :table_schema
            AND table_name = :table_name
        """
        with self.engine.connect() as connection:
            result = connection.execute(text(query), {"table_schema": self.schema, "table_name": table_name})
            return {row["column_name"]: row["data_type"] for row in result.mappings().all()}

    def _handle_schema_evolution(self, *, table_name: str, new_schema: pa.Schema) -> dict[str, str]:
        """Add the columns of the new schema that the table does not have yet.

        The column types are cached per table, so ``information_schema`` is only read
        when the data has a column that was not seen before.

        Args:
            table_name: Name of the table.
            new_schema: Schema of the data to write.

        Returns:
            The columns of the table and their types, after the change.

        Raises:
            StorageValidationError: If a column exists with a type that cannot store the new values.
        """
        column_types = self._column_types.get(table_name)
        if column_types is None or not set(new_schema.names) <= set(column_types):
            column_types = self._read_column_types(table_name=table_name)

        for field in new_schema:
            existing = column_types.get(field.name)
            if existing is not None and not self._is_compatible_type(existing=existing, incoming=field.type):
                raise StorageValidationError(
                    message=(
                        f"Column {field.name} of table {table_name} has type {existing}, "
                        f"which cannot store values of type {field.type}"
                    )
                )

        columns_to_add = [field for field in new_schema if field.name not in column_types]
        if columns_to_add:
            qualified_table = self._qualified_table(table_name=table_name)
            with self.engine.begin() as connection:
                for field in columns_to_add:
                    self._validate_identifier(identifier=field.name, kind="column name")
                    postgres_type = self._pyarrow_to_postgres_type(pa_type=field.type)
                    quoted_column = self._quote_identifier(identifier=field.name)
                    # IF NOT EXISTS: concurrent batches can add the same column.
                    connection.execute(
                        text(f"ALTER TABLE {qualified_table} ADD COLUMN IF NOT EXISTS {quoted_column} {postgres_type}")
                    )
                    column_types[field.name] = _INFORMATION_SCHEMA_TYPE[postgres_type]
                    logger.info("Added column %s to PostgreSQL table %s.%s", field.name, self.schema, table_name)

        self._column_types[table_name] = column_types
        return column_types

    def upsert_data(self, *, table_name: str, data: pa.Table) -> None:
        """Insert rows, or update the rows with the same ``id``.

        Args:
            table_name: Name of the table.
            data: Rows to write. Must have an ``id`` column.

        Raises:
            StorageException: If the table does not exist or the write fails.
            StorageValidationError: If ``id`` is missing or a column has an incompatible type.
        """
        self._validate_identifier(identifier=table_name, kind="table name")

        if not self.table_exists(table_name=table_name):
            raise StorageException(message=f"Table {table_name} does not exist")

        if "id" not in data.schema.names:
            raise StorageValidationError(message="Data must contain an 'id' column for upsert")

        if data.num_rows == 0:
            return

        try:
            columns = list(data.schema.names)
            for column in columns:
                self._validate_identifier(identifier=column, kind="column name")

            column_types = self._handle_schema_evolution(table_name=table_name, new_schema=data.schema)

            quoted_columns = [self._quote_identifier(identifier=column) for column in columns]
            placeholders = ", ".join(f":{column}" for column in columns)
            update_columns = [column for column in quoted_columns if column != '"id"']
            # Identifiers are validated and quoted, so the SQL built below is safe.
            conflict_action = (
                "DO UPDATE SET " + ", ".join(f"{column} = EXCLUDED.{column}" for column in update_columns)  # nosec B608
                if update_columns
                else "DO NOTHING"
            )
            query = (
                f"INSERT INTO {self._qualified_table(table_name=table_name)} ({', '.join(quoted_columns)}) "  # nosec B608
                f'VALUES ({placeholders}) ON CONFLICT ("id") {conflict_action}'
            )

            # psycopg2 cannot adapt a dict and sends a list as an ARRAY, so JSONB values go as JSON text.
            json_columns = [column for column in columns if column_types.get(column) == "jsonb"]
            rows = data.to_pylist()
            for row in rows:
                for column in json_columns:
                    value = row[column]
                    if value is not None and not isinstance(value, str):
                        row[column] = self._to_json_text(value=value)

            # One bulk call: SQLAlchemy runs a list of rows as executemany.
            with self.engine.begin() as connection:
                connection.execute(text(query), rows)

            logger.debug("Upserted %s rows into PostgreSQL table %s.%s", len(rows), self.schema, table_name)

        except StorageException:
            raise
        except Exception as exc:
            raise StorageException(message=f"Failed to upsert data into {table_name}: {exc}") from exc

    def read_data(self, *, table_name: str, limit: int | None = None, offset: int | None = None) -> pa.Table:
        """Read rows ordered by ``id``, so pages with ``limit`` and ``offset`` are stable.

        Args:
            table_name: Name of the table.
            limit: Maximum number of rows to return.
            offset: Number of rows to skip.

        Returns:
            The rows, with the column types of the table.
        """
        self._validate_identifier(identifier=table_name, kind="table name")

        if not self.table_exists(table_name=table_name):
            raise StorageException(message=f"Table {table_name} does not exist")

        try:
            column_types = self._column_types.get(table_name) or self._read_column_types(table_name=table_name)
            query = f"SELECT * FROM {self._qualified_table(table_name=table_name)}"  # nosec B608 — identifier is validated.
            if "id" in column_types:
                query += ' ORDER BY "id"'

            params: dict[str, int] = {}
            if limit is not None:
                query += " LIMIT :limit"
                params["limit"] = limit
            if offset is not None:
                query += " OFFSET :offset"
                params["offset"] = offset

            with self.engine.connect() as connection:
                result = connection.execute(text(query), params)
                description = result.cursor.description
                rows = list(result.fetchall())

            return self._result_to_arrow(description=description, rows=rows)

        except StorageException:
            raise
        except Exception as exc:
            raise StorageException(message=f"Failed to read data from {table_name}: {exc}") from exc

    def delete_table(self, *, table_name: str) -> bool:
        """Delete a table.

        Returns:
            True if the table was deleted, False if it did not exist.

        Raises:
            StorageConnectionError: If the database cannot be reached.
            StorageException: If the table cannot be deleted.
        """
        self._validate_identifier(identifier=table_name, kind="table name")

        if not self.table_exists(table_name=table_name):
            return False

        try:
            with self.engine.begin() as connection:
                connection.execute(text(f"DROP TABLE IF EXISTS {self._qualified_table(table_name=table_name)}"))
            self._column_types.pop(table_name, None)

            logger.info("Deleted PostgreSQL table %s.%s", self.schema, table_name)
            return True

        except Exception as exc:
            raise StorageException(message=f"Failed to delete table {table_name}: {exc}") from exc

    def table_exists(self, *, table_name: str) -> bool:
        """Check if a table exists in the storage schema.

        Raises:
            StorageConnectionError: If the database cannot be reached, so a failed
                check is never taken for a missing table.
        """
        self._validate_identifier(identifier=table_name, kind="table name")

        query = """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = :table_schema
                AND table_name = :table_name
            )
        """
        try:
            with self.engine.connect() as connection:
                params = {"table_schema": self.schema, "table_name": table_name}
                return bool(connection.execute(text(query), params).scalar())
        except Exception as exc:
            raise StorageConnectionError(message=f"Failed to check if table {table_name} exists: {exc}") from exc

    def get_row_count(self, *, table_name: str) -> int:
        """Return the number of rows in a table."""
        self._validate_identifier(identifier=table_name, kind="table name")

        if not self.table_exists(table_name=table_name):
            raise StorageException(message=f"Table {table_name} does not exist")

        try:
            query = f"SELECT COUNT(*) FROM {self._qualified_table(table_name=table_name)}"  # nosec B608 — identifier is validated.
            with self.engine.connect() as connection:
                return int(connection.execute(text(query)).scalar() or 0)

        except Exception as exc:
            raise StorageException(message=f"Failed to get row count for {table_name}: {exc}") from exc

    def execute_query(self, *, query: str, params: list[Any] | None = None) -> pa.Table:
        """Execute a SQL query with ``?`` placeholders and return the result.

        Unqualified table names refer to the storage schema, as in ``DuckDBTableStorage``
        they refer to its database.

        Args:
            query: SQL with ``?`` placeholders.
            params: Positional values for the placeholders.

        Returns:
            Query result as a PyArrow table (empty if the statement returns no rows).
        """
        try:
            with self.engine.connect() as connection:
                connection.exec_driver_sql(
                    f"SET LOCAL search_path TO {self._quote_identifier(identifier=self.schema)}, public", ()
                )
                result = connection.exec_driver_sql(self._to_driver_sql(query=query), tuple(params or ()))
                if not result.returns_rows:
                    return pa.table({})
                description = result.cursor.description
                rows = list(result.fetchall())

            return self._result_to_arrow(description=description, rows=rows)

        except Exception as exc:
            raise StorageException(message=f"Failed to execute query: {exc}") from exc
