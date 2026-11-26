# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for log retrieval and node-stats formatting in docpipe.utils.operators.logging."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from docpipe.core.constants.constants import ExecutionStatus, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.job_management.domain.models.node_stats import NodeStats
from docpipe.utils.operators import logging as op_logging
from docpipe.utils.operators.logging import (
    format_node_stats,
    format_operator_logs,
    get_log_and_job_file_path,
    retrieve_operator_logs,
)

SEPARATOR = ">>> ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"


@pytest.fixture
def data_root(tmp_path):
    """Point the logging module's data path at a temporary directory."""
    with patch.object(op_logging, "get_data_path", return_value=str(tmp_path)):
        yield tmp_path


def _paths(job_id: str = "job", run_id: str = "run") -> tuple[Path, Path, Path, Path]:
    """Return (log, job_stats, nodes_metadata, aggregated) paths, creating the log directory."""
    log, stats, meta, agg = (Path(p) for p in get_log_and_job_file_path(job_id=job_id, jobrun_id=run_id))
    log.parent.mkdir(parents=True, exist_ok=True)
    return log, stats, meta, agg


class TestRetrieveOperatorLogs:
    """Tests for retrieve_operator_logs file-format fallbacks."""

    def test_returns_aggregated_content_when_present(self, data_root):
        """A non-empty aggregated JSON file is returned as-is, ignoring the legacy log."""
        log, _, _, agg = _paths()
        aggregated = {"node_sequence": ["n1"], "n1": "aggregated log"}
        agg.write_text(json.dumps(aggregated), encoding="utf-8")
        log.write_text(f"{SEPARATOR}\nNode: legacy\nold line\n", encoding="utf-8")

        assert retrieve_operator_logs(job_id="job", jobrun_id="run") == aggregated

    def test_empty_aggregated_file_falls_back_to_sequential_log(self, data_root):
        """An empty aggregated JSON object falls back to parsing the legacy sequential log."""
        log, stats, meta, agg = _paths()
        agg.write_text("{}", encoding="utf-8")
        log.write_text(
            f"{SEPARATOR}\nNode: n1\nline one\nline two\n{SEPARATOR}\nNode: n2\nother\n",
            encoding="utf-8",
        )
        stats.write_text(json.dumps({"status": "completed"}), encoding="utf-8")
        meta.write_text(json.dumps({"n1": {"operator": "op"}}), encoding="utf-8")

        result = retrieve_operator_logs(job_id="job", jobrun_id="run")

        assert result["node_sequence"] == ["n1", "n2"]
        assert result["n1"] == "line one\n line two"
        assert result["n2"] == "other"
        assert result["job_stats"] == {"status": "completed"}
        assert result["nodes_metadata"] == {"n1": {"operator": "op"}}

    def test_sequential_log_without_aggregated_file(self, data_root):
        """Without an aggregated file the legacy log is parsed; missing side files are skipped."""
        log, _, _, _ = _paths()
        log.write_text(f"{SEPARATOR}\nNode: only\nmsg\n", encoding="utf-8")

        result = retrieve_operator_logs(job_id="job", jobrun_id="run")

        assert result == {"node_sequence": ["only"], "only": "msg"}


class TestGetLogsDictWithEmptyLogs:
    """Tests for get_logs with a Cloud/MCSP payload whose logs are empty."""

    def test_empty_logs_keep_job_stats_only(self):
        """An empty 'logs' string yields no node entries but still carries job stats."""
        result = op_logging.get_logs(content={"logs": "", "jobs": {"status": "failed"}})
        assert result == {"node_sequence": [], "job_stats": {"status": "failed"}}


class TestFormatNodeStats:
    """Tests for format_node_stats branches not covered elsewhere."""

    def test_skips_nodes_missing_from_stats_and_keeps_order(self):
        """Nodes absent from node_stats are skipped; output follows node_sequence order."""
        node_stats = {
            "b": {OperatorConstants.Columns.NAME: "B"},
            "a": {OperatorConstants.Columns.NAME: "A"},
        }
        parsed = json.loads(format_node_stats(node_stats=node_stats, node_sequence=["a", "missing", "b"]))
        assert [next(iter(entry)) for entry in parsed] == ["A", "B"]

    def test_node_stats_model_is_dumped_and_formatted(self):
        """NodeStats models are dumped, timestamps formatted and doc lists replaced by counts."""
        stats = NodeStats(
            id="n1",
            name="Node One",
            start_time=1609459200,
            end_time=1609459260,
            total_docs=["d1", "d2", "d3"],
            failed_docs=["d3"],
            skipped_docs=[],
            docs_completed=["d1", "d2"],
        )
        parsed = json.loads(format_node_stats(node_stats={"n1": stats}, node_sequence=["n1"]))
        info = parsed[0]["Node One"]

        assert info[Metrics.External.START_TIME] == "2021-01-01 00:00:00"
        assert info[Metrics.External.END_TIME] == "2021-01-01 00:01:00"
        assert info[Metrics.External.TOTAL_DOCS] == 3
        assert info["failed_docs_count"] == 1
        assert info["skipped_docs_count"] == 0
        assert info["docs_completed_count"] == 2
        assert "total_docs" not in info
        # The original model must not be mutated by formatting.
        assert stats.total_docs == ["d1", "d2", "d3"]

    def test_document_level_errors_are_extracted_and_metadata_removed(self):
        """Failed/skipped doc details in nested node metadata become document_level_errors."""
        meta_key = OperatorConstants.Metadata.NODE_METADATA
        node_stats = {
            "n1": {
                OperatorConstants.Columns.NAME: "N1",
                meta_key: {
                    meta_key: {
                        Metrics.External.FAILED_DOCS: [{"doc": "d1", "error": "boom"}],
                        Metrics.External.SKIPPED_DOCS: [{"doc": "d2", "reason": "dup"}],
                    }
                },
                "document_level_errors": [{"doc": "d0", "error": "earlier"}],
            }
        }
        parsed = json.loads(format_node_stats(node_stats=node_stats, node_sequence=["n1"]))
        info = parsed[0]["N1"]

        assert info["document_level_errors"] == [
            {"doc": "d0", "error": "earlier"},
            {"doc": "d1", "error": "boom"},
            {"doc": "d2", "reason": "dup"},
        ]
        assert meta_key not in info


class TestFormatOperatorLogs:
    """Tests for node-sequence resolution in format_operator_logs."""

    @staticmethod
    def _job_stats(**overrides):
        """Build a minimal job_stats dict accepted by format_operator_logs."""
        stats = {"status": ExecutionStatus.COMPLETED, "duration": 1.5, "message": "ok"}
        stats.update(overrides)
        return stats

    def test_sequence_is_looked_up_from_job_run_id(self):
        """Without node_sequence, the sequence is retrieved via the job run id."""
        job_stats = self._job_stats(job_run_id="run-1", node_stats={"n1": {OperatorConstants.Columns.NAME: "N1"}})
        with patch.object(op_logging, "retrieve_operators_sequence", return_value=["n1"]) as mock_seq:
            result = format_operator_logs(job_id="job-1", job_stats=job_stats)

        mock_seq.assert_called_once_with(job_id="job-1", job_run_id="run-1")
        assert '"N1"' in result
        assert f"The flow execution is {ExecutionStatus.COMPLETED.value}." in result

    def test_without_job_run_id_sequence_is_empty(self):
        """Without node_sequence or job run id no lookup happens and no nodes are listed."""
        job_stats = self._job_stats(node_stats={"n1": {OperatorConstants.Columns.NAME: "N1"}})
        with patch.object(op_logging, "retrieve_operators_sequence") as mock_seq:
            result = format_operator_logs(job_id="job-1", job_stats=job_stats)

        mock_seq.assert_not_called()
        assert '"N1"' not in result
        assert "Duration        : 1.50 seconds" in result
