# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for the double-checked singleton creation in DuckDBConnectionManager."""

import pytest

from docpipe.utils.duckdb.connection_manager import DuckDBConnectionManager


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the singleton before and after each test for isolation."""
    DuckDBConnectionManager.reset_instance()
    yield
    DuckDBConnectionManager.reset_instance()


class TestSingletonCreation:
    """Tests for DuckDBConnectionManager.__new__."""

    def test_instance_created_while_waiting_for_lock_is_reused(self, monkeypatch):
        """If another thread creates the instance while we wait for the lock, that instance is returned."""
        other = object.__new__(DuckDBConnectionManager)
        real_lock = DuckDBConnectionManager._lock

        class _RacingLock:
            """Lock stand-in that simulates another thread winning the race on acquire."""

            def __enter__(self):
                real_lock.acquire()
                DuckDBConnectionManager._instance = other
                return self

            def __exit__(self, *exc):
                real_lock.release()
                return False

        monkeypatch.setattr(DuckDBConnectionManager, "_lock", _RacingLock())

        try:
            assert DuckDBConnectionManager.__new__(DuckDBConnectionManager) is other
        finally:
            # 'other' was never initialised, so drop it before reset_instance() calls close_all().
            DuckDBConnectionManager._instance = None

    def test_repeated_construction_returns_same_instance(self):
        """Constructing the manager twice yields the same, initialised-once object."""
        first = DuckDBConnectionManager()
        connections = first._connections
        second = DuckDBConnectionManager()

        assert second is first
        assert second._connections is connections
