# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Unit tests for JobTrackerService.write_job_logs() — chronological node_stats sorting.

Covers:
- node_stats in the written JSON file are ordered by start_time (ascending)
- tie-breaking by end_time then name
- single node and empty node_stats cases
- JobStats domain model (model_dump path) is handled correctly
- plain dict job_stats is handled correctly
- missing/null start_time defaults to 0 without raising
- OSError is raised (and original exception chained) when the file cannot be written
"""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from docpipe.core.constants.constants import ExecutionStatus
from docpipe.core.job_management.adapters.services.job_tracker_service import JobTrackerService
from docpipe.core.job_management.domain.models.job_stats import JobStats
from docpipe.core.job_management.domain.models.node_stats import NodeStats

JOB_ID = "job-111"
JOB_RUN_ID = "run-222"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_store():
    return Mock()


@pytest.fixture
def mock_aggregator():
    return Mock()


@pytest.fixture
def service(mock_store, mock_aggregator):
    svc = JobTrackerService(job_stats_store=mock_store, node_stats_aggregator=mock_aggregator)
    # No snapshot: keeps write_job_logs off real snapshot storage, whose cached config leaks into later tests
    svc.get_flow_definition = Mock(return_value=None)
    return svc


def _node(node_id: str, name: str, start_time: int, end_time: int = 0) -> NodeStats:
    return NodeStats(id=node_id, name=name, start_time=start_time, end_time=end_time)


def _job_stats_model(node_stats: dict[str, NodeStats]) -> JobStats:
    return JobStats(
        job_id=JOB_ID,
        job_run_id=JOB_RUN_ID,
        status=ExecutionStatus.COMPLETED,
        node_stats=node_stats,
    )


def _job_stats_dict(node_stats_raw: dict) -> dict:
    """Return a plain dict (the non-JobStats branch in write_job_logs)."""
    return {
        "job_id": JOB_ID,
        "job_run_id": JOB_RUN_ID,
        "node_stats": node_stats_raw,
    }


# ---------------------------------------------------------------------------
# Tests — JobStats domain model (model_dump branch)
# ---------------------------------------------------------------------------


class TestWriteJobLogsFromJobStatsModel:
    """write_job_logs() with a JobStats domain model as input."""

    def test_node_stats_written_in_start_time_order(self, service, tmp_path):
        """Nodes are written to disk in ascending start_time order."""
        node_stats = {
            "node-c": _node("node-c", "NodeC", start_time=300),
            "node-a": _node("node-a", "NodeA", start_time=100),
            "node-b": _node("node-b", "NodeB", start_time=200),
        }
        job_stats = _job_stats_model(node_stats)
        log_path = str(tmp_path / "job_stats.json")

        service.write_job_logs(job_stats=job_stats, job_log_path=log_path)

        with Path(log_path).open() as f:
            written = json.load(f)
        assert list(written["node_stats"].keys()) == ["node-a", "node-b", "node-c"]

    def test_tiebreak_by_end_time(self, service, tmp_path):
        """When start_times are equal, nodes are ordered by end_time."""
        node_stats = {
            "node-b": _node("node-b", "NodeB", start_time=100, end_time=300),
            "node-a": _node("node-a", "NodeA", start_time=100, end_time=200),
        }
        job_stats = _job_stats_model(node_stats)
        log_path = str(tmp_path / "job_stats.json")

        service.write_job_logs(job_stats=job_stats, job_log_path=log_path)

        with Path(log_path).open() as f:
            written = json.load(f)
        assert list(written["node_stats"].keys()) == ["node-a", "node-b"]

    def test_tiebreak_by_name(self, service, tmp_path):
        """When start_time and end_time are equal, nodes are sorted alphabetically by name."""
        node_stats = {
            "node-z": _node("node-z", "Zebra", start_time=100, end_time=100),
            "node-a": _node("node-a", "Apple", start_time=100, end_time=100),
        }
        job_stats = _job_stats_model(node_stats)
        log_path = str(tmp_path / "job_stats.json")

        service.write_job_logs(job_stats=job_stats, job_log_path=log_path)

        with Path(log_path).open() as f:
            written = json.load(f)
        assert list(written["node_stats"].keys()) == ["node-a", "node-z"]

    def test_single_node_written_unchanged(self, service, tmp_path):
        """A single node is written without error and appears in the output."""
        node_stats = {"node-x": _node("node-x", "Only", start_time=500)}
        job_stats = _job_stats_model(node_stats)
        log_path = str(tmp_path / "job_stats.json")

        service.write_job_logs(job_stats=job_stats, job_log_path=log_path)

        with Path(log_path).open() as f:
            written = json.load(f)
        assert list(written["node_stats"].keys()) == ["node-x"]

    def test_empty_node_stats_written_as_empty_dict(self, service, tmp_path):
        """Empty node_stats is written as an empty JSON object."""
        job_stats = _job_stats_model({})
        log_path = str(tmp_path / "job_stats.json")

        service.write_job_logs(job_stats=job_stats, job_log_path=log_path)

        with Path(log_path).open() as f:
            written = json.load(f)
        assert written["node_stats"] == {}

    def test_file_is_valid_json(self, service, tmp_path):
        """Written file must be valid, parseable JSON."""
        node_stats = {"node-a": _node("node-a", "NodeA", start_time=100)}
        job_stats = _job_stats_model(node_stats)
        log_path = str(tmp_path / "stats.json")

        service.write_job_logs(job_stats=job_stats, job_log_path=log_path)

        with Path(log_path).open() as f:
            content = f.read()
        # Must not raise
        parsed = json.loads(content)
        assert parsed["job_id"] == JOB_ID

    def test_nested_directories_created(self, service, tmp_path):
        """write_job_logs() creates missing parent directories."""
        log_path = str(tmp_path / "a" / "b" / "c" / "job_stats.json")

        service.write_job_logs(job_stats=_job_stats_model({}), job_log_path=log_path)

        assert Path(log_path).exists()


# ---------------------------------------------------------------------------
# Tests — plain dict input (non-JobStats branch)
# ---------------------------------------------------------------------------


class TestWriteJobLogsFromDict:
    """write_job_logs() with a plain dict as input."""

    def test_dict_node_stats_sorted_by_start_time(self, service, tmp_path):
        """Plain-dict node_stats are sorted by start_time before writing."""
        raw_node_stats = {
            "node-c": {"name": "NodeC", "start_time": 300, "end_time": 0},
            "node-a": {"name": "NodeA", "start_time": 100, "end_time": 0},
            "node-b": {"name": "NodeB", "start_time": 200, "end_time": 0},
        }
        job_stats = _job_stats_dict(raw_node_stats)
        log_path = str(tmp_path / "job_stats.json")

        service.write_job_logs(job_stats=job_stats, job_log_path=log_path)

        with Path(log_path).open() as f:
            written = json.load(f)
        assert list(written["node_stats"].keys()) == ["node-a", "node-b", "node-c"]

    def test_dict_without_node_stats_key_written_as_is(self, service, tmp_path):
        """A dict without a 'node_stats' key is written without modification."""
        job_stats = {"job_id": JOB_ID, "status": "completed"}
        log_path = str(tmp_path / "job_stats.json")

        service.write_job_logs(job_stats=job_stats, job_log_path=log_path)

        with Path(log_path).open() as f:
            written = json.load(f)
        assert written["job_id"] == JOB_ID
        assert "node_stats" not in written

    def test_missing_start_time_defaults_to_zero(self, service, tmp_path):
        """Nodes missing start_time are treated as pending (0) and placed after executed nodes."""
        raw_node_stats = {
            "node-b": {"name": "NodeB"},  # no start_time key (pending)
            "node-a": {"name": "NodeA", "start_time": 100},  # executed
        }
        job_stats = _job_stats_dict(raw_node_stats)
        log_path = str(tmp_path / "job_stats.json")

        # Must not raise
        service.write_job_logs(job_stats=job_stats, job_log_path=log_path)

        with Path(log_path).open() as f:
            written = json.load(f)
        # node-a (executed, start_time=100) comes before node-b (pending, start_time=0)
        keys = list(written["node_stats"].keys())
        assert keys.index("node-a") < keys.index("node-b")


# ---------------------------------------------------------------------------
# Tests — error handling
# ---------------------------------------------------------------------------


class TestWriteJobLogsErrorHandling:
    """write_job_logs() raises OSError when the file cannot be written."""

    def test_raises_os_error_on_write_failure(self, service, tmp_path):
        """An IOError during Path.open() is re-raised as OSError."""
        log_path = str(tmp_path / "job_stats.json")
        job_stats = _job_stats_model({})

        with patch("pathlib.Path.open", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="Failed to write job logs"):
                service.write_job_logs(job_stats=job_stats, job_log_path=log_path)

    def test_original_exception_is_chained(self, service, tmp_path):
        """The original IOError is chained as the __cause__ of the raised OSError."""
        log_path = str(tmp_path / "job_stats.json")
        job_stats = _job_stats_model({})
        original = OSError("disk full")

        with patch("pathlib.Path.open", side_effect=original):
            with pytest.raises(OSError, match="Failed to write job logs") as exc_info:
                service.write_job_logs(job_stats=job_stats, job_log_path=log_path)

        assert exc_info.value.__cause__ is original
