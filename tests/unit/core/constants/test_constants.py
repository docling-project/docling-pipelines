"""Regression tests for default DuckDB paths."""

import runpy
from pathlib import Path

import pytest

from docpipe.core.constants import constants


@pytest.mark.parametrize("data_root", [None, "relative-data", "absolute"])
def test_default_database_paths(*, monkeypatch, tmp_path, data_root):
    """Resolve all defaults from the data root without creating directories."""
    working_dir = tmp_path / "working"
    working_dir.mkdir()
    monkeypatch.chdir(working_dir)
    if data_root is None:
        monkeypatch.delenv("DOCPIPE_DATA_PATH", raising=False)
        expected_root = constants._find_project_root() / "data"
    else:
        configured_root = str(tmp_path / data_root) if data_root.startswith("absolute") else data_root
        monkeypatch.setenv("DOCPIPE_DATA_PATH", configured_root)
        expected_root = Path(configured_root).resolve()

    root_existed = expected_root.exists()

    # Execute in an isolated namespace: constants are evaluated at import time.
    loaded_constants = runpy.run_path(constants.__file__)["DocpipeConstants"]

    assert loaded_constants.DOCUMENT_SET_DEFAULT_DB_PATH == str(expected_root / "duckdb" / "document_sets.duckdb")
    assert loaded_constants.DOCUMENT_LIBRARY_DEFAULT_DB_PATH == loaded_constants.DOCUMENT_SET_DEFAULT_DB_PATH
    assert loaded_constants.JOB_STATS_DEFAULT_DB_PATH == str(expected_root / "duckdb" / "job_stats.duckdb")
    assert expected_root.exists() == root_existed
