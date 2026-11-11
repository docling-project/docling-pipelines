# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Filesystem table storage implementation: PyArrow tables kept as Parquet files."""

import re
import shutil
from io import TextIOWrapper
from pathlib import Path
from typing import IO, Any, ClassVar, cast

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from docpipe.storage.exceptions import StorageException, StorageValidationError
from docpipe.storage.file_system.abstract_file_system_storage import AbstractFileSystemStorage
from docpipe.storage.interfaces.table_storage_port import TableStoragePort
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)

_ID_COLUMN = "id"
_PARQUET_SUFFIX = ".parquet"
_QUOTED_NAME_RE = re.compile(r'"([^"]+)"')
_BARE_NAME_RE = re.compile(r"\b[A-Za-z_]\w*\b")


class TableFileSystemStorage(AbstractFileSystemStorage, TableStoragePort):
    """
    Thread-safe singleton filesystem storage for PyArrow tables.

    A table is a directory ``{base_dir}/{table_name}`` and its rows are the content of every ``*.parquet`` file below
    that directory, including files in sub-directories. A table name may be a sub-path such as ``run-1/data/chunker_0``.
    Because any Parquet files count, a directory written by another component (for example the intermediate node
    outputs of a flow, which keep one file per micro-batch) can be read as a table.

    Tables created and changed through this class keep their rows in ``data.parquet``.

    Differences from the contract of ``TableStoragePort``: nested values are kept as native Parquet types and are
    not converted to JSON text, and ``execute_query`` can reference a table by its name only; a name containing
    ``/`` must be double quoted.

    Example:
        storage = TableFileSystemStorage(base_dir="data/tables")
        storage.create_table(table_name="documents", schema=schema)
        storage.upsert_data(table_name="documents", data=table)
        rows = storage.execute_query(query='SELECT * FROM documents WHERE id IN (?, ?)', params=["a", "b"])
    """

    DATA_FILE = "data.parquet"

    # Each subclass of AbstractFileSystemStorage has its own singleton registry
    _instances: ClassVar[dict[str, "TableFileSystemStorage"]] = {}

    def _validate_collection(self, *, collection: str) -> None:
        """Also reject absolute table names, which would resolve outside ``base_dir``."""
        super()._validate_collection(collection=collection)
        if collection.startswith("/"):
            raise StorageValidationError(message=f"Invalid table name: {collection}. It must be a relative path")

    # ------------------------------------------------------------------
    # AbstractFileSystemStorage I/O hooks
    # ------------------------------------------------------------------

    def save_file_content(self, *, file: IO[str], data: Any) -> None:
        """Write ``data`` (a PyArrow table) as Parquet through the binary layer of the open file."""
        pq.write_table(data, cast(TextIOWrapper, file).buffer)

    def load_file_content(self, *, file: IO[str]) -> pa.Table:
        """Read a PyArrow table from the Parquet file through the binary layer of the open file."""
        return pq.read_table(cast(TextIOWrapper, file).buffer)

    def list_files(self, *, collection: str) -> list[Any]:
        """List the content of every Parquet file of a table, one PyArrow table per file."""
        return [pq.read_table(path) for path in self._data_files(table_name=collection)]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _data_files(self, *, table_name: str) -> list[Path]:
        """Return the Parquet files that hold the rows of a table, in a stable order."""
        table_dir = self._get_collection_dir(collection=table_name)
        if not table_dir.is_dir():
            return []
        return sorted(path for path in table_dir.rglob(f"*{_PARQUET_SUFFIX}") if path.is_file())

    def _write_table(self, *, path: Path, table: pa.Table) -> None:
        """Atomically write a table to a Parquet file below ``base_dir``."""
        self.write_file(collection=path.parent.relative_to(self.base_dir).as_posix(), file_name=path.name, data=table)

    @staticmethod
    def _concat(*, tables: list[pa.Table]) -> pa.Table:
        """Concatenate tables, adding missing columns as nulls."""
        return pa.concat_tables(tables, promote_options="permissive")

    def _read_all(self, *, files: list[Path]) -> pa.Table:
        """Read and concatenate the given Parquet files."""
        return self._concat(tables=[pq.read_table(path) for path in files])

    # ------------------------------------------------------------------
    # TableStoragePort implementation
    # ------------------------------------------------------------------

    def create_table(self, *, table_name: str, schema: pa.Schema) -> None:
        """Create an empty table with the given schema, if it does not exist yet."""
        if self.table_exists(table_name=table_name):
            return
        try:
            table_dir = self._get_collection_dir(collection=table_name)
            self._write_table(path=table_dir / self.DATA_FILE, table=schema.empty_table())
        except StorageValidationError:
            raise
        except Exception as e:
            raise StorageException(message=f"Failed to create table {table_name}: {e}") from e

    def upsert_data(self, *, table_name: str, data: pa.Table) -> None:
        """Insert rows, or replace the rows that have the same ``id``."""
        if _ID_COLUMN not in data.column_names:
            raise StorageValidationError(message=f"Data for table {table_name} must have an '{_ID_COLUMN}' column")
        files = self._data_files(table_name=table_name)
        if not files:
            raise StorageException(message=f"Table {table_name} does not exist")
        try:
            for path in files:
                existing = pq.read_table(path)
                if _ID_COLUMN not in existing.column_names:
                    continue
                replaced = pc.is_in(existing[_ID_COLUMN], value_set=data[_ID_COLUMN].cast(existing[_ID_COLUMN].type))
                if pc.any(replaced).as_py():
                    self._write_table(path=path, table=existing.filter(pc.invert(replaced)))

            data_file = self._get_collection_dir(collection=table_name) / self.DATA_FILE
            tables = [pq.read_table(data_file)] if data_file.is_file() else []
            self._write_table(path=data_file, table=self._concat(tables=[*tables, data]))
        except Exception as e:
            raise StorageException(message=f"Failed to upsert data into {table_name}: {e}") from e

    def read_data(self, *, table_name: str, limit: int | None = None, offset: int | None = None) -> pa.Table:
        """Read the rows of a table ordered by ``id``."""
        files = self._data_files(table_name=table_name)
        if not files:
            raise KeyError(table_name)
        try:
            table = self._read_all(files=files)
            if _ID_COLUMN in table.column_names:
                table = table.sort_by(_ID_COLUMN)
            start = offset or 0
            return table.slice(start) if limit is None else table.slice(start, limit)
        except Exception as e:
            raise RuntimeError(f"Failed to read table {table_name}: {e}") from e

    def delete_table(self, *, table_name: str) -> bool:
        """Delete a table with all its files."""
        if not self._data_files(table_name=table_name):
            return False
        try:
            shutil.rmtree(self._get_collection_dir(collection=table_name))
        except Exception as e:
            raise RuntimeError(f"Failed to delete table {table_name}: {e}") from e
        return True

    def table_exists(self, *, table_name: str) -> bool:
        """A table exists when at least one Parquet file is stored for it."""
        return bool(self._data_files(table_name=table_name))

    def get_row_count(self, *, table_name: str) -> int:
        """Return the number of rows, taken from the Parquet metadata."""
        files = self._data_files(table_name=table_name)
        if not files:
            raise KeyError(table_name)
        try:
            return sum(pq.ParquetFile(path).metadata.num_rows for path in files)
        except Exception as e:
            raise RuntimeError(f"Failed to count rows of table {table_name}: {e}") from e

    def execute_query(self, *, query: str, params: list[Any] | None = None) -> pa.Table:
        """
        Run a SQL query over the tables it names and return the result as a PyArrow table.

        Every table of this storage that is named in the query is registered with its Parquet files, so only
        the rows and columns the query needs are read. Placeholders are positional ``?``.
        """
        try:
            conn = duckdb.connect(":memory:")
        except duckdb.Error as e:
            raise StorageException(message=f"Failed to execute query: {e}") from e
        try:
            for table_name in self._referenced_tables(query=query):
                self._register_table(conn=conn, table_name=table_name)
            result = conn.execute(query, params or []).fetch_arrow_table()
            logger.debug("Executed query, returned %s rows", len(result))
            return result
        except duckdb.Error as e:
            raise StorageException(message=f"Failed to execute query: {e}") from e
        except Exception as e:
            raise StorageException(message=f"Unexpected error executing query: {e}") from e
        finally:
            conn.close()

    def _register_table(self, *, conn: duckdb.DuckDBPyConnection, table_name: str) -> None:
        """Expose the Parquet files of a table to the query under the name of the table.

        The files are registered as an Arrow dataset, so no SQL is built from table or file names and DuckDB only reads
        the columns and rows the query needs.
        """
        files = [str(path) for path in self._data_files(table_name=table_name)]
        conn.register(table_name, ds.dataset(files, format="parquet"))

    def _referenced_tables(self, *, query: str) -> list[str]:
        """Return the names in ``query`` that are tables of this storage."""
        candidates = dict.fromkeys([*_QUOTED_NAME_RE.findall(query), *_BARE_NAME_RE.findall(query)])
        tables = []
        for name in candidates:
            try:
                if self.table_exists(table_name=name):
                    tables.append(name)
            except StorageValidationError:
                continue
        return tables
