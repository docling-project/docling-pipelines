"""Table storage port — interface for PyArrow table storage."""

from abc import ABC, abstractmethod
from typing import Any

import pyarrow as pa


class TableStoragePort(ABC):
    """
    Interface for PyArrow table storage.

    Used for storing document set data and curated entities as PyArrow tables.
    Provides operations for creating tables, upserting data, and querying.

    Contract shared by all implementations:
        - Every table written with ``upsert_data`` has an ``id`` column, which is its
          primary key. Rows with an existing ``id`` are updated.
        - Nested values (lists, structs and maps) are stored as JSON and read back as
          JSON text.
        - ``read_data`` returns rows ordered by ``id``.
        - ``execute_query`` takes positional ``?`` placeholders.

    docling-pipelines implementations: DuckDBTableStorage, PostgresTableStorage
    """

    @abstractmethod
    def create_table(self, *, table_name: str, schema: pa.Schema) -> None:
        """
        Create a table with the specified schema, if it does not exist yet.

        Creating a table that already exists does nothing, and keeps its columns.

        Args:
            table_name: Unique name for the table
            schema: PyArrow schema defining the table structure. An ``id`` column
                becomes the primary key.

        Raises:
            StorageException: If storage operation fails
        """
        ...

    @abstractmethod
    def upsert_data(self, *, table_name: str, data: pa.Table) -> None:
        """
        Insert or update data in a table, by ``id``.

        Columns that the table does not have yet are added.

        Args:
            table_name: Name of the table to upsert data into
            data: PyArrow table containing the data to upsert. Must have an ``id`` column.

        Raises:
            StorageException: If the specified table does not exist or the storage operation fails
            StorageValidationError: If the data has no ``id`` column
        """
        ...

    @abstractmethod
    def read_data(self, *, table_name: str, limit: int | None = None, offset: int | None = None) -> pa.Table:
        """
        Read data from a table, ordered by ``id`` so that pages are stable.

        Args:
            table_name: Name of the table to read from
            limit: Maximum number of rows to return
            offset: Number of rows to skip

        Returns:
            PyArrow table containing the requested data

        Raises:
            KeyError: If the specified table does not exist
            RuntimeError: If storage operation fails
        """
        ...

    @abstractmethod
    def delete_table(self, *, table_name: str) -> bool:
        """
        Delete a table and all its data.

        Args:
            table_name: Name of the table to delete

        Returns:
            True if table was deleted, False if it did not exist

        Raises:
            RuntimeError: If storage operation fails
        """
        ...

    @abstractmethod
    def table_exists(self, *, table_name: str) -> bool:
        """
        Check if a table exists.

        Args:
            table_name: Name of the table to check

        Returns:
            True if table exists, False otherwise

        Raises:
            StorageConnectionError: If the storage cannot be reached. A failed check
                is never reported as a missing table.
        """
        ...

    @abstractmethod
    def get_row_count(self, *, table_name: str) -> int:
        """
        Get the number of rows in a table.

        Args:
            table_name: Name of the table

        Returns:
            Number of rows in the table

        Raises:
            KeyError: If the specified table does not exist
            RuntimeError: If storage operation fails
        """
        ...

    @abstractmethod
    def execute_query(self, *, query: str, params: list[Any] | None = None) -> pa.Table:
        """
        Execute a SQL query and return results as PyArrow table.

        Placeholders are positional ``?`` on every backend; each implementation
        translates them for its driver.

        Args:
            query: SQL query to execute, with ``?`` placeholders
            params: Optional positional values for the placeholders

        Returns:
            Query results as PyArrow table

        Raises:
            StorageException: If query execution fails
        """
        ...

    def close(self) -> None:
        """Release the resources held by the storage, such as a connection pool."""
