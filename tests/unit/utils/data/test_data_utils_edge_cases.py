# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Edge-case tests for docpipe.utils.data.pyarrow_handler and docpipe.utils.data.schema_utils."""

from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from docpipe.utils.data.pyarrow_handler import CpdParquetTableHandler
from docpipe.utils.data.schema_utils import _combine_tables


class TestDeleteRowsEmptyTable:
    """Tests for delete_rows on an existing but empty Parquet file."""

    def test_empty_table_is_left_untouched(self, tmp_path):
        """No filter is applied and nothing is saved when the stored table has no rows."""
        path = str(tmp_path / "empty.parquet")
        pq.write_table(pa.table({"id": pa.array([], type=pa.string())}), path)
        handler = CpdParquetTableHandler()
        calls = []

        def _filter(table):
            calls.append(table)
            return pc.equal(table["id"], "x")  # type: ignore[attr-defined]

        with patch.object(handler, "save_table") as mock_save:
            handler.delete_rows(path=path, delete_filter_fn=_filter)

        assert calls == []
        mock_save.assert_not_called()


class TestDeleteFileErrors:
    """Tests for delete_file error handling."""

    def test_unlink_failure_is_logged_not_raised(self, tmp_path):
        """Errors while deleting are logged and swallowed; the file stays in place."""
        path = tmp_path / "data.parquet"
        path.write_bytes(b"x")
        handler = CpdParquetTableHandler()

        with (
            patch.object(Path, "unlink", side_effect=PermissionError("locked")),
            patch.object(CpdParquetTableHandler, "logger") as mock_logger,
        ):
            handler.delete_file(path=str(path))

        assert path.exists()
        mock_logger.exception.assert_called_once()
        assert mock_logger.exception.call_args.args[0] == "locked"


class TestCombineTablesErrors:
    """Tests for _combine_tables failure handling."""

    def test_incompatible_schemas_return_none(self):
        """Tables whose column types cannot be unified yield None instead of raising."""
        left = pa.table({"col": pa.array([1, 2], type=pa.int64())})
        right = pa.table({"col": pa.array([[1], [2]], type=pa.list_(pa.int64()))})

        with patch("docpipe.utils.data.schema_utils.get_logger") as mock_get_logger:
            assert _combine_tables([left, right], "chunk tables") is None

        warning = mock_get_logger.return_value.warning
        warning.assert_called_once()
        assert "Failed to combine chunk tables" in warning.call_args.args[0]
