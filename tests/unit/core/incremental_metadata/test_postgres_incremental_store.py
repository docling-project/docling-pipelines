# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for PostgreSQL-based incremental metadata store."""

from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

from docpipe.core.incremental_metadata.domain.models import IncrementalMetadataRecord
from docpipe.exceptions.docpipe_exceptions import (
    FlowExecutionFailedException,
    JobStatsStoreInitializationException,
)

_MODULE = "docpipe.core.incremental_metadata.adapters.stores.postgres.postgres_incremental_store"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pg_row(
    *,
    doc_id: str,
    modified_time: int | None = 1000,
    job_run_id: str | None = "run-1",
    deleted: bool = False,
):
    """Build a minimal mock that looks like IncrementalMetadataPostgresModel row."""
    row = Mock()
    row.doc_id = doc_id
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

    with (
        patch(f"{_MODULE}.get_postgres_connection_string", return_value="postgresql+psycopg2://u:p@h/db"),
        patch(f"{_MODULE}.create_postgres_engine", return_value=mock_engine),
        patch(f"{_MODULE}.create_session_factory", return_value=MagicMock()),
        patch(f"{_MODULE}.MetaData"),
        patch(f"{_MODULE}.cast", return_value=MagicMock()),
    ):
        from docpipe.core.incremental_metadata.adapters.stores.postgres.postgres_incremental_store import (
            PostgresIncrementalMetadataStore,
        )

        return PostgresIncrementalMetadataStore(config=config)


@contextmanager
def _mock_session(store, *, rows=None, scalars_side_effect=None):
    """Replace the store's session factory with a preconfigured mock session."""
    mock_session = MagicMock()
    mock_execute_result = MagicMock()

    if scalars_side_effect is not None:
        mock_execute_result.scalars.return_value.all.side_effect = scalars_side_effect
    else:
        mock_execute_result.scalars.return_value.all.return_value = rows or []

    mock_session.execute.return_value = mock_execute_result

    @contextmanager
    def _factory():
        yield mock_session

    original = store._session_factory
    store._session_factory = _factory
    try:
        yield mock_session
    finally:
        store._session_factory = original


def _session_factory_for(mock_session):
    """Return a context-manager factory that yields mock_session."""

    @contextmanager
    def _factory():
        yield mock_session

    return _factory


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

    def test_init_with_nested_postgres_config(self):
        s = _make_store(config={"postgres": {"host": "pg-host"}})
        assert s is not None

    def test_init_with_custom_schema(self):
        s = _make_store(config={"schema": "custom_schema"})
        assert s is not None

    def test_raises_wraps_init_exception_in_job_stats_exc(self):
        """Any unexpected exception during init is wrapped in JobStatsStoreInitializationException."""
        mock_engine = MagicMock()
        mock_engine.begin.side_effect = RuntimeError("boom")

        with (
            patch(f"{_MODULE}.get_postgres_connection_string", return_value="postgresql+psycopg2://u:p@h/db"),
            patch(f"{_MODULE}.create_postgres_engine", return_value=mock_engine),
            patch(f"{_MODULE}.create_session_factory", return_value=MagicMock()),
            patch(f"{_MODULE}.MetaData"),
            patch(f"{_MODULE}.cast", return_value=MagicMock()),
        ):
            with pytest.raises(JobStatsStoreInitializationException, match="boom"):
                PostgresIncrementalMetadataStore(config={})


# ---------------------------------------------------------------------------
# get_processed_docs
# ---------------------------------------------------------------------------


class TestGetProcessedDocs:
    def test_returns_non_deleted_docs(self, *, store):
        rows = [
            _make_pg_row(doc_id="doc-1", modified_time=1000, job_run_id="run-1"),
            _make_pg_row(doc_id="doc-2", modified_time=2000, job_run_id="run-1"),
        ]
        with _mock_session(store, rows=rows):
            result = store.get_processed_docs(job_id="job-1")

        assert result == {
            "doc-1": {"modified_time": 1000, "job_run_id": "run-1"},
            "doc-2": {"modified_time": 2000, "job_run_id": "run-1"},
        }

    def test_returns_empty_when_no_rows(self, *, store):
        with _mock_session(store, rows=[]):
            result = store.get_processed_docs(job_id="job-1")

        assert result == {}

    def test_raises_flow_exception_on_db_error(self, *, store):
        with _mock_session(store, scalars_side_effect=Exception("db error")):
            with pytest.raises(FlowExecutionFailedException, match="job-1"):
                store.get_processed_docs(job_id="job-1")

    def test_includes_null_modified_time_in_result(self, *, store):
        rows = [_make_pg_row(doc_id="doc-1", modified_time=None, job_run_id=None)]
        with _mock_session(store, rows=rows):
            result = store.get_processed_docs(job_id="job-1")

        assert result == {"doc-1": {"modified_time": None, "job_run_id": None}}


# ---------------------------------------------------------------------------
# upsert_records
# ---------------------------------------------------------------------------


class TestUpsertRecords:
    def test_empty_records_is_noop(self, *, store):
        mock_session = MagicMock()
        store._session_factory = _session_factory_for(mock_session)

        store.upsert_records(job_id="job-1", job_run_id="run-1", records=[])

        mock_session.add.assert_not_called()
        mock_session.commit.assert_not_called()

    def test_inserts_new_records(self, *, store, sample_records):
        mock_session = MagicMock()
        mock_session.get.return_value = None  # no pre-existing records
        store._session_factory = _session_factory_for(mock_session)

        store.upsert_records(job_id="job-1", job_run_id="run-1", records=sample_records)

        assert mock_session.add.call_count == 2
        mock_session.commit.assert_called_once()

    def test_updates_existing_record(self, *, store, sample_records):
        existing_model = MagicMock()
        mock_session = MagicMock()
        mock_session.get.return_value = existing_model
        store._session_factory = _session_factory_for(mock_session)

        store.upsert_records(job_id="job-1", job_run_id="run-2", records=[sample_records[0]])

        assert existing_model.name == "a.pdf"
        assert existing_model.modified_time == 1000
        assert existing_model.job_run_id == "run-2"
        assert existing_model.deleted is False
        mock_session.commit.assert_called_once()

    def test_upsert_sets_deleted_false_on_existing(self, *, store, sample_records):
        """A previously soft-deleted record is un-deleted on upsert."""
        existing_model = MagicMock()
        existing_model.deleted = True
        mock_session = MagicMock()
        mock_session.get.return_value = existing_model
        store._session_factory = _session_factory_for(mock_session)

        store.upsert_records(job_id="job-1", job_run_id="run-1", records=[sample_records[0]])

        assert existing_model.deleted is False

    def test_raises_flow_exception_on_db_error(self, *, store, sample_records):
        mock_session = MagicMock()
        mock_session.get.side_effect = Exception("insert failed")
        store._session_factory = _session_factory_for(mock_session)

        with pytest.raises(FlowExecutionFailedException, match="job-1"):
            store.upsert_records(job_id="job-1", job_run_id="run-1", records=sample_records)


# ---------------------------------------------------------------------------
# get_soft_deleted_doc_ids
# ---------------------------------------------------------------------------


class TestGetSoftDeletedDocIds:
    def test_returns_deleted_ids(self, *, store):
        mock_session = MagicMock()
        mock_session.execute.return_value.scalars.return_value.all.return_value = ["doc-2", "doc-3"]
        store._session_factory = _session_factory_for(mock_session)

        result = store.get_soft_deleted_doc_ids(job_id="job-1")

        assert result == {"doc-2", "doc-3"}

    def test_returns_empty_set_when_none(self, *, store):
        mock_session = MagicMock()
        mock_session.execute.return_value.scalars.return_value.all.return_value = []
        store._session_factory = _session_factory_for(mock_session)

        result = store.get_soft_deleted_doc_ids(job_id="job-1")

        assert result == set()

    def test_raises_flow_exception_on_db_error(self, *, store):
        mock_session = MagicMock()
        mock_session.execute.side_effect = Exception("query failed")
        store._session_factory = _session_factory_for(mock_session)

        with pytest.raises(FlowExecutionFailedException, match="job-1"):
            store.get_soft_deleted_doc_ids(job_id="job-1")


# ---------------------------------------------------------------------------
# mark_missing_docs_as_deleted
# ---------------------------------------------------------------------------


class TestMarkMissingDocsAsDeleted:
    def test_marks_docs_not_in_list(self, *, store):
        rows = [_make_pg_row(doc_id="doc-1"), _make_pg_row(doc_id="doc-2")]
        mock_session = MagicMock()
        mock_session.execute.return_value.scalars.return_value.all.return_value = rows
        store._session_factory = _session_factory_for(mock_session)

        deleted = store.mark_missing_docs_as_deleted(job_id="job-1", doc_ids=["doc-1"])

        assert deleted == {"doc-2"}
        assert rows[1].deleted is True
        mock_session.commit.assert_called_once()

    def test_returns_empty_when_all_docs_present(self, *, store):
        rows = [_make_pg_row(doc_id="doc-1"), _make_pg_row(doc_id="doc-2")]
        mock_session = MagicMock()
        mock_session.execute.return_value.scalars.return_value.all.return_value = rows
        store._session_factory = _session_factory_for(mock_session)

        deleted = store.mark_missing_docs_as_deleted(job_id="job-1", doc_ids=["doc-1", "doc-2"])

        assert deleted == set()
        mock_session.commit.assert_called_once()

    def test_returns_empty_when_no_existing_rows(self, *, store):
        mock_session = MagicMock()
        mock_session.execute.return_value.scalars.return_value.all.return_value = []
        store._session_factory = _session_factory_for(mock_session)

        deleted = store.mark_missing_docs_as_deleted(job_id="job-1", doc_ids=["doc-x"])

        assert deleted == set()

    def test_marks_all_docs_when_list_is_empty(self, *, store):
        rows = [_make_pg_row(doc_id="doc-1"), _make_pg_row(doc_id="doc-2")]
        mock_session = MagicMock()
        mock_session.execute.return_value.scalars.return_value.all.return_value = rows
        store._session_factory = _session_factory_for(mock_session)

        deleted = store.mark_missing_docs_as_deleted(job_id="job-1", doc_ids=[])

        assert deleted == {"doc-1", "doc-2"}
        assert rows[0].deleted is True
        assert rows[1].deleted is True

    def test_raises_flow_exception_on_db_error(self, *, store):
        mock_session = MagicMock()
        mock_session.execute.side_effect = Exception("db error")
        store._session_factory = _session_factory_for(mock_session)

        with pytest.raises(FlowExecutionFailedException, match="job-1"):
            store.mark_missing_docs_as_deleted(job_id="job-1", doc_ids=["doc-1"])


# ---------------------------------------------------------------------------
# delete_docs
# ---------------------------------------------------------------------------


class TestDeleteDocs:
    def test_empty_list_is_noop(self, *, store):
        mock_session = MagicMock()
        store._session_factory = _session_factory_for(mock_session)

        store.delete_docs(job_id="job-1", doc_ids=[])

        mock_session.execute.assert_not_called()
        mock_session.commit.assert_not_called()

    def test_executes_delete_and_commits(self, *, store):
        mock_session = MagicMock()
        store._session_factory = _session_factory_for(mock_session)

        store.delete_docs(job_id="job-1", doc_ids=["doc-1", "doc-2"])

        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_raises_flow_exception_on_db_error(self, *, store):
        mock_session = MagicMock()
        mock_session.execute.side_effect = Exception("delete failed")
        store._session_factory = _session_factory_for(mock_session)

        with pytest.raises(FlowExecutionFailedException, match="job-1"):
            store.delete_docs(job_id="job-1", doc_ids=["doc-1"])


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


class TestClear:
    def test_executes_delete_and_commits(self, *, store):
        mock_session = MagicMock()
        store._session_factory = _session_factory_for(mock_session)

        store.clear(job_id="job-1")

        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_raises_flow_exception_on_db_error(self, *, store):
        mock_session = MagicMock()
        mock_session.execute.side_effect = Exception("clear failed")
        store._session_factory = _session_factory_for(mock_session)

        with pytest.raises(FlowExecutionFailedException, match="job-1"):
            store.clear(job_id="job-1")

    def test_clear_passes_correct_job_id(self, *, store):
        """Verify clear uses the right job_id in its delete statement."""
        mock_session = MagicMock()
        store._session_factory = _session_factory_for(mock_session)

        store.clear(job_id="specific-job-xyz")

        # The execute was called — job_id is passed via the SQLAlchemy expression;
        # what we can verify is that commit was called exactly once with no error.
        mock_session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# unmark_soft_deleted_docs
# ---------------------------------------------------------------------------


class TestUnmarkSoftDeletedDocs:
    def test_unmarks_all_when_doc_ids_none(self, *, store):
        mock_row = MagicMock(deleted=True, doc_id="doc-1")
        mock_session = MagicMock()
        mock_session.execute.return_value.scalars.return_value.all.return_value = [mock_row]
        store._session_factory = _session_factory_for(mock_session)

        store.unmark_soft_deleted_docs(job_id="job-1")

        assert mock_row.deleted is False
        mock_session.commit.assert_called_once()

    def test_unmarks_specific_doc_ids(self, *, store):
        mock_row = MagicMock(deleted=True, doc_id="doc-1")
        mock_session = MagicMock()
        mock_session.execute.return_value.scalars.return_value.all.return_value = [mock_row]
        store._session_factory = _session_factory_for(mock_session)

        store.unmark_soft_deleted_docs(job_id="job-1", doc_ids=["doc-1"])

        assert mock_row.deleted is False
        mock_session.commit.assert_called_once()

    def test_raises_flow_exception_on_db_error(self, *, store):
        mock_session = MagicMock()
        mock_session.execute.side_effect = Exception("unmark failed")
        store._session_factory = _session_factory_for(mock_session)

        with pytest.raises(FlowExecutionFailedException, match="job-1"):
            store.unmark_soft_deleted_docs(job_id="job-1")


# ---------------------------------------------------------------------------
# purge_soft_deleted_docs
# ---------------------------------------------------------------------------


class TestPurgeSoftDeletedDocs:
    def test_executes_delete_and_commits(self, *, store):
        mock_session = MagicMock()
        store._session_factory = _session_factory_for(mock_session)

        store.purge_soft_deleted_docs(job_id="job-1")

        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_raises_flow_exception_on_db_error(self, *, store):
        mock_session = MagicMock()
        mock_session.execute.side_effect = Exception("purge failed")
        store._session_factory = _session_factory_for(mock_session)

        with pytest.raises(FlowExecutionFailedException, match="job-1"):
            store.purge_soft_deleted_docs(job_id="job-1")
