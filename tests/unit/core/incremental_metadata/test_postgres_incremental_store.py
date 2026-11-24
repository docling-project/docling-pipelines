# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for PostgreSQL-based incremental metadata store."""

from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import psycopg2.errors
import pytest
import sqlalchemy.exc

from docpipe.core.incremental_metadata.domain.models import IncrementalMetadataRecord
from docpipe.exceptions import (
    FlowExecutionFailedException,
    JobStatsStoreInitializationException,
    LockTimeoutError,
)

_MODULE = "docpipe.core.incremental_metadata.adapters.stores.postgres.postgres_incremental_store"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pg_row(
    *,
    id: str,
    modified_time: int | None = 1000,
    job_run_id: str | None = "run-1",
    deleted: bool = False,
):
    """Build a minimal mock that looks like a row fetched from SATable."""
    row = Mock()
    row.id = id
    row.modified_time = modified_time
    row.job_run_id = job_run_id
    row.deleted = deleted
    return row


def _make_store(config: dict[str, Any] | None = None) -> "PostgresIncrementalMetadataStore":
    """Construct a store with all DB-related calls mocked out."""
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.begin.return_value.__enter__ = lambda *a: mock_conn
    mock_engine.begin.return_value.__exit__ = Mock(return_value=False)
    mock_engine.connect.return_value.__enter__ = lambda *a: mock_conn
    mock_engine.connect.return_value.__exit__ = Mock(return_value=False)

    with (
        patch(f"{_MODULE}.get_postgres_connection_string", return_value="postgresql+psycopg2://u:p@h/db"),
        patch(f"{_MODULE}.create_postgres_engine", return_value=mock_engine),
        patch(f"{_MODULE}.create_session_factory", return_value=MagicMock()),
    ):
        from docpipe.core.incremental_metadata.adapters.stores.postgres.postgres_incremental_store import (
            PostgresIncrementalMetadataStore,
        )

        return PostgresIncrementalMetadataStore(config=config)


@contextmanager
def _mock_connection(store, *, fetchall_rows=None, scalars_rows=None, execute_side_effect=None):
    """Replace the store's engine connect/begin with a preconfigured mock connection."""
    mock_conn = MagicMock()
    mock_execute_result = MagicMock()

    if execute_side_effect is not None:
        mock_conn.execute.side_effect = execute_side_effect
    else:
        mock_execute_result.fetchall.return_value = fetchall_rows or []
        mock_execute_result.scalars.return_value.all.return_value = scalars_rows or []
        mock_conn.execute.return_value = mock_execute_result

    @contextmanager
    def _begin():
        yield mock_conn

    @contextmanager
    def _connect():
        yield mock_conn

    store._engine.begin = _begin
    store._engine.connect = _connect
    try:
        yield mock_conn
    finally:
        pass


# ---------------------------------------------------------------------------
# Import under test
# ---------------------------------------------------------------------------

from docpipe.core.incremental_metadata.adapters.stores.postgres.postgres_incremental_store import (  # noqa: E402
    PostgresIncrementalMetadataStore,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store():
    return _make_store()


@pytest.fixture
def sample_records():
    return [
        IncrementalMetadataRecord(job_id="job-1", doc_id="doc-1", name="a.pdf", modified_time=1000, job_run_id="run-1"),
        IncrementalMetadataRecord(job_id="job-1", doc_id="doc-2", name="b.pdf", modified_time=2000, job_run_id="run-1"),
    ]


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestInit:
    def test_raises_when_no_connection_string(self):
        with patch(f"{_MODULE}.get_postgres_connection_string", return_value=None):
            with pytest.raises(JobStatsStoreInitializationException):
                PostgresIncrementalMetadataStore(config={})

    def test_raises_on_engine_creation_failure(self):
        with (
            patch(f"{_MODULE}.get_postgres_connection_string", return_value="postgresql+psycopg2://u:p@h/db"),
            patch(f"{_MODULE}.create_postgres_engine", side_effect=Exception("connection refused")),
        ):
            with pytest.raises(JobStatsStoreInitializationException, match="connection refused"):
                PostgresIncrementalMetadataStore(config={})

    def test_init_with_none_config(self):
        s = _make_store(config=None)
        assert s is not None
        assert s._lock_timeout_ms == 30000

    def test_init_with_default_lock_timeout(self):
        s = _make_store(config={})
        assert s._lock_timeout_ms == 30000

    def test_init_with_custom_lock_timeout(self):
        s = _make_store(config={"lock_timeout": 10.5})
        assert s._lock_timeout_ms == 10500

    def test_init_rejects_zero_lock_timeout(self):
        with pytest.raises(JobStatsStoreInitializationException, match="positive number"):
            _make_store(config={"lock_timeout": 0})

    def test_init_rejects_negative_lock_timeout(self):
        with pytest.raises(JobStatsStoreInitializationException, match="positive number"):
            _make_store(config={"lock_timeout": -5.0})

    def test_init_rejects_non_numeric_lock_timeout(self):
        with pytest.raises(JobStatsStoreInitializationException, match="positive number"):
            _make_store(config={"lock_timeout": "30s"})
        with pytest.raises(JobStatsStoreInitializationException, match="positive number"):
            _make_store(config={"lock_timeout": True})

    def test_init_with_nested_postgres_config(self):
        s = _make_store(config={"postgres": {"host": "pg-host"}})
        assert s is not None

    def test_init_with_custom_schema(self):
        s = _make_store(config={"schema": "custom_schema"})
        assert s is not None
        assert s.schema_name == "custom_schema"
        assert s._table.schema == "custom_schema"

    def test_init_schema_and_bootstrap_lock(self):
        """Bootstrap acquires advisory lock before creating schema and table."""
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = lambda *a: mock_conn
        mock_engine.begin.return_value.__exit__ = Mock(return_value=False)

        with (
            patch(f"{_MODULE}.get_postgres_connection_string", return_value="postgresql+psycopg2://u:p@h/db"),
            patch(f"{_MODULE}.create_postgres_engine", return_value=mock_engine),
            patch(f"{_MODULE}.create_session_factory", return_value=MagicMock()),
        ):
            s = PostgresIncrementalMetadataStore(config={"schema": "test_schema"})
            assert s._table.schema == "test_schema"
            # Verify lock statement and schema creation executed
            calls = mock_conn.execute.call_args_list
            assert len(calls) >= 2
            lock_call = str(calls[0][0][0])
            assert "pg_advisory_xact_lock" in lock_call

    def test_raises_wraps_init_exception_in_job_stats_exc(self):
        """Any unexpected exception during init is wrapped in JobStatsStoreInitializationException."""
        mock_engine = MagicMock()
        mock_engine.begin.side_effect = RuntimeError("boom")

        with (
            patch(f"{_MODULE}.get_postgres_connection_string", return_value="postgresql+psycopg2://u:p@h/db"),
            patch(f"{_MODULE}.create_postgres_engine", return_value=mock_engine),
            patch(f"{_MODULE}.create_session_factory", return_value=MagicMock()),
        ):
            with pytest.raises(JobStatsStoreInitializationException, match="boom"):
                PostgresIncrementalMetadataStore(config={})


# ---------------------------------------------------------------------------
# Schema Qualification
# ---------------------------------------------------------------------------


class TestSchemaQualification:
    def test_default_schema_table_name(self):
        store = _make_store()
        assert store.schema_name == "incremental_metadata"
        assert store._table.schema == "incremental_metadata"
        assert store._table.name == "inc_update_metadata"

    def test_custom_schema_table_name(self):
        store = _make_store(config={"schema": "my_custom_schema"})
        assert store.schema_name == "my_custom_schema"
        assert store._table.schema == "my_custom_schema"
        assert store._table.name == "inc_update_metadata"

    def test_compiled_sql_contains_schema(self):
        from sqlalchemy import select
        from sqlalchemy.dialects import postgresql

        store = _make_store(config={"schema": "custom_schema"})
        stmt = select(store._table.c.id).where(store._table.c.job_id == "job-1")
        compiled = str(stmt.compile(dialect=postgresql.dialect()))
        assert "custom_schema.inc_update_metadata" in compiled or '"custom_schema"."inc_update_metadata"' in compiled


# ---------------------------------------------------------------------------
# get_processed_docs (lock-free read)
# ---------------------------------------------------------------------------


class TestGetProcessedDocs:
    def test_returns_non_deleted_docs(self, *, store):
        rows = [
            _make_pg_row(id="doc-1", modified_time=1000, job_run_id="run-1"),
            _make_pg_row(id="doc-2", modified_time=2000, job_run_id="run-1"),
        ]
        with _mock_connection(store, fetchall_rows=rows):
            result = store.get_processed_docs(job_id="job-1")

        assert result == {
            "doc-1": {"modified_time": 1000, "job_run_id": "run-1"},
            "doc-2": {"modified_time": 2000, "job_run_id": "run-1"},
        }

    def test_returns_empty_when_no_rows(self, *, store):
        with _mock_connection(store, fetchall_rows=[]):
            result = store.get_processed_docs(job_id="job-1")

        assert result == {}

    def test_raises_flow_exception_on_db_error(self, *, store):
        with _mock_connection(store, execute_side_effect=Exception("db error")):
            with pytest.raises(FlowExecutionFailedException, match="job-1"):
                store.get_processed_docs(job_id="job-1")

    def test_includes_null_modified_time_in_result(self, *, store):
        rows = [_make_pg_row(id="doc-1", modified_time=None, job_run_id=None)]
        with _mock_connection(store, fetchall_rows=rows):
            result = store.get_processed_docs(job_id="job-1")

        assert result == {"doc-1": {"modified_time": None, "job_run_id": None}}


# ---------------------------------------------------------------------------
# upsert_records
# ---------------------------------------------------------------------------


class TestUpsertRecords:
    def test_empty_records_is_noop(self, *, store):
        with _mock_connection(store) as mock_conn:
            store.upsert_records(job_id="job-1", job_run_id="run-1", records=[])
            mock_conn.execute.assert_not_called()

    def test_upserts_records_with_lock_timeout_and_advisory_lock(self, *, store, sample_records):
        with _mock_connection(store) as mock_conn:
            store.upsert_records(job_id="job-1", job_run_id="run-1", records=sample_records)
            calls = mock_conn.execute.call_args_list
            assert len(calls) == 3
            # 1. lock_timeout set
            assert "set_config" in str(calls[0][0][0])
            assert calls[0][0][1] == {"val": "30000ms"}
            # 2. advisory xact lock acquired
            assert "pg_advisory_xact_lock" in str(calls[1][0][0])
            assert calls[1][0][1] == {"key": "incremental_metadata.inc_update_metadata:job-1"}
            # 3. ON CONFLICT insert
            assert "ON CONFLICT" in str(calls[2][0][0])

    def test_deduplicates_duplicate_doc_ids_in_batch(self, *, store):
        records = [
            IncrementalMetadataRecord(job_id="job-1", doc_id="doc-1", name="first.pdf", modified_time=100),
            IncrementalMetadataRecord(job_id="job-1", doc_id="doc-1", name="second.pdf", modified_time=200),
        ]
        with _mock_connection(store) as mock_conn:
            store.upsert_records(job_id="job-1", job_run_id="run-1", records=records)
            calls = mock_conn.execute.call_args_list
            assert len(calls) == 3
            executed_stmt = calls[2][0][0]
            assert "ON CONFLICT" in str(executed_stmt)

    def test_raises_flow_exception_on_db_error(self, *, store, sample_records):
        with _mock_connection(store, execute_side_effect=Exception("insert failed")):
            with pytest.raises(FlowExecutionFailedException, match="job-1"):
                store.upsert_records(job_id="job-1", job_run_id="run-1", records=sample_records)

    def test_maps_lock_not_available_to_lock_timeout_error(self, *, store, sample_records, mocker):
        """OperationalError with LockNotAvailable or pgcode 55P03 is mapped to LockTimeoutError."""
        mocker.patch("time.sleep")
        orig_err = psycopg2.errors.LockNotAvailable("canceling statement due to lock timeout")
        op_err = sqlalchemy.exc.OperationalError("statement", {}, orig_err)

        with _mock_connection(store, execute_side_effect=op_err):
            with pytest.raises(LockTimeoutError) as exc_info:
                store.upsert_records(job_id="job-1", job_run_id="run-1", records=sample_records)
            assert "job-1" in str(exc_info.value)

    def test_maps_custom_55p03_error_to_lock_timeout_error(self, *, store, sample_records, mocker):
        """OperationalError with pgcode 55P03 on generic exception is mapped to LockTimeoutError."""
        mocker.patch("time.sleep")
        orig_err = Exception("custom lock error")
        orig_err.pgcode = "55P03"  # type: ignore[attr-defined]
        op_err = sqlalchemy.exc.OperationalError("statement", {}, orig_err)

        with _mock_connection(store, execute_side_effect=op_err):
            with pytest.raises(LockTimeoutError) as exc_info:
                store.upsert_records(job_id="job-1", job_run_id="run-1", records=sample_records)
            assert "job-1" in str(exc_info.value)

    def test_retry_on_lock_timeout_exhaustion(self, *, store, sample_records, mocker):
        """upsert_records retries on LockTimeoutError until exhausted."""
        orig_err = psycopg2.errors.LockNotAvailable("lock timeout")
        op_err = sqlalchemy.exc.OperationalError("statement", {}, orig_err)

        mocker.patch("time.sleep")  # Fast retry
        with _mock_connection(store, execute_side_effect=op_err) as mock_conn:
            with pytest.raises(LockTimeoutError):
                store.upsert_records(job_id="job-1", job_run_id="run-1", records=sample_records)
            assert mock_conn.execute.call_count == 5


# ---------------------------------------------------------------------------
# get_soft_deleted_doc_ids (lock-free read)
# ---------------------------------------------------------------------------


class TestGetSoftDeletedDocIds:
    def test_returns_deleted_ids(self, *, store):
        with _mock_connection(store, scalars_rows=["doc-2", "doc-3"]):
            result = store.get_soft_deleted_doc_ids(job_id="job-1")

        assert result == {"doc-2", "doc-3"}

    def test_returns_empty_set_when_none(self, *, store):
        with _mock_connection(store, scalars_rows=[]):
            result = store.get_soft_deleted_doc_ids(job_id="job-1")

        assert result == set()

    def test_raises_flow_exception_on_db_error(self, *, store):
        with _mock_connection(store, execute_side_effect=Exception("query failed")):
            with pytest.raises(FlowExecutionFailedException, match="job-1"):
                store.get_soft_deleted_doc_ids(job_id="job-1")


# ---------------------------------------------------------------------------
# mark_missing_docs_as_deleted
# ---------------------------------------------------------------------------


class TestMarkMissingDocsAsDeleted:
    def test_marks_docs_not_in_list_using_single_update_returning(self, *, store):
        with _mock_connection(store, scalars_rows=["doc-2"]) as mock_conn:
            deleted = store.mark_missing_docs_as_deleted(job_id="job-1", doc_ids=["doc-1"])

        assert deleted == {"doc-2"}
        calls = mock_conn.execute.call_args_list
        assert len(calls) == 3
        # 1. lock_timeout
        assert "set_config" in str(calls[0][0][0])
        # 2. advisory lock
        assert "pg_advisory_xact_lock" in str(calls[1][0][0])
        # 3. UPDATE ... RETURNING id
        stmt = calls[2][0][0]
        params = calls[2][0][1]
        assert "UPDATE" in str(stmt)
        assert params == {"doc_ids": ["doc-1"]}

    def test_marks_all_docs_when_list_is_empty(self, *, store):
        with _mock_connection(store, scalars_rows=["doc-1", "doc-2"]) as mock_conn:
            deleted = store.mark_missing_docs_as_deleted(job_id="job-1", doc_ids=[])

        assert deleted == {"doc-1", "doc-2"}
        calls = mock_conn.execute.call_args_list
        assert len(calls) == 3
        params = calls[2][0][1]
        assert params == {}

    def test_returns_empty_when_no_rows_returned(self, *, store):
        with _mock_connection(store, scalars_rows=[]):
            deleted = store.mark_missing_docs_as_deleted(job_id="job-1", doc_ids=["doc-1", "doc-2"])

        assert deleted == set()

    def test_raises_flow_exception_on_db_error(self, *, store):
        with _mock_connection(store, execute_side_effect=Exception("db error")):
            with pytest.raises(FlowExecutionFailedException, match="job-1"):
                store.mark_missing_docs_as_deleted(job_id="job-1", doc_ids=["doc-1"])

    def test_raises_lock_timeout_error_on_lock_timeout(self, *, store):
        orig_err = psycopg2.errors.LockNotAvailable("lock timeout")
        op_err = sqlalchemy.exc.OperationalError("statement", {}, orig_err)

        with _mock_connection(store, execute_side_effect=op_err):
            with pytest.raises(LockTimeoutError, match="job-1"):
                store.mark_missing_docs_as_deleted(job_id="job-1", doc_ids=["doc-1"])


# ---------------------------------------------------------------------------
# delete_docs
# ---------------------------------------------------------------------------


class TestDeleteDocs:
    def test_empty_list_is_noop(self, *, store):
        with _mock_connection(store) as mock_conn:
            store.delete_docs(job_id="job-1", doc_ids=[])
            mock_conn.execute.assert_not_called()

    def test_executes_delete_with_locks(self, *, store):
        with _mock_connection(store) as mock_conn:
            store.delete_docs(job_id="job-1", doc_ids=["doc-1", "doc-2"])
            calls = mock_conn.execute.call_args_list
            assert len(calls) == 3
            assert "DELETE" in str(calls[2][0][0])
            assert calls[2][0][1] == {"doc_ids": ["doc-1", "doc-2"]}

    def test_raises_flow_exception_on_db_error(self, *, store):
        with _mock_connection(store, execute_side_effect=Exception("delete failed")):
            with pytest.raises(FlowExecutionFailedException, match="job-1"):
                store.delete_docs(job_id="job-1", doc_ids=["doc-1"])


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


class TestClear:
    def test_executes_delete_with_locks(self, *, store):
        with _mock_connection(store) as mock_conn:
            store.clear(job_id="job-1")
            calls = mock_conn.execute.call_args_list
            assert len(calls) == 3
            assert "DELETE" in str(calls[2][0][0])

    def test_raises_flow_exception_on_db_error(self, *, store):
        with _mock_connection(store, execute_side_effect=Exception("clear failed")):
            with pytest.raises(FlowExecutionFailedException, match="job-1"):
                store.clear(job_id="job-1")

    def test_clear_passes_correct_job_id(self, *, store):
        """Verify clear uses the right job_id in its delete statement and lock key."""
        with _mock_connection(store) as mock_conn:
            store.clear(job_id="specific-job-xyz")
            calls = mock_conn.execute.call_args_list
            assert len(calls) == 3
            assert calls[1][0][1] == {"key": "incremental_metadata.inc_update_metadata:specific-job-xyz"}


# ---------------------------------------------------------------------------
# unmark_soft_deleted_docs
# ---------------------------------------------------------------------------


class TestUnmarkSoftDeletedDocs:
    def test_unmarks_all_when_doc_ids_none(self, *, store):
        with _mock_connection(store) as mock_conn:
            mock_conn.execute.return_value.rowcount = 1
            store.unmark_soft_deleted_docs(job_id="job-1")
            calls = mock_conn.execute.call_args_list
            assert len(calls) == 3
            assert "UPDATE" in str(calls[2][0][0])

    def test_unmarks_specific_doc_ids(self, *, store):
        with _mock_connection(store) as mock_conn:
            mock_conn.execute.return_value.rowcount = 1
            store.unmark_soft_deleted_docs(job_id="job-1", doc_ids=["doc-1"])
            calls = mock_conn.execute.call_args_list
            assert len(calls) == 3
            assert calls[2][0][1] == {"doc_ids": ["doc-1"]}

    def test_raises_flow_exception_on_db_error(self, *, store):
        with _mock_connection(store, execute_side_effect=Exception("unmark failed")):
            with pytest.raises(FlowExecutionFailedException, match="job-1"):
                store.unmark_soft_deleted_docs(job_id="job-1")


# ---------------------------------------------------------------------------
# purge_soft_deleted_docs
# ---------------------------------------------------------------------------


class TestPurgeSoftDeletedDocs:
    def test_executes_delete_with_locks(self, *, store):
        with _mock_connection(store) as mock_conn:
            store.purge_soft_deleted_docs(job_id="job-1")
            calls = mock_conn.execute.call_args_list
            assert len(calls) == 3
            assert "DELETE" in str(calls[2][0][0])

    def test_raises_flow_exception_on_db_error(self, *, store):
        with _mock_connection(store, execute_side_effect=Exception("purge failed")):
            with pytest.raises(FlowExecutionFailedException, match="job-1"):
                store.purge_soft_deleted_docs(job_id="job-1")
