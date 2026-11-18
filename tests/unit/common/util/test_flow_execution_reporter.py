"""Unit tests for FlowExecutionReporter."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import ExecutionStatus
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.job_management.domain.models.job_stats import JobStats
from docpipe.core.job_management.domain.models.node_stats import NodeStats
from docpipe.utils.infrastructure.flow_execution_reporter import FlowExecutionReporter


@pytest.fixture
def reporter():
    """Create a FlowExecutionReporter instance."""
    return FlowExecutionReporter()


@pytest.fixture
def sample_node_stats():
    """Create sample NodeStats for testing."""
    return NodeStats(
        id="test-node-123",
        name="test_operator",
        node_status=ExecutionStatus.COMPLETED.value,
        time_taken=5,
        col_names=["id", "name", "content"],
        docs_completed=["doc1", "doc2", "doc3"],
        failed_docs=[],
        skipped_docs=[],
    )


@pytest.fixture
def sample_job_stats():
    """Create sample JobStats for testing."""
    return JobStats(
        job_id="job-123",
        job_run_id="run-456",
        status=ExecutionStatus.COMPLETED,
        total_docs=10,
        processed_docs=8,
        completed_docs=8,
        failed_docs=1,
        skipped_docs=1,
        duration=25,
    )


@pytest.fixture
def sample_pyarrow_table():
    """Create a sample PyArrow table for testing."""
    return pa.table(
        {
            "id": ["doc1", "doc2", "doc3"],
            "name": ["file1.pdf", "file2.pdf", "file3.pdf"],
            "content": ["content1", "content2", "content3"],
        }
    )


class TestInitialization:
    """Tests for reporter initialization."""

    def test_init_sets_default_state(self, reporter):
        """Test reporter initializes with None values."""
        assert reporter._flow_start_time is None
        assert reporter._current_tables is None
        assert reporter._previous_tables is None


class TestFlowHeader:
    """Tests for flow header printing."""

    @patch("docpipe.utils.infrastructure.flow_execution_reporter.logger")
    def test_print_flow_header_sets_start_time(self, mock_logger, reporter):
        """Test flow header sets start time."""
        reporter.print_flow_header(flow_name="Test Flow", operator_count=5)

        assert reporter._flow_start_time is not None
        assert isinstance(reporter._flow_start_time, datetime)

    @patch("docpipe.utils.infrastructure.flow_execution_reporter.logger")
    def test_print_flow_header_logs_info(self, mock_logger, reporter):
        """Test flow header logs flow information."""
        reporter.print_flow_header(flow_name="Test Flow", operator_count=5)

        assert mock_logger.info.call_count >= 5
        calls = [str(call) for call in mock_logger.info.call_args_list]
        assert any("Test Flow" in str(call) for call in calls)


class TestOperatorMessages:
    """Tests for operator start and summary messages."""

    @patch("docpipe.utils.infrastructure.flow_execution_reporter.logger")
    def test_print_operator_start(self, mock_logger, reporter):
        """Test operator start message includes step name and type."""
        reporter.print_operator_start(step_name="step1", operator_type="extract_operator")

        mock_logger.info.assert_called_once_with("[%s] Starting %s...", "step1", "extract_operator")

    @patch("docpipe.utils.infrastructure.flow_execution_reporter.logger")
    def test_print_operator_summary_updates_table_state(
        self, mock_logger, reporter, sample_node_stats, sample_pyarrow_table
    ):
        """Test operator summary updates current and previous tables."""
        reporter.print_operator_summary(
            step_name="test_step", node_stats=sample_node_stats, tables=[sample_pyarrow_table]
        )

        assert reporter._current_tables == [sample_pyarrow_table]
        assert reporter._previous_tables == [sample_pyarrow_table]


class TestDurationFormatting:
    """Tests for duration formatting."""

    def test_format_duration_less_than_one_second(self, reporter):
        """Test duration formatting for sub-second values."""
        assert reporter._format_duration(0.5) == "< 1s"
        assert reporter._format_duration(0) == "< 1s"
        assert reporter._format_duration(None) == "< 1s"

    def test_format_duration_normal_values(self, reporter):
        """Test duration formatting for normal values."""
        assert reporter._format_duration(1.5) == "1.50s"
        assert reporter._format_duration(10) == "10.00s"
        assert reporter._format_duration(123.456) == "123.46s"


class TestColumnTracking:
    """Tests for column name tracking and new column detection."""

    def test_get_new_columns_first_operator(self, reporter):
        """Test all columns are new for first operator."""
        col_names = ["id", "name", "content"]
        new_cols = reporter._get_new_columns(col_names=col_names)

        assert new_cols == col_names

    def test_get_new_columns_with_previous_tables(self, reporter):
        """Test new column detection with previous tables."""
        prev_table = pa.table({"id": ["doc1"], "name": ["file1.pdf"]})
        curr_table = pa.table({"id": ["doc1"], "name": ["file1.pdf"], "content": ["text"], "embedding": [1.0]})

        reporter._previous_tables = [prev_table]
        reporter._current_tables = [curr_table]

        new_cols = reporter._get_new_columns(col_names=["id", "name", "content", "embedding"])

        assert "content" in new_cols
        assert "embedding" in new_cols
        assert "id" not in new_cols
        assert "name" not in new_cols

    def test_get_removed_columns_first_operator(self, reporter):
        """Test no columns are removed for first operator."""
        col_names = ["id", "name", "content"]
        removed_cols = reporter._get_removed_columns(col_names=col_names)

        assert removed_cols == []

    def test_get_removed_columns_with_previous_tables(self, reporter):
        """Test removed column detection with previous tables."""
        prev_table = pa.table({"id": ["doc1"], "name": ["file1.pdf"], "path": ["/tmp/file1.pdf"], "size": [1024]})
        curr_table = pa.table({"id": ["doc1"], "name": ["file1.pdf"], "content": ["text"]})

        reporter._previous_tables = [prev_table]
        reporter._current_tables = [curr_table]

        removed_cols = reporter._get_removed_columns(col_names=["id", "name", "content"])

        assert "path" in removed_cols
        assert "size" in removed_cols
        assert "id" not in removed_cols
        assert "name" not in removed_cols
        assert "content" not in removed_cols

    def test_get_removed_columns_no_previous_tables(self, reporter):
        """Test no columns removed when no previous tables."""
        curr_table = pa.table({"id": ["doc1"], "name": ["file1.pdf"]})
        reporter._current_tables = [curr_table]

        removed_cols = reporter._get_removed_columns(col_names=["id", "name"])

        assert removed_cols == []

    def test_extract_column_names_from_tables(self, reporter, sample_pyarrow_table):
        """Test extracting column names from PyArrow tables."""
        columns = reporter._extract_column_names([sample_pyarrow_table])
        assert columns == {"id", "name", "content"}

    def test_extract_column_names_handles_none(self, reporter):
        """Test extracting column names handles None gracefully."""
        columns = reporter._extract_column_names([None])
        assert columns == set()


class TestColumnGrouping:
    """Tests for column grouping and formatting."""

    def test_group_columns_by_prefix(self, reporter):
        """Test grouping columns by common prefix."""
        columns = ["ml_feature1", "ml_feature2", "lang_detect", "lang_score"]
        groups = reporter._group_columns_by_prefix(columns)

        assert "ML Features" in groups
        assert len(groups["ML Features"]) == 2
        assert "Language Features" in groups
        assert len(groups["Language Features"]) == 2

    def test_group_columns_without_prefix(self, reporter):
        """Test columns without prefix go to Other group."""
        columns = ["simple", "basic", "plain"]
        groups = reporter._group_columns_by_prefix(columns)

        assert "Other Features" in groups
        assert len(groups["Other Features"]) == 3

    def test_format_group_name_special_cases(self, reporter):
        """Test special group name formatting."""
        assert reporter._format_group_name("ml") == "ML Features"
        assert reporter._format_group_name("lang") == "Language Features"
        assert reporter._format_group_name("acl") == "ACL Features"

    def test_format_group_name_default(self, reporter):
        """Test default group name formatting."""
        assert reporter._format_group_name("custom") == "Custom Features"


class TestColumnListPrinting:
    """Tests for _print_column_list helper method."""

    @patch("docpipe.utils.infrastructure.flow_execution_reporter.logger")
    def test_print_column_list_few_columns(self, mock_logger, reporter):
        """Test printing few columns uses simple comma-separated format."""
        columns = ["id", "name", "content"]
        reporter._print_column_list(columns)

        mock_logger.info.assert_called_once_with("%s%s", "     ", "id, name, content")

    @patch("docpipe.utils.infrastructure.flow_execution_reporter.logger")
    def test_print_column_list_many_columns(self, mock_logger, reporter):
        """Test printing many columns uses wrapped format."""
        columns = [f"col_{i}" for i in range(15)]
        reporter._print_column_list(columns)

        assert mock_logger.info.call_count > 1

    @patch("docpipe.utils.infrastructure.flow_execution_reporter.logger")
    def test_print_column_list_very_many_columns(self, mock_logger, reporter):
        """Test printing very many columns uses grouped format."""
        columns = [f"ml_feature_{i}" for i in range(25)]
        reporter._print_column_list(columns)

        assert mock_logger.info.call_count > 1

    @patch("docpipe.utils.infrastructure.flow_execution_reporter.logger")
    def test_print_column_list_custom_indent(self, mock_logger, reporter):
        """Test custom indent is used."""
        columns = ["id", "name"]
        custom_indent = "       "
        reporter._print_column_list(columns, indent=custom_indent)

        mock_logger.info.assert_called_once_with("%s%s", custom_indent, "id, name")


class TestMetadataCategorization:
    """Tests for metadata categorization and filtering."""

    def test_categorize_metadata_by_type(self, reporter):
        """Test metadata is categorized by type."""
        metadata = {
            "chunk_count": 100,
            "config": {"model": "gpt-4"},
            "models": ["model1", "model2"],
            "description": "test",
        }

        categorized = reporter._categorize_metadata(metadata)

        assert "chunk_count" in categorized["numeric"]
        assert "config" in categorized["dict"]
        assert "models" in categorized["list"]
        assert "description" in categorized["other"]

    def test_categorize_metadata_filters_standard_fields(self, reporter):
        """Test standard fields are filtered from metadata."""
        metadata = {
            "documents_in_scope": 100,
            "processed_docs": 50,
            "custom_field": 42,
        }

        categorized = reporter._categorize_metadata(metadata)

        assert "custom_field" in categorized["numeric"]
        assert "documents_in_scope" not in categorized["numeric"]
        assert "processed_docs" not in categorized["numeric"]

    def test_categorize_metadata_handles_old_format(self, reporter):
        """Test metadata categorization handles old wrapped format."""
        metadata = {"node_metadata": {"chunk_count": 100}}

        # This should be handled by _print_operator_metadata
        reporter._print_operator_metadata(metadata)


class TestDocumentLookup:
    """Tests for document name lookup from PyArrow tables."""

    def test_lookup_doc_name_no_tables(self, reporter):
        """Test lookup returns None when no tables available."""
        result = reporter._lookup_doc_name_from_table("doc1")
        assert result is None

    def test_lookup_doc_name_found(self, reporter, sample_pyarrow_table):
        """Test successful document name lookup."""
        reporter._current_tables = [sample_pyarrow_table]
        result = reporter._lookup_doc_name_from_table("doc1")
        assert result == "file1.pdf"

    def test_lookup_doc_name_not_found(self, reporter, sample_pyarrow_table):
        """Test lookup returns None when ID not found."""
        reporter._current_tables = [sample_pyarrow_table]
        result = reporter._lookup_doc_name_from_table("nonexistent")
        assert result is None

    def test_lookup_doc_name_no_id_column(self, reporter):
        """Test lookup returns None when table has no ID column."""
        table = pa.table({"name": ["file1.pdf"], "content": ["text"]})
        reporter._current_tables = [table]
        result = reporter._lookup_doc_name_from_table("doc1")
        assert result is None

    def test_lookup_doc_name_from_previous_tables(self, reporter, sample_pyarrow_table):
        """Test lookup searches previous tables."""
        reporter._previous_tables = [sample_pyarrow_table]
        result = reporter._lookup_doc_name_from_table("doc2")
        assert result == "file2.pdf"

    def test_lookup_doc_name_handles_exceptions(self, reporter):
        """Test lookup handles exceptions gracefully."""
        mock_table = MagicMock()
        mock_table.column_names = ["id", "name"]
        mock_table.column.side_effect = Exception("Test error")

        reporter._current_tables = [mock_table]
        result = reporter._lookup_doc_name_from_table("doc1")
        assert result is None


class TestFlowSummary:
    """Tests for flow summary printing."""

    @patch("docpipe.utils.infrastructure.flow_execution_reporter.logger")
    def test_print_flow_summary_basic(self, mock_logger, reporter, sample_job_stats):
        """Test flow summary prints basic information."""
        dag_nodes = [
            {OperatorConstants.Columns.ID: "node1", "operator": "ingest"},
        ]

        reporter.print_flow_summary(job_stats=sample_job_stats, dag_nodes=dag_nodes)

        # sample_job_stats has failed_docs=1, so output routes to logger.error
        assert mock_logger.error.call_count > 0

    @patch("docpipe.utils.infrastructure.flow_execution_reporter.logger")
    def test_print_operator_summary_table_respects_dag_order(self, mock_logger, reporter):
        """Test operator summary table respects DAG execution order."""
        node_stats = {
            "node2": NodeStats(
                id="node2",
                name="second",
                node_status=ExecutionStatus.COMPLETED.value,
                time_taken=2,
                docs_completed=["doc1"],
                failed_docs=[],
                skipped_docs=[],
            ),
            "node1": NodeStats(
                id="node1",
                name="first",
                node_status=ExecutionStatus.COMPLETED.value,
                time_taken=1,
                docs_completed=["doc1"],
                failed_docs=[],
                skipped_docs=[],
            ),
        }
        dag_nodes = [
            {OperatorConstants.Columns.ID: "node1", "operator": "ingest"},
            {OperatorConstants.Columns.ID: "node2", "operator": "extract"},
        ]

        reporter._print_operator_summary_table(node_stats, dag_nodes)

        # No failures — all output routes to logger.info; check DAG order is preserved.
        # Rows are logged with %s-style args, so search all args of each call.
        calls = mock_logger.info.call_args_list
        first_idx = next(i for i, c in enumerate(calls) if "first" in str(c))
        second_idx = next(i for i, c in enumerate(calls) if "second" in str(c))
        assert first_idx < second_idx


class TestIntegration:
    """Integration tests for complete flow reporting."""

    def test_full_flow_reporting_workflow(self, reporter, sample_node_stats, sample_job_stats, sample_pyarrow_table):
        """Test complete flow reporting workflow."""
        # Start flow
        reporter.print_flow_header(flow_name="Test Flow", operator_count=2)
        assert reporter._flow_start_time is not None

        # First operator
        reporter.print_operator_start(step_name="ingest", operator_type="ingest_source")
        reporter.print_operator_summary(step_name="ingest", node_stats=sample_node_stats, tables=[sample_pyarrow_table])
        assert reporter._current_tables == [sample_pyarrow_table]

        # Second operator with new columns
        node_stats_2 = NodeStats(
            id="node2",
            name="extract",
            node_status=ExecutionStatus.COMPLETED.value,
            time_taken=10,
            col_names=["id", "name", "content", "extracted_text"],
            docs_completed=["doc1", "doc2"],
            failed_docs=[],
            skipped_docs=[],
        )
        table_2 = pa.table(
            {
                "id": ["doc1", "doc2"],
                "name": ["file1.pdf", "file2.pdf"],
                "content": ["content1", "content2"],
                "extracted_text": ["text1", "text2"],
            }
        )

        reporter.print_operator_start(step_name="extract", operator_type="extract_operator")
        reporter.print_operator_summary(step_name="extract", node_stats=node_stats_2, tables=[table_2])

        # Verify new columns were detected (check via the actual column comparison)
        prev_cols = reporter._extract_column_names([sample_pyarrow_table])
        curr_cols = reporter._extract_column_names([table_2])
        new_cols = curr_cols - prev_cols
        assert "extracted_text" in new_cols
        assert "id" not in new_cols

        # Flow summary
        sample_job_stats.node_stats = {"node1": sample_node_stats, "node2": node_stats_2}
        dag_nodes = [
            {OperatorConstants.Columns.ID: "node1", "operator": "ingest"},
            {OperatorConstants.Columns.ID: "node2", "operator": "extract"},
        ]
        reporter.print_flow_summary(job_stats=sample_job_stats, dag_nodes=dag_nodes)

        # Verify final state
        assert reporter._current_tables == [table_2]
        assert reporter._previous_tables == [table_2]


class TestColumnTrackingExceptionPaths:
    """Cover the except-Exception-pass paths in _get_new_columns and _get_removed_columns."""

    def test_get_new_columns_handles_exception_in_extract(self, reporter):
        """When _extract_column_names raises, _get_new_columns returns col_names unchanged."""
        from unittest.mock import patch

        import pyarrow as pa

        reporter._previous_tables = [pa.table({"id": ["x"]})]
        reporter._current_tables = [pa.table({"id": ["x"]})]

        col_names = ["id", "content"]
        with patch.object(reporter, "_extract_column_names", side_effect=RuntimeError("boom")):
            result = reporter._get_new_columns(col_names=col_names)

        # Falls back to returning all columns as new
        assert result == col_names

    def test_get_removed_columns_handles_exception_in_extract(self, reporter):
        """When _extract_column_names raises, _get_removed_columns returns empty list."""
        from unittest.mock import patch

        import pyarrow as pa

        reporter._previous_tables = [pa.table({"id": ["x"]})]
        reporter._current_tables = [pa.table({"id": ["x"]})]

        with patch.object(reporter, "_extract_column_names", side_effect=RuntimeError("boom")):
            result = reporter._get_removed_columns(col_names=["id", "content"])

        assert result == []


class TestFlowExecutionReporterStaticMethods:
    """Verify reporter helpers are static and callable without an instance."""

    STATIC_METHODS = (
        "print_operator_start",
        "_format_duration",
        "_log_column_change_header",
        "_extract_column_names",
        "_print_wrapped_columns",
        "_format_group_name",
        "_print_numeric_fields",
        "_print_nested_dict_field",
        "_print_other_fields",
        "_print_generic_list",
        "_extract_name_from_row",
    )

    def test_reporter_helpers_are_static(self):
        """Every converted reporter helper must be a true staticmethod."""
        import inspect

        from docpipe.utils.infrastructure.flow_execution_reporter import FlowExecutionReporter

        for method_name in self.STATIC_METHODS:
            assert isinstance(inspect.getattr_static(FlowExecutionReporter, method_name), staticmethod), (
                f"{method_name} is not a staticmethod"
            )

    def test_format_duration_class_call(self):
        """Duration formatting works when called directly on the class."""
        from docpipe.utils.infrastructure.flow_execution_reporter import FlowExecutionReporter

        assert FlowExecutionReporter._format_duration(None) == "< 1s"
        assert FlowExecutionReporter._format_duration(0.5) == "< 1s"
        assert FlowExecutionReporter._format_duration(2.5) == "2.50s"

    def test_extract_column_names_class_call(self):
        """Column extraction works when called directly on the class."""
        from docpipe.utils.infrastructure.flow_execution_reporter import FlowExecutionReporter

        tables = [pa.table({"id": ["x"], "content": ["y"]}), None]

        assert FlowExecutionReporter._extract_column_names(tables) == {"id", "content"}
