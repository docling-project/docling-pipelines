# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""PyArrow table handling utilities for reading, writing, and transforming Parquet tables."""

from abc import ABC, abstractmethod
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from filelock import FileLock

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.utils.core.memmap_file_utils import replace_memmap_paths_combined
from docpipe.utils.data.transform import TransformUtils
from docpipe.utils.infrastructure.logging import get_logger

LOCK_TIMEOUT: float = 20


class BaseParquetTableHandler(ABC):
    """
    Abstract Base Class for handling Parquet tables.

    This class provides common methods for reading, saving, and deleting rows from Parquet tables.
    It includes a logger property for logging purposes and abstract methods for reading and saving tables.

    Attributes:
        logger (Logger): A logger instance for logging messages.

    Methods:
        logger: Returns the logger instance.
        read_table(path: str, filter_fn: callable = None) -> pa.Table | None:
            Abstract method to read a Parquet table from a given path.
            Optionally, it can filter rows using a filter function.

        save_table(path: str, table: pa.Table):
            Abstract method to save a PyArrow Table to a Parquet file at the given path.

        delete_rows(path: str, delete_filter_fn: callable):
            Deletes rows from a Parquet table based on a filter function.
    """

    @property
    def logger(self):
        """Logger."""
        return get_logger(f"{DocpipeConstants.LOGGER_NAME} : {self.__class__.__name__.upper()}")

    @abstractmethod
    def read_table(self, *, path, filters=None, columns=None) -> pa.Table | None:
        """
        Abstract method to read a Parquet table from a given path.
        Optionally, it can filter rows using a filter function.

        Args:
            path (str): The path to the Parquet file.
            filters (list | None): Optional row-level filters applied during Parquet read.
            columns (list[str] | None): List of column names to project. If None,
            all columns are read.

        Returns:
            pa.Table | None: A PyArrow Table object if the table is read successfully, otherwise None.
        """
        ...

    @abstractmethod
    def save_table(self, *, path, table: pa.Table):
        """
        Abstract method to save a PyArrow Table to a Parquet file at the given path.

        Args:
            path (str): The path where the Parquet file should be saved.
            table (pa.Table): The PyArrow Table to be saved as a Parquet file.
        """
        ...

    def delete_rows(self, *, path, delete_filter_fn):
        """
        Delete rows from a Parquet table based on a filter function.
        """
        self.logger.info("Deleting rows from: %s table", path)
        table = self.read_table(path=path)
        if table is None or table.num_rows == 0:
            return
        delete_mask = delete_filter_fn(table)

        if not pa.types.is_boolean(delete_mask.type):
            raise TypeError("delete_filter_fn must return a pyarrow BooleanArray")

        # Invert the mask to keep only non-matching (i.e., not deleted) rows
        keep_mask = pc.invert(delete_mask)  # type: ignore[attr-defined]

        updated_table = table.filter(keep_mask)
        self.save_table(path=path, table=updated_table)
        self.logger.info("Deleted %s rows.", table.num_rows - updated_table.num_rows)

    @abstractmethod
    def delete_file(self, *, path):
        """
        Delete Parquet file from the specified path.
        """
        ...


def _lock_path(*, path: str) -> str:
    return f"{path}.lock"


class CpdParquetTableHandler(BaseParquetTableHandler):
    """
    CPD implementation of BaseParquetTableHandler for local file storage.

    This class reads and writes Parquet tables from/to local file storage.
    """

    def read_table(self, *, path, filters=None, columns=None) -> pa.Table | None:
        """
        Read a Parquet table from File storage and optionally filter rows.
        """
        self.logger.info("Reading table from: %s", path)
        lock = FileLock(_lock_path(path=path), timeout=LOCK_TIMEOUT)
        with lock:
            if not Path(path).exists():
                self.logger.debug("Table not found from: %s", path)
                return None
            return pq.read_table(path, columns=columns, filters=filters)

    def save_table(self, *, path, table: pa.Table):
        """
        Save a PyArrow Table to File storage as a Parquet file.
        Replaces memmap file paths with actual data before saving.
        """
        try:
            self.logger.info("Saving table to: %s", path)

            # Replace memmap paths with actual data before saving to parquet
            table = replace_memmap_paths_combined(table=table)

            with FileLock(_lock_path(path=path), timeout=LOCK_TIMEOUT):
                pq.write_table(table, path)
        except Exception as exc:
            self.logger.exception(str(exc), stack_info=True)

    def delete_file(self, *, path):
        """Delete file."""
        try:
            self.logger.info("Deleting file: %s", path)
            with FileLock(_lock_path(path=path), timeout=LOCK_TIMEOUT):
                if Path(path).exists():
                    Path(path).unlink()
                    self.logger.info("File deleted successfully %s", path)
                else:
                    self.logger.warning("File does not exist.")
        except Exception as exc:
            self.logger.exception(str(exc), stack_info=True)


def get_parquet_table_handler() -> BaseParquetTableHandler:
    """
    Get the default Parquet table handler implementation.

    Returns:
        BaseParquetTableHandler: An instance of CpdParquetTableHandler
    """
    return CpdParquetTableHandler()


__all__ = [
    "BaseParquetTableHandler",
    "CpdParquetTableHandler",
    "TransformUtils",
    "get_parquet_table_handler",
]
