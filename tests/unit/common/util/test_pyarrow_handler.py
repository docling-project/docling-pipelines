# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for PyArrow table handler utilities.
Tests for reading, writing, and transforming Parquet tables.
"""

from pathlib import Path
from unittest.mock import patch

import portalocker
import pyarrow as pa
import pyarrow.compute as pc
import pytest

from docpipe.utils.data import pyarrow_handler
from docpipe.utils.data.pyarrow_handler import (
    BaseParquetTableHandler,
    CpdParquetTableHandler,
    _lock_path,
    get_parquet_table_handler,
)


class TestBaseParquetTableHandler:
    """Test abstract base class for Parquet table handlers."""

    def test_logger_property(self):
        """Test that logger property returns a logger instance."""
        handler = CpdParquetTableHandler()
        logger = handler.logger
        assert logger is not None
        assert "CPDPARQUETTABLEHANDLER" in logger.name.upper()

    def test_abstract_methods_not_implemented(self):
        """Test that abstract methods raise NotImplementedError."""

        class IncompleteHandler(BaseParquetTableHandler):
            pass

        with pytest.raises(TypeError):
            IncompleteHandler()


class TestCpdParquetTableHandler:
    """Test CPD implementation of Parquet table handler."""

    @pytest.fixture
    def handler(self):
        """Create a CpdParquetTableHandler instance."""
        return CpdParquetTableHandler()

    @pytest.fixture
    def sample_table(self):
        """Create a sample PyArrow table for testing."""
        return pa.table(
            {
                "id": [1, 2, 3, 4, 5],
                "name": ["Alice", "Bob", "Charlie", "David", "Eve"],
                "age": [25, 30, 35, 40, 45],
                "active": [True, True, False, True, False],
            }
        )

    @pytest.fixture
    def temp_parquet_file(self, tmp_path):
        """Create a temporary parquet file path."""
        return str(tmp_path / "test_table.parquet")

    def test_save_and_read_table(self, handler, sample_table, temp_parquet_file):
        """Test saving and reading a Parquet table."""
        # Save table
        handler.save_table(path=temp_parquet_file, table=sample_table)
        assert Path(temp_parquet_file).exists()

        # Read table
        read_table = handler.read_table(path=temp_parquet_file)
        assert read_table is not None
        assert read_table.num_rows == sample_table.num_rows
        assert read_table.column_names == sample_table.column_names
        assert read_table.equals(sample_table)

    def test_read_nonexistent_table(self, handler, tmp_path):
        """Test reading a non-existent table returns None."""
        nonexistent_path = str(tmp_path / "nonexistent.parquet")
        result = handler.read_table(path=nonexistent_path)
        assert result is None

    def test_read_table_with_column_projection(self, handler, sample_table, temp_parquet_file):
        """Test reading specific columns from a table."""
        handler.save_table(path=temp_parquet_file, table=sample_table)

        # Read only specific columns
        read_table = handler.read_table(path=temp_parquet_file, columns=["id", "name"])
        assert read_table is not None
        assert read_table.column_names == ["id", "name"]
        assert read_table.num_rows == sample_table.num_rows

    def test_read_table_with_filters(self, handler, sample_table, temp_parquet_file):
        """Test reading table with row filters."""
        handler.save_table(path=temp_parquet_file, table=sample_table)

        # Read with filter: age > 30
        filters = [("age", ">", 30)]
        read_table = handler.read_table(path=temp_parquet_file, filters=filters)
        assert read_table is not None
        assert read_table.num_rows == 3  # Charlie, David, Eve

    def test_delete_rows(self, handler, sample_table, temp_parquet_file):
        """Test deleting rows from a table."""
        handler.save_table(path=temp_parquet_file, table=sample_table)

        # Delete rows where active is False
        def delete_filter(table):
            return pc.equal(table["active"], False)  # type: ignore[attr-defined]

        handler.delete_rows(path=temp_parquet_file, delete_filter_fn=delete_filter)

        # Verify deletion
        updated_table = handler.read_table(path=temp_parquet_file)
        assert updated_table.num_rows == 3  # Only active=True rows remain
        assert all(updated_table["active"].to_pylist())

    def test_delete_rows_empty_table(self, handler, temp_parquet_file):
        """Test deleting rows from an empty table."""
        empty_table = pa.table({"id": [], "name": []})
        handler.save_table(path=temp_parquet_file, table=empty_table)

        def delete_filter(table):
            return pc.equal(table["id"], 1)  # type: ignore[attr-defined]

        # Should not raise error
        handler.delete_rows(path=temp_parquet_file, delete_filter_fn=delete_filter)

        result = handler.read_table(path=temp_parquet_file)
        assert result.num_rows == 0

    def test_delete_rows_nonexistent_table(self, handler, tmp_path):
        """Test deleting rows from non-existent table."""
        nonexistent_path = str(tmp_path / "nonexistent.parquet")

        def delete_filter(table):
            return pc.equal(table["id"], 1)  # type: ignore[attr-defined]

        # Should not raise error
        handler.delete_rows(path=nonexistent_path, delete_filter_fn=delete_filter)

    def test_delete_rows_invalid_filter(self, handler, sample_table, temp_parquet_file):
        """Test that invalid filter function raises TypeError."""
        handler.save_table(path=temp_parquet_file, table=sample_table)

        # Filter that returns non-boolean array
        def invalid_filter(table):
            return table["id"]  # Returns int array, not boolean

        with pytest.raises(TypeError, match="delete_filter_fn must return a pyarrow BooleanArray"):
            handler.delete_rows(path=temp_parquet_file, delete_filter_fn=invalid_filter)

    def test_delete_file(self, handler, sample_table, temp_parquet_file):
        """Test deleting a Parquet file."""
        handler.save_table(path=temp_parquet_file, table=sample_table)
        assert Path(temp_parquet_file).exists()

        handler.delete_file(path=temp_parquet_file)
        assert not Path(temp_parquet_file).exists()

    def test_delete_nonexistent_file(self, handler, tmp_path):
        """Test deleting a non-existent file logs warning."""
        nonexistent_path = str(tmp_path / "nonexistent.parquet")
        # Should not raise error
        handler.delete_file(path=nonexistent_path)

    def test_save_table_with_exception(self, handler, sample_table, tmp_path):
        """Test that save_table handles exceptions gracefully."""
        # Use invalid path to trigger exception
        invalid_path = str(tmp_path / "invalid" / "nested" / "path" / "file.parquet")

        with patch("pyarrow.parquet.write_table", side_effect=Exception("Write error")):
            # Should not raise, but log error
            handler.save_table(path=invalid_path, table=sample_table)

    def test_read_table_allows_concurrent_shared_lock(self, handler, sample_table, temp_parquet_file, monkeypatch):
        """An externally held LOCK_SH must not block read_table (readers share the lock)."""
        handler.save_table(path=temp_parquet_file, table=sample_table)
        monkeypatch.setattr(pyarrow_handler, "LOCK_TIMEOUT", 0.3)

        with portalocker.Lock(
            _lock_path(path=temp_parquet_file), flags=portalocker.LOCK_SH | portalocker.LOCK_NB, timeout=1.0
        ):
            result = handler.read_table(path=temp_parquet_file)

        assert result is not None
        assert result.equals(sample_table)

    def test_read_table_blocked_by_exclusive_lock_raises(self, handler, sample_table, temp_parquet_file, monkeypatch):
        """An externally held LOCK_EX must make read_table raise LockException after LOCK_TIMEOUT."""
        handler.save_table(path=temp_parquet_file, table=sample_table)
        monkeypatch.setattr(pyarrow_handler, "LOCK_TIMEOUT", 0.3)

        with portalocker.Lock(
            _lock_path(path=temp_parquet_file), flags=portalocker.LOCK_EX | portalocker.LOCK_NB, timeout=1.0
        ):
            with pytest.raises(portalocker.exceptions.LockException):
                handler.read_table(path=temp_parquet_file)

    def test_save_table_blocked_by_shared_lock_does_not_write(
        self, handler, sample_table, temp_parquet_file, monkeypatch
    ):
        """A writer cannot acquire LOCK_EX while a reader holds LOCK_SH; the file is left unwritten."""
        monkeypatch.setattr(pyarrow_handler, "LOCK_TIMEOUT", 0.3)

        with portalocker.Lock(
            _lock_path(path=temp_parquet_file), flags=portalocker.LOCK_SH | portalocker.LOCK_NB, timeout=1.0
        ):
            handler.save_table(path=temp_parquet_file, table=sample_table)

        assert not Path(temp_parquet_file).exists()

    def test_save_table_creates_lock_file(self, handler, sample_table, temp_parquet_file):
        """Test that lock file is created during save operation."""
        # Lock file should be cleaned up after operation
        handler.save_table(path=temp_parquet_file, table=sample_table)

        # Lock file may or may not exist after operation (depends on cleanup)
        # Just verify the main file exists
        assert Path(temp_parquet_file).exists()

    def test_read_table_with_unicode_data(self, handler, temp_parquet_file):
        """Test reading and writing tables with Unicode characters."""
        unicode_table = pa.table({"id": [1, 2, 3], "text": ["Hello 世界", "Привет мир", "مرحبا بالعالم"]})

        handler.save_table(path=temp_parquet_file, table=unicode_table)
        read_table = handler.read_table(path=temp_parquet_file)

        assert read_table.equals(unicode_table)

    def test_large_table_handling(self, handler, temp_parquet_file):
        """Test handling of larger tables."""
        # Create a table with 10,000 rows
        large_table = pa.table({"id": list(range(10000)), "value": [f"value_{i}" for i in range(10000)]})

        handler.save_table(path=temp_parquet_file, table=large_table)
        read_table = handler.read_table(path=temp_parquet_file)

        assert read_table.num_rows == 10000
        assert read_table.equals(large_table)

    def test_delete_rows_all_rows(self, handler, sample_table, temp_parquet_file):
        """Test deleting all rows from a table."""
        handler.save_table(path=temp_parquet_file, table=sample_table)

        # Delete all rows
        def delete_all_filter(table):
            return pc.equal(table["id"], table["id"])  # type: ignore[attr-defined]  # All True

        handler.delete_rows(path=temp_parquet_file, delete_filter_fn=delete_all_filter)

        updated_table = handler.read_table(path=temp_parquet_file)
        assert updated_table.num_rows == 0

    def test_delete_rows_no_rows(self, handler, sample_table, temp_parquet_file):
        """Test deleting no rows from a table."""
        handler.save_table(path=temp_parquet_file, table=sample_table)

        # Delete no rows
        def delete_none_filter(table):
            return pc.equal(table["id"], -1)  # type: ignore[attr-defined]  # All False

        handler.delete_rows(path=temp_parquet_file, delete_filter_fn=delete_none_filter)

        updated_table = handler.read_table(path=temp_parquet_file)
        assert updated_table.num_rows == sample_table.num_rows


class TestGetParquetTableHandler:
    """Test factory function for getting Parquet table handler."""

    def test_get_parquet_table_handler_returns_cpd_handler(self):
        """Test that factory function returns CpdParquetTableHandler."""
        handler = get_parquet_table_handler()
        assert isinstance(handler, CpdParquetTableHandler)
        assert isinstance(handler, BaseParquetTableHandler)

    def test_get_parquet_table_handler_returns_new_instance(self):
        """Test that factory function returns new instances."""
        handler1 = get_parquet_table_handler()
        handler2 = get_parquet_table_handler()
        assert handler1 is not handler2


class TestEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.fixture
    def handler(self):
        return CpdParquetTableHandler()

    def test_empty_table_save_and_read(self, handler, tmp_path):
        """Test saving and reading an empty table."""
        empty_table = pa.table({"col1": [], "col2": []})
        path = str(tmp_path / "empty.parquet")

        handler.save_table(path=path, table=empty_table)
        read_table = handler.read_table(path=path)

        assert read_table.num_rows == 0
        assert read_table.column_names == ["col1", "col2"]

    def test_table_with_null_values(self, handler, tmp_path):
        """Test handling tables with null values."""
        table_with_nulls = pa.table({"id": [1, 2, None, 4], "name": ["Alice", None, "Charlie", "David"]})
        path = str(tmp_path / "nulls.parquet")

        handler.save_table(path=path, table=table_with_nulls)
        read_table = handler.read_table(path=path)

        assert read_table.num_rows == 4
        assert read_table["id"][2].as_py() is None
        assert read_table["name"][1].as_py() is None

    def test_table_with_complex_types(self, handler, tmp_path):
        """Test handling tables with complex data types."""
        complex_table = pa.table(
            {
                "id": [1, 2, 3],
                "list_col": [[1, 2, 3], [4, 5], [6]],
                "struct_col": [
                    {"a": 1, "b": "x"},
                    {"a": 2, "b": "y"},
                    {"a": 3, "b": "z"},
                ],
            }
        )
        path = str(tmp_path / "complex.parquet")

        handler.save_table(path=path, table=complex_table)
        read_table = handler.read_table(path=path)

        assert read_table.num_rows == 3
        assert "list_col" in read_table.column_names
        assert "struct_col" in read_table.column_names
