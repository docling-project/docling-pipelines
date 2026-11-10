"""Unit tests covering missing lines in AbstractOperatorExecutor."""

from queue import Queue
from typing import Any
from unittest.mock import Mock, patch

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import DocpipeConstants, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.orchestration.python.python_operator_executor import PythonOperatorExecutor


def _make_executor(job_stats_service=None):
    """Create a PythonOperatorExecutor with minimal params."""
    return PythonOperatorExecutor(
        name="test_node",
        operator="test_operator",
        params={
            OperatorConstants.Columns.ID: "node_1",
            OperatorConstants.Columns.NAME: "test_node",
            DocpipeConstants.JOB_ID: "job_1",
            DocpipeConstants.JOB_RUN_ID: "run_1",
        },
        job_stats_service=job_stats_service,
    )


class TestGetOutputFilePath:
    """Lines 246-248: get_output_file_path static method."""

    def test_output_file_path_with_trailing_slash(self):
        """Folder already ends with '/' — path appended directly."""
        da = Mock()
        da.get_output_folder.return_value = "/tmp/output/"
        result = PythonOperatorExecutor.get_output_file_path(data_access=da)
        assert result == "/tmp/output/output.parquet"

    def test_output_file_path_without_trailing_slash(self):
        """Line 247: folder does NOT end with '/' — slash is added."""
        da = Mock()
        da.get_output_folder.return_value = "/tmp/output"
        result = PythonOperatorExecutor.get_output_file_path(data_access=da)
        assert result == "/tmp/output/output.parquet"

    def test_output_file_path_none_folder(self):
        """Line 245: output_folder is None — returns empty string."""
        da = Mock()
        da.get_output_folder.return_value = None
        result = PythonOperatorExecutor.get_output_file_path(data_access=da)
        assert result == ""


class TestGetInputTables:
    """Lines 130, 135-142: _get_input_tables branches."""

    def test_none_data_access_returns_none(self):
        """Line 130: data_access is None — tables is None."""
        executor = _make_executor()
        result = executor._get_input_tables(data_access=None)
        assert result is None

    def test_dict_data_access_builds_tables_dict(self):
        """Lines 135-142: data_access is a dict — iterate and load each table."""
        executor = _make_executor()

        table_a = pa.table({"id": ["1", "2"]})
        table_b = pa.table({"id": ["3"]})

        da_a = Mock()
        da_b = Mock()
        da_a.get_output_folder.return_value = "/tmp/a"
        da_b.get_output_folder.return_value = "/tmp/b"
        da_a.get_table.return_value = (table_a, {})
        da_b.get_table.return_value = (table_b, {})

        data_access = {"link_a": da_a, "link_b": da_b}
        result = executor._get_input_tables(data_access=data_access)

        assert isinstance(result, dict)
        assert "link_a" in result
        assert "link_b" in result
        assert result["link_a"].num_rows == 2
        assert result["link_b"].num_rows == 1

    def test_dict_data_access_skips_none_values(self):
        """Line 137-139: None value in dict is skipped (supports merge operator)."""
        executor = _make_executor()

        table_a = pa.table({"id": ["1"]})
        da_a = Mock()
        da_a.get_output_folder.return_value = "/tmp/a"
        da_a.get_table.return_value = (table_a, {})

        data_access = {"link_a": da_a, "link_b": None}
        result = executor._get_input_tables(data_access=data_access)

        assert isinstance(result, dict)
        assert "link_a" in result
        assert "link_b" not in result


class TestValidateAndGetMetadata:
    """Lines 108-109, 115-116: validate() and get_metadata() delegate to operator."""

    def test_validate_delegates_to_operator(self):
        """Lines 108-109: validate() calls op.validate()."""
        executor = _make_executor()
        mock_op = Mock()
        executor.get_operator = Mock(return_value=mock_op)

        errors: list[Any] = []
        warnings: list[str] = []
        features = ["col1"]
        executor.validate(errors=errors, warnings=warnings, available_features=features)

        mock_op.validate.assert_called_once_with(errors=errors, warnings=warnings, available_features=features)

    def test_validate_ingest_without_provider(self):
        """The executor supports the ingest operator's keyword-only validation contract."""
        from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator

        executor = _make_executor()
        executor.get_operator = Mock(return_value=IngestSourceOperator({"provider": None}))
        errors: list[Any] = []

        executor.validate(errors=errors, warnings=[], available_features=[])

        assert len(errors) == 1
        assert errors[0].message_code == "INGEST_PROVIDER_MISSING"

    def test_get_metadata_delegates_to_operator(self):
        """Lines 115-116: get_metadata() calls op.get_metadata()."""
        executor = _make_executor()
        mock_op = Mock()
        mock_op.get_metadata.return_value = {"schema": "info"}
        executor.get_operator = Mock(return_value=mock_op)

        result = executor.get_metadata()

        mock_op.get_metadata.assert_called_once()
        assert result == {"schema": "info"}


class TestJobStatsServiceNone:
    """Lines 161-162, 197-198: warn and return early when job_stats_service is None."""

    def test_set_default_node_stats_no_service_logs_warning(self):
        """Lines 161-162: no job_stats_service causes early return with warning."""
        executor = _make_executor(job_stats_service=None)
        table = pa.table({"id": ["1"]})
        # Should not raise — just log warning and return
        executor.set_default_node_stats(tables=table)

    def test_update_final_node_stats_no_service_logs_warning(self):
        """Lines 197-198: no job_stats_service causes early return with warning."""
        executor = _make_executor(job_stats_service=None)
        table = pa.table({"id": ["1"]})
        # Should not raise — just log warning and return
        executor.update_final_node_stats(tables=[table], metadata={})


class TestAddEmptyDocsToSkippedMetadataExtraPaths:
    """Lines 381, 409: remaining branches in _add_empty_docs_to_skipped_metadata."""

    @pytest.fixture
    def executor(self):
        exc = _make_executor()
        mock_op = Mock()
        mock_op.record_skipped_document = Mock()
        exc.get_operator = Mock(return_value=mock_op)
        return exc

    def test_empty_indices_returns_early(self, executor):
        """Line 381: empty_doc_indices=[] returns early before calling get_operator."""
        table = pa.table({"id": ["doc1"], "content": ["valid"]})
        metadata: dict[str, Any] = {}
        executor._add_empty_docs_to_skipped_metadata(table=table, empty_doc_indices=[], metadata=metadata)
        # get_operator must NOT be called
        executor.get_operator.assert_not_called()

    def test_processed_docs_decremented(self, executor):
        """Line 409: PROCESSED_DOCS in metadata is decremented by number of empty docs."""
        table = pa.table(
            {
                OperatorConstants.Columns.ID: ["doc1", "doc2", "doc3"],
                OperatorConstants.Columns.NAME: ["f1.pdf", "f2.pdf", "f3.pdf"],
            }
        )
        metadata = {Metrics.External.PROCESSED_DOCS: 10}

        executor._add_empty_docs_to_skipped_metadata(table=table, empty_doc_indices=[0, 1], metadata=metadata)

        assert metadata[Metrics.External.PROCESSED_DOCS] == 8


class TestExecuteDeletedRowsBranch:
    """Line 77: deleted_rows_list.put() called when update_deleted_rows returns rows."""

    def test_deleted_rows_put_when_rows_present(self):
        """Line 77: if deleted_rows has rows, they are enqueued."""
        executor = _make_executor()
        mock_op = Mock()

        out_table = pa.table({"id": ["1"]})
        deleted = pa.table({"id": ["deleted_doc"]})  # non-empty
        deleted_rows_list: Queue = Queue()

        with (
            patch.object(executor, "_get_input_tables", return_value=out_table),
            patch.object(executor, "_execute_impl", return_value=([out_table], {})),
            patch.object(executor, "create_data_accesses", return_value=[Mock()]),
            patch.object(executor, "get_operator", return_value=mock_op),
            patch(
                "docpipe.core.orchestration.abstract_operator_executor.update_deleted_rows",
                return_value=deleted,
            ),
        ):
            executor.execute(data_access=None, deleted_rows_list=deleted_rows_list)

        assert not deleted_rows_list.empty()
        assert deleted_rows_list.get() is deleted

    def test_deleted_rows_not_put_when_zero_rows(self):
        """Line 76 taken/77 skipped: empty deleted table does NOT enqueue."""
        executor = _make_executor()
        mock_op = Mock()

        out_table = pa.table({"id": ["1"]})
        empty_deleted = pa.table({"id": pa.array([], type=pa.string())})
        deleted_rows_list: Queue = Queue()

        with (
            patch.object(executor, "_get_input_tables", return_value=out_table),
            patch.object(executor, "_execute_impl", return_value=([out_table], {})),
            patch.object(executor, "create_data_accesses", return_value=[Mock()]),
            patch.object(executor, "get_operator", return_value=mock_op),
            patch(
                "docpipe.core.orchestration.abstract_operator_executor.update_deleted_rows",
                return_value=empty_deleted,
            ),
        ):
            executor.execute(data_access=None, deleted_rows_list=deleted_rows_list)

        assert deleted_rows_list.empty()
