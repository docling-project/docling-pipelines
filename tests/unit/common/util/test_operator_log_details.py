"""Unit tests for operator_log_details module."""

import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from docpipe.core.constants.constants import ExecutionStatus, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.utils.operators.logging import (
    _count_and_remove_lists,
    _extract_document_level_errors,
    _handle_dict_with_logs_key,
    _handle_string_logs,
    _operator_log_split,
    _parse_sequential_log_content,
    epoch_to_datetime,
    format_node_stats,
    format_operator_logs,
    get_log_and_job_file_path,
    get_logs,
    read_json_if_exists,
    retrieve_node_specific_operator_logs,
    retrieve_operator_logs,
    retrieve_operators_sequence,
)


class TestEpochToDatetime:
    """Test epoch_to_datetime function."""

    def test_epoch_to_datetime_valid(self):
        """Test converting valid epoch time."""
        epoch = 1609459200  # 2021-01-01 00:00:00 UTC
        result = epoch_to_datetime(epoch_time=epoch)
        assert isinstance(result, datetime)
        assert result.year == 2021

    def test_epoch_to_datetime_none(self):
        """Test with None epoch time."""
        result = epoch_to_datetime(epoch_time=None)
        assert result == ""

    def test_epoch_to_datetime_zero(self):
        """Test with zero epoch time."""
        result = epoch_to_datetime(epoch_time=0)
        assert result == ""


class TestOperatorLogSplit:
    """Test _operator_log_split function."""

    def test_operator_log_split_valid(self):
        """Test splitting valid operator log."""
        value = "NodeID: node_123\nLog line 1\nLog line 2"
        operator_logs_combined: dict[str, object] = {"node_sequence": []}
        result = _operator_log_split(value=value, operator_logs_combined=operator_logs_combined)

        assert "node_123" in result["node_sequence"]
        assert "node_123" in result
        assert "Log line 1" in result["node_123"]
        assert "Log line 2" in result["node_123"]

    def test_operator_log_split_no_colon(self):
        """Test with log value without colon."""
        value = "No colon here"
        operator_logs_combined: dict[str, object] = {"node_sequence": []}
        result = _operator_log_split(value=value, operator_logs_combined=operator_logs_combined)

        assert len(result["node_sequence"]) == 0

    def test_operator_log_split_empty_lines(self):
        """Test with empty lines in log."""
        value = "NodeID: node_456\n\nLog line\n\n"
        operator_logs_combined: dict[str, object] = {"node_sequence": []}
        result = _operator_log_split(value=value, operator_logs_combined=operator_logs_combined)

        assert "node_456" in result["node_sequence"]
        assert "Log line" in result["node_456"]


class TestGetLogAndJobFilePath:
    """Test get_log_and_job_file_path function."""

    @patch("docpipe.utils.infrastructure.filesystem.get_data_path")
    def test_get_log_and_job_file_path(self, mock_data_path):
        """Test getting log and job file paths."""
        mock_data_path.return_value = "/test/warehouse"

        log_path, job_path, _metadata_path, agg_path = get_log_and_job_file_path(job_id="job_123", jobrun_id="run_456")

        assert "job_123" in log_path
        assert "run_456" in log_path
        assert "flow_execute.log" in log_path
        assert "job_stats.json" in job_path
        assert "flow_execute_aggregated.json" in agg_path


class TestReadJsonIfExists:
    """Test read_json_if_exists function."""

    def test_read_json_if_exists_valid_file(self):
        """Test reading existing JSON file."""
        test_data = {"key": "value", "number": 123}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(test_data, f)
            temp_path = f.name

        try:
            result = read_json_if_exists(path=temp_path)
            assert result == test_data
        finally:
            Path(temp_path).unlink()

    def test_read_json_if_exists_nonexistent(self):
        """Test with nonexistent file."""
        result = read_json_if_exists(path="/nonexistent/path.json")
        assert result is None

    def test_read_json_if_exists_none_path(self):
        """Test with None path."""
        result = read_json_if_exists(path=None)
        assert result is None


class TestParseSequentialLogContent:
    """Test _parse_sequential_log_content function."""

    def test_parse_sequential_log_content(self):
        """Test parsing sequential log content."""
        log_content = (
            ">>> ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n"
            "NodeID: node_1\nLog for node 1\n"
            ">>> ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n"
            "NodeID: node_2\nLog for node 2"
        )
        operator_logs_combined: dict[str, object] = {"node_sequence": []}
        result = _parse_sequential_log_content(log_content, operator_logs_combined)

        assert "node_1" in result["node_sequence"]
        assert "node_2" in result["node_sequence"]
        assert "node_1" in result
        assert "node_2" in result


class TestHandleDictWithLogsKey:
    """Test _handle_dict_with_logs_key function."""

    def test_handle_dict_with_logs_key(self):
        """Test handling dict with logs key."""
        content = {
            "logs": ">>> ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\nNodeID: node_1\nLog content",
            "jobs": {"job_id": "123"},
        }
        operator_logs_combined: dict[str, object] = {"node_sequence": []}
        result = _handle_dict_with_logs_key(content, operator_logs_combined)

        assert "job_stats" in result
        assert result["job_stats"] == {"job_id": "123"}
        assert "node_1" in result["node_sequence"]

    def test_handle_dict_with_logs_key_no_jobs(self):
        """Test with no jobs key."""
        content = {"logs": ">>> ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\nNodeID: node_1\nLog"}
        operator_logs_combined: dict[str, object] = {"node_sequence": []}
        result = _handle_dict_with_logs_key(content, operator_logs_combined)

        assert "job_stats" not in result
        assert "node_1" in result["node_sequence"]


class TestHandleStringLogs:
    """Test _handle_string_logs function."""

    def test_handle_string_logs_basic(self):
        """Test handling string logs."""
        content = ">>> ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\nNodeID: node_1\nLog content"
        operator_logs_combined: dict[str, object] = {"node_sequence": []}
        result = _handle_string_logs(content, operator_logs_combined, None, None)

        assert "node_1" in result["node_sequence"]
        assert "node_1" in result

    @patch("docpipe.utils.operators.logging.read_json_if_exists")
    def test_handle_string_logs_with_job_stats(self, mock_read_json):
        """Test with job stats file."""
        mock_read_json.return_value = {"status": "completed"}
        content = ">>> ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\nNodeID: node_1\nLog"
        operator_logs_combined: dict[str, object] = {"node_sequence": []}
        result = _handle_string_logs(content, operator_logs_combined, "/path/to/job_stats.json", None)

        assert "job_stats" in result
        assert result["job_stats"]["status"] == "completed"


class TestGetLogs:
    """Test get_logs function."""

    def test_get_logs_dict_with_logs_key(self):
        """Test with dict containing logs key."""
        content = {
            "logs": ">>> ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\nNodeID: node_1\nLog",
            "jobs": {"job_id": "123"},
        }

        result = get_logs(content=content)

        assert "job_stats" in result
        assert "node_1" in result["node_sequence"]

    def test_get_logs_dict_without_logs_key(self):
        """Test with dict without logs key."""
        content = {"node_1": "Log for node 1", "node_2": "Log for node 2"}

        result = get_logs(content=content)

        assert "node_1" in result
        assert "node_2" in result
        assert set(result["node_sequence"]) == {"node_1", "node_2"}

    def test_get_logs_string_content(self):
        """Test with string content."""
        content = ">>> ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\nNodeID: node_1\nLog content"

        result = get_logs(content=content)

        assert "node_1" in result["node_sequence"]
        assert "node_1" in result

    def test_get_logs_empty_content(self):
        """Test with empty content."""
        result = get_logs(content="")

        assert result == {"node_sequence": []}

    def test_get_logs_none_content(self):
        """Test with None content."""
        result = get_logs(content=None)

        assert result == {"node_sequence": []}


class TestRetrieveOperatorLogs:
    """Test retrieve_operator_logs function."""

    def test_no_log_files_returns_empty_structure(self):
        """A job run with no log file at all returns the empty structure, not UnboundLocalError (#673)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("docpipe.utils.operators.logging.get_data_path", return_value=tmpdir):
                result = retrieve_operator_logs(job_id="job", jobrun_id="run")

        assert result == {"node_sequence": []}

    def test_no_log_files_same_as_empty_log_file(self):
        """No log file and an empty flow_execute.log give the same result (#673)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("docpipe.utils.operators.logging.get_data_path", return_value=tmpdir):
                missing = retrieve_operator_logs(job_id="job", jobrun_id="run")
                log_path, *_ = get_log_and_job_file_path(job_id="job", jobrun_id="run")
                Path(log_path).parent.mkdir(parents=True)
                Path(log_path).write_text("")
                empty = retrieve_operator_logs(job_id="job", jobrun_id="run")

        assert missing == empty

    def test_missing_log_file_is_logged_at_debug(self):
        """A missing log file leaves a debug hint; an empty log file does not (#673)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("docpipe.utils.operators.logging.get_data_path", return_value=tmpdir),
                patch("docpipe.utils.operators.logging.logger") as mock_logger,
            ):
                retrieve_operator_logs(job_id="job", jobrun_id="run")
                mock_logger.debug.assert_called_once_with("No log file found for job_id=%s jobrun_id=%s", "job", "run")

                mock_logger.reset_mock()
                log_path, *_ = get_log_and_job_file_path(job_id="job", jobrun_id="run")
                Path(log_path).parent.mkdir(parents=True)
                Path(log_path).write_text("")
                retrieve_operator_logs(job_id="job", jobrun_id="run")
                mock_logger.debug.assert_not_called()


class TestRetrieveNodeSpecificOperatorLogs:
    """Test retrieve_node_specific_operator_logs function."""

    @patch("docpipe.utils.operators.logging.retrieve_operator_logs")
    def test_retrieve_node_specific_operator_logs(self, mock_retrieve):
        """Test retrieving node-specific logs."""
        mock_retrieve.return_value = {
            "node_1": "Log for node 1",
            "node_2": "Log for node 2",
        }

        result = retrieve_node_specific_operator_logs(job_id="job_123", jobrun_id="run_456", node_id="node_1")

        assert result == "Log for node 1"


class TestRetrieveOperatorsSequence:
    """Test retrieve_operators_sequence function."""

    @patch("docpipe.utils.operators.logging.retrieve_operator_logs")
    def test_retrieve_operators_sequence(self, mock_retrieve):
        """Test retrieving operators sequence."""
        mock_retrieve.return_value = {"node_sequence": ["node_1", "node_2", "node_3"]}

        result = retrieve_operators_sequence(job_id="job_123", job_run_id="run_456")

        assert result == ["node_1", "node_2", "node_3"]

    @patch("docpipe.utils.operators.logging.retrieve_operator_logs")
    def test_retrieve_operators_sequence_empty(self, mock_retrieve):
        """Test with no sequence."""
        mock_retrieve.return_value = {}

        result = retrieve_operators_sequence(job_id="job_123", job_run_id="run_456")

        assert result == []


class TestExtractDocumentLevelErrors:
    """Test _extract_document_level_errors function."""

    def test_extract_document_level_errors_with_failed_docs(self):
        """Test extracting failed docs errors."""
        node_metadata = {
            OperatorConstants.Metadata.NODE_METADATA: {
                Metrics.External.FAILED_DOCS: ["doc1", "doc2"],
                Metrics.External.SKIPPED_DOCS: [],
            }
        }

        result = _extract_document_level_errors(node_metadata=node_metadata)

        assert len(result) == 2
        assert "doc1" in result
        assert "doc2" in result

    def test_extract_document_level_errors_with_skipped_docs(self):
        """Test extracting skipped docs errors."""
        node_metadata = {
            OperatorConstants.Metadata.NODE_METADATA: {
                Metrics.External.FAILED_DOCS: [],
                Metrics.External.SKIPPED_DOCS: ["doc3", "doc4"],
            }
        }

        result = _extract_document_level_errors(node_metadata=node_metadata)

        assert len(result) == 2
        assert "doc3" in result

    def test_extract_document_level_errors_empty(self):
        """Test with no errors."""
        node_metadata: dict[str, object] = {OperatorConstants.Metadata.NODE_METADATA: {}}
        result = _extract_document_level_errors(node_metadata=node_metadata)

        assert result == []


class TestCountAndRemoveLists:
    """Test _count_and_remove_lists function."""

    def test_count_and_remove_lists(self):
        """Test counting and removing lists."""
        node_info = {
            "total_docs": ["doc1", "doc2", "doc3"],
            "failed_docs": ["doc4"],
            "other_field": "value",
        }
        keys_to_count = ["total_docs", "failed_docs"]

        _count_and_remove_lists(node_info=node_info, keys_to_count=keys_to_count)

        assert "total_docs" not in node_info
        assert "failed_docs" not in node_info
        assert node_info["documents_in_scope"] == 3
        assert node_info["failed_docs_count"] == 1
        assert node_info["other_field"] == "value"

    def test_count_and_remove_lists_non_list_values(self):
        """Test with non-list values."""
        node_info = {"total_docs": "not a list", "other_field": 123}
        keys_to_count = ["total_docs"]

        _count_and_remove_lists(node_info=node_info, keys_to_count=keys_to_count)

        assert "total_docs" in node_info
        assert "documents_in_scope" not in node_info


class TestFormatNodeStats:
    """Test format_node_stats function."""

    def test_format_node_stats_basic(self):
        """Test basic node stats formatting."""
        node_stats = {
            "node_1": {
                OperatorConstants.Columns.NAME: "Node 1",
                Metrics.External.START_TIME: 1609459200,
                Metrics.External.END_TIME: 1609459260,
                "total_docs": ["doc1", "doc2"],
            }
        }
        node_sequence: list[str] = ["node_1"]

        result = format_node_stats(node_stats=node_stats, node_sequence=node_sequence)

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert "Node 1" in parsed[0]

    def test_format_node_stats_with_errors(self):
        """Test formatting with document errors."""
        node_stats = {
            "node_1": {
                OperatorConstants.Columns.NAME: "Node 1",
                OperatorConstants.Metadata.NODE_METADATA: {Metrics.External.FAILED_DOCS: ["doc1"]},
                "document_level_errors": {},
            }
        }
        node_sequence: list[str] = ["node_1"]

        result = format_node_stats(node_stats=node_stats, node_sequence=node_sequence)

        parsed = json.loads(result)
        node_data = parsed[0]["Node 1"]
        assert "document_level_errors" in node_data

    def test_format_node_stats_empty_sequence(self):
        """Test with empty sequence."""
        node_stats = {"node_1": {OperatorConstants.Columns.NAME: "Node 1"}}
        node_sequence: list[str] = []
        result = format_node_stats(node_stats=node_stats, node_sequence=node_sequence)

        parsed = json.loads(result)
        assert parsed == []


class TestFormatOperatorLogs:
    """Test format_operator_logs function."""

    @patch("docpipe.utils.operators.logging.retrieve_operators_sequence")
    def test_format_operator_logs_basic(self, mock_sequence):
        """Test basic operator logs formatting."""
        mock_sequence.return_value = ["node_1"]

        job_stats = {
            "status": ExecutionStatus.COMPLETED,
            "job_run_id": "run_123",
            "message": "Success",
            "end_time": 1609459260,
            "start_time": 1609459200,
            "duration": 60.0,
            "documents_in_scope_from_logs": 10,
            "processed_docs": 10,
            "failed_docs": 0,
            "skipped_docs": 0,
            "total_pages_processed": 20,
            "node_stats": {"node_1": {OperatorConstants.Columns.NAME: "Node 1"}},
        }

        result = format_operator_logs(job_id="job_123", job_stats=job_stats, node_sequence=["node_1"])

        assert "job_123" in result
        assert "run_123" in result
        assert "Success" in result
        assert "60.00 seconds" in result

    def test_format_operator_logs_with_string_status(self):
        """Test with string status instead of enum."""
        job_stats = {
            "status": "COMPLETED",
            "job_run_id": "run_123",
            "message": "Done",
            "end_time": 1609459260,
            "start_time": 1609459200,
            "duration": 60.0,
            "documents_in_scope_from_logs": 5,
            "processed_docs": 5,
            "failed_docs": 0,
            "skipped_docs": 0,
            "total_pages_processed": 10,
            "node_stats": {},
        }

        result = format_operator_logs(job_id="job_123", job_stats=job_stats, node_sequence=[])

        assert "COMPLETED" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
