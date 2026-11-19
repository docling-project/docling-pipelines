"""Unit tests for orchestrator_utils module."""

import os
import shutil
import tempfile
from pathlib import Path
from queue import Queue
from unittest.mock import Mock, patch

import pyarrow as pa
import pytest

from docpipe.utils.data.schema_utils import (
    _combine_tables,
    _total_rows,
    align_table_schema,
)
from docpipe.utils.orchestration.deleted_rows_tracker import (
    combine_cumulative_deleted_rows,
    update_deleted_rows,
)
from docpipe.utils.orchestration.flow_utils import (
    construct_deleted_rows_table_path,
    create_log_folders,
    create_node_id_to_index_map,
    write_job_logs,
)
from docpipe.utils.orchestration.prefect_config import (
    PREFECT_API_DATABASE_CONNECTION_URL,
    PREFECT_DEBUG,
    PREFECT_HOME,
    _safe_rmtree,
    clean_up_prefect_home,
    set_prefect_env_variables,
)


class TestCreateNodeIdToIndexMap:
    """Test create_node_id_to_index_map function."""

    def test_create_node_id_to_index_map_basic(self):
        """Test basic node ID to index mapping."""
        flow_def = [
            {"id": "node_1", "name": "Node 1"},
            {"id": "node_2", "name": "Node 2"},
            {"id": "node_3", "name": "Node 3"},
        ]

        result = create_node_id_to_index_map(flow_def=flow_def)

        assert result == {"node_1": 0, "node_2": 1, "node_3": 2}

    def test_create_node_id_to_index_map_empty(self):
        """Test with empty flow definition."""
        result = create_node_id_to_index_map(flow_def=[])
        assert result == {}

    def test_create_node_id_to_index_map_single_node(self):
        """Test with single node."""
        flow_def = [{"id": "single_node"}]
        result = create_node_id_to_index_map(flow_def=flow_def)
        assert result == {"single_node": 0}


class TestCreateLogFolders:
    """Test create_log_folders function."""

    @patch("docpipe.utils.infrastructure.filesystem.get_data_path")
    def test_create_log_folders_job_type(self, mock_data_path):
        """Test creating log folders for job type."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_data_path.return_value = tmpdir

            result = create_log_folders("job_123", "run_456", "job")

            assert "job_123" in result
            assert "run_456" in result
            assert "job_stats.json" in result
            assert Path(Path(result).parent).exists()

    @patch("docpipe.utils.infrastructure.filesystem.get_data_path")
    def test_create_log_folders_agg_logs_type(self, mock_data_path):
        """Test creating log folders for aggregated logs type."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_data_path.return_value = tmpdir

            result = create_log_folders("job_789", "run_012", "agg_logs")

            assert "flow_execute_aggregated.json" in result

    def test_create_log_folders_unknown_type_raises_before_creating_folders(self):
        """An unknown log type raises ValueError and leaves the disk untouched (#668)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("docpipe.utils.orchestration.flow_utils.get_data_path", return_value=tmpdir):
                with pytest.raises(ValueError, match="other"):
                    create_log_folders("job_x", "run_y", "other")

            assert not (Path(tmpdir) / "job_x").exists()


class TestWriteJobLogs:
    """Test write_job_logs function."""

    def test_write_job_logs(self):
        """Test writing job logs to file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            temp_path = f.name

        try:
            job_stats = Mock()
            job_stats.__dict__ = {"status": "completed", "duration": 60.5}

            write_job_logs(job_stats, temp_path)

            assert Path(temp_path).exists()
            with Path(temp_path).open() as f:
                import json

                content = json.load(f)
                assert content["status"] == "completed"
                assert content["duration"] == 60.5
        finally:
            if Path(temp_path).exists():
                Path(temp_path).unlink()


class TestSetPrefectEnvVariables:
    """Test set_prefect_env_variables function."""

    def test_set_prefect_env_variables_without_debug(self):
        """Test setting Prefect env variables without debug mode."""
        # Clear any existing PREFECT_DEBUG
        if PREFECT_DEBUG in os.environ:
            del os.environ[PREFECT_DEBUG]

        set_prefect_env_variables()

        assert PREFECT_HOME in os.environ
        assert PREFECT_API_DATABASE_CONNECTION_URL in os.environ
        assert os.environ[PREFECT_API_DATABASE_CONNECTION_URL] == "sqlite+aiosqlite:///:memory:"

        # Cleanup
        if PREFECT_HOME in os.environ:
            prefect_home = os.environ[PREFECT_HOME]
            if Path(prefect_home).exists():
                shutil.rmtree(prefect_home, ignore_errors=True)
            del os.environ[PREFECT_HOME]

    def test_set_prefect_env_variables_with_debug(self):
        """Test setting Prefect env variables with debug mode."""
        os.environ[PREFECT_DEBUG] = "true"

        # Clear PREFECT_HOME if it exists
        if PREFECT_HOME in os.environ:
            del os.environ[PREFECT_HOME]

        set_prefect_env_variables()

        # In debug mode, PREFECT_HOME should not be set to temp directory
        # and in-memory DB should not be forced

        # Cleanup
        if PREFECT_DEBUG in os.environ:
            del os.environ[PREFECT_DEBUG]


class TestCleanUpPrefectHome:
    """Test clean_up_prefect_home function."""

    def test_clean_up_prefect_home_removes_temp_dir(self):
        """Test that Prefect home directory is cleaned up."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prefect_temp = str(Path(tmpdir) / "prefect_test")
            Path(prefect_temp).mkdir(parents=True)

            os.environ[PREFECT_HOME] = prefect_temp

            clean_up_prefect_home()

            # Directory should be removed
            assert not Path(prefect_temp).exists()

            # Cleanup env var
            if PREFECT_HOME in os.environ:
                del os.environ[PREFECT_HOME]

    def test_clean_up_prefect_home_with_debug(self):
        """Test cleanup doesn't happen in debug mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prefect_temp = str(Path(tmpdir) / "prefect_test")
            Path(prefect_temp).mkdir(parents=True)

            os.environ[PREFECT_HOME] = prefect_temp
            os.environ[PREFECT_DEBUG] = "true"

            clean_up_prefect_home()

            # Directory should still exist in debug mode
            assert Path(prefect_temp).exists()

            # Cleanup
            if PREFECT_HOME in os.environ:
                del os.environ[PREFECT_HOME]
            if PREFECT_DEBUG in os.environ:
                del os.environ[PREFECT_DEBUG]


class TestSafeRmtree:
    """Test _safe_rmtree function."""

    def test_safe_rmtree_valid_temp_dir(self):
        """Test removing valid temp directory."""
        temp_root = tempfile.gettempdir()
        test_dir = str(Path(temp_root) / "prefect_test_dir")
        Path(test_dir).mkdir(parents=True, exist_ok=True)

        result = _safe_rmtree(test_dir, prefix="prefect_")

        assert result is True
        assert not Path(test_dir).exists()

    def test_safe_rmtree_outside_temp(self):
        """Test that directories outside temp are not removed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a directory outside system temp
            test_dir = str(Path(tmpdir) / "test_dir")
            Path(test_dir).mkdir(parents=True)

            result = _safe_rmtree(test_dir, prefix="prefect_")

            # Should refuse to delete
            assert result is False
            assert Path(test_dir).exists()

    def test_safe_rmtree_wrong_prefix(self):
        """Test that directories with wrong prefix are not removed."""
        temp_root = tempfile.gettempdir()
        test_dir = str(Path(temp_root) / "wrong_prefix_dir")
        Path(test_dir).mkdir(parents=True, exist_ok=True)

        try:
            result = _safe_rmtree(test_dir, prefix="prefect_")

            assert result is False
            assert Path(test_dir).exists()
        finally:
            if Path(test_dir).exists():
                shutil.rmtree(test_dir, ignore_errors=True)

    def test_safe_rmtree_nonexistent_path(self):
        """Test with nonexistent path."""
        temp_root = tempfile.gettempdir()
        test_dir = str(Path(temp_root) / "prefect_nonexistent")

        result = _safe_rmtree(test_dir, prefix="prefect_")

        assert result is False


class TestAlignTableSchema:
    """Test align_table_schema function."""

    def test_align_table_schema_adds_missing_columns(self):
        """Test that missing columns are added."""
        table = pa.table({"col1": [1, 2, 3]})
        all_cols = {"col1": pa.int64(), "col2": pa.string()}

        result = align_table_schema(table, all_cols)

        assert "col1" in result.column_names
        assert "col2" in result.column_names
        assert result.num_rows == 3

    def test_align_table_schema_maintains_order(self):
        """Test that column order is maintained."""
        table = pa.table({"col2": [1, 2], "col1": [3, 4]})
        all_cols = {"col1": pa.int64(), "col2": pa.int64()}

        result = align_table_schema(table, all_cols)

        # Columns should be sorted
        assert result.column_names == ["col1", "col2"]


class TestCombineCumulativeDeletedRows:
    """Test combine_cumulative_deleted_rows function."""

    def test_combine_cumulative_deleted_rows_basic(self):
        """Test combining deleted rows."""
        deleted_rows: Queue = Queue()
        deleted_rows.put(pa.table({"id": [1, 2], "name": ["a", "b"]}))
        deleted_rows.put(pa.table({"id": [3, 4], "name": ["c", "d"]}))

        result = combine_cumulative_deleted_rows(deleted_rows)

        assert result.num_rows == 4
        assert "id" in result.column_names
        assert "name" in result.column_names

    def test_combine_cumulative_deleted_rows_different_schemas(self):
        """Test combining tables with different schemas."""
        deleted_rows: Queue = Queue()
        deleted_rows.put(pa.table({"id": [1, 2], "col1": ["a", "b"]}))
        deleted_rows.put(pa.table({"id": [3, 4], "col2": ["c", "d"]}))

        result = combine_cumulative_deleted_rows(deleted_rows)

        assert result.num_rows == 4
        assert "id" in result.column_names
        assert "col1" in result.column_names
        assert "col2" in result.column_names

    def test_combine_cumulative_deleted_rows_empty(self):
        """Test with empty queue."""
        deleted_rows: Queue = Queue()

        result = combine_cumulative_deleted_rows(deleted_rows)

        assert result.num_rows == 0


class TestCombineTables:
    """Test _combine_tables function."""

    def test_combine_tables_basic(self):
        """Test combining multiple tables."""
        tables = [
            pa.table({"id": [1, 2], "value": [10, 20]}),
            pa.table({"id": [3, 4], "value": [30, 40]}),
        ]

        result = _combine_tables(tables, "test tables")

        assert result.num_rows == 4
        assert result.column_names == ["id", "value"]

    def test_combine_tables_empty_list(self):
        """Test with empty list."""
        result = _combine_tables([], "test tables")
        assert result is None

    def test_combine_tables_with_duplicates(self):
        """Test combining tables with duplicate IDs."""
        tables = [
            pa.table({"id": [1, 2], "value": [10, 20]}),
            pa.table({"id": [2, 3], "value": [25, 30]}),
        ]

        result = _combine_tables(tables, "test tables")

        # Should still combine but log warning about duplicates
        assert result.num_rows == 4


class TestTotalRows:
    """Test _total_rows function."""

    def test_total_rows_single_table(self):
        """Test with single PyArrow table."""
        table = pa.table({"id": [1, 2, 3]})
        result = _total_rows(table)
        assert result == 3

    def test_total_rows_dict_of_tables(self):
        """Test with dict of tables."""
        tables = {
            "table1": pa.table({"id": [1, 2]}),
            "table2": pa.table({"id": [3, 4, 5]}),
        }
        result = _total_rows(tables)
        assert result == 5

    def test_total_rows_list_of_tables(self):
        """Test with list of tables."""
        tables = [
            pa.table({"id": [1, 2]}),
            pa.table({"id": [3, 4, 5]}),
        ]
        result = _total_rows(tables)
        assert result == 5

    def test_total_rows_none(self):
        """Test with None."""
        result = _total_rows(None)
        assert result == 0


class TestUpdateDeletedRows:
    """Test update_deleted_rows function."""

    def test_update_deleted_rows_no_deletions(self):
        """Test when no rows are deleted."""
        prev_table = pa.table({"id": [1, 2, 3], "value": [10, 20, 30]})
        current_tables = [pa.table({"id": [1, 2, 3], "value": [10, 20, 30]})]

        mock_op = Mock()
        mock_op.config = {}
        mock_op.id = "op1"
        mock_op.name = "Test Op"

        result = update_deleted_rows(prev_table, current_tables, [], mock_op)

        assert result.num_rows == 0

    def test_update_deleted_rows_with_deletions(self):
        """Test when rows are deleted."""
        prev_table = pa.table({"id": [1, 2, 3], "value": [10, 20, 30]})
        current_tables = [pa.table({"id": [1, 2], "value": [10, 20]})]

        mock_op = Mock()
        mock_op.config = {}
        mock_op.id = "op1"
        mock_op.name = "Test Op"

        result = update_deleted_rows(prev_table, current_tables, [], mock_op)

        assert result.num_rows == 1
        assert result["id"].to_pylist() == [3]
        assert "deleted_at_step" in result.column_names

    def test_update_deleted_rows_skip_columns(self):
        """Test that specified columns are skipped."""
        prev_table = pa.table({"id": [1, 2, 3], "content": ["a", "b", "c"], "value": [10, 20, 30]})
        current_tables = [pa.table({"id": [1, 2], "content": ["a", "b"], "value": [10, 20]})]

        mock_op = Mock()
        mock_op.config = {}
        mock_op.id = "op1"
        mock_op.name = "Test Op"

        result = update_deleted_rows(prev_table, current_tables, ["content"], mock_op)

        assert "content" not in result.column_names
        assert "id" in result.column_names
        assert "value" in result.column_names

    def test_update_deleted_rows_dict_prev_tables(self):
        """Test with dict of previous tables."""
        prev_tables = {
            "branch1": pa.table({"id": [1, 2], "value": [10, 20]}),
            "branch2": pa.table({"id": [3, 4], "value": [30, 40]}),
        }
        current_tables = [pa.table({"id": [1, 3], "value": [10, 30]})]

        mock_op = Mock()
        mock_op.config = {}
        mock_op.id = "op1"
        mock_op.name = "Test Op"

        result = update_deleted_rows(prev_tables, current_tables, [], mock_op)

        assert result.num_rows == 2  # IDs 2 and 4 deleted


class TestConstructDeletedRowsTablePath:
    """Test construct_deleted_rows_table_path function."""

    @patch("docpipe.utils.infrastructure.filesystem.get_data_path")
    def test_construct_deleted_rows_table_path(self, mock_data_path):
        """Test constructing deleted rows table path."""
        mock_data_path.return_value = "/warehouse"

        result = construct_deleted_rows_table_path(job_id="job_123", job_run_id="run_456")

        assert "job_123" in result
        assert "run_456" in result
        assert "unprocessed_docs.parquet" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
