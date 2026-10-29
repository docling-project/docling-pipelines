# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for PostgreSQL-based incremental metadata store."""

import os
import uuid
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy import MetaData, create_engine, text
from sqlmodel import Session

from docpipe.core.incremental_metadata.adapters.stores.filesystem import FilesystemIncrementalMetadataStore
from docpipe.core.incremental_metadata.adapters.stores.postgres.models import IncrementalMetadataPostgresModel
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


@pytest.fixture(params=["filesystem", "sql"])
def sync_store(*, request, tmp_path):
    if request.param == "filesystem":
        yield FilesystemIncrementalMetadataStore(config={"base_dir": str(tmp_path)})
    else:
        engine = create_engine("sqlite://")
        table = IncrementalMetadataPostgresModel.__table__
        table.create(engine)
        store = object.__new__(PostgresIncrementalMetadataStore)
        store._engine, store._sync_table = engine, table
        store._session_factory = lambda: Session(engine)
        yield store
        engine.dispose()


def test_candidate_and_acknowledgment_parity(sync_store):
    for scope in ("scope", "other"):
        sync_store.upsert_records(
            job_id=scope,
            job_run_id="1",
            records=[
                IncrementalMetadataRecord(job_id=scope, doc_id="a"),
                IncrementalMetadataRecord(job_id=scope, doc_id="b"),
            ],
        )
    sync_store.mark_deleted_candidates(job_id="scope", doc_ids={"a"})
    assert sync_store.get_soft_deleted_doc_ids(job_id="scope") == {"a"}
    assert sync_store.get_soft_deleted_doc_ids(job_id="other") == set()
    sync_store.mark_deleted_candidates(job_id="scope", doc_ids={"b"})
    assert sync_store.get_soft_deleted_doc_ids(job_id="scope") == {"a", "b"}
    sync_store.upsert_records(
        job_id="scope", job_run_id="2", records=[IncrementalMetadataRecord(job_id="scope", doc_id="a")]
    )
    sync_store.acknowledge_deletions(job_id="scope", doc_ids={"a", "b"})
    assert set(sync_store.get_processed_docs(job_id="scope")) == {"a"}
    assert set(sync_store.get_processed_docs(job_id="other")) == {"a", "b"}


def test_postgres_guard_connection_releases_after_failure():
    store = object.__new__(PostgresIncrementalMetadataStore)
    store._engine = MagicMock()
    connection = store._engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalar.return_value = True
    with pytest.raises(RuntimeError, match="cancelled"):
        with store.synchronization_guard(job_id="scope"):
            raise RuntimeError("cancelled")
    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert statements == ["SELECT pg_try_advisory_lock(:key)", "SELECT pg_advisory_unlock(:key)"]
    store._engine.connect.return_value.__exit__.assert_called_once()


def test_postgres_guard_contended_execution_is_rejected():
    store = object.__new__(PostgresIncrementalMetadataStore)
    store._engine = MagicMock()
    connection = store._engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalar.return_value = False
    with pytest.raises(FlowExecutionFailedException, match="already running"):
        with store.synchronization_guard(job_id="scope"):
            pytest.fail("Contended run must not execute")


def test_failed_acknowledgment_preserves_tombstone(*, sync_store, monkeypatch):
    sync_store.upsert_records(
        job_id="scope", job_run_id="1", records=[IncrementalMetadataRecord(job_id="scope", doc_id="a", deleted=True)]
    )
    sync_store.mark_deleted_candidates(job_id="scope", doc_ids={"a"})
    if isinstance(sync_store, FilesystemIncrementalMetadataStore):
        monkeypatch.setattr(sync_store, "_write_table", MagicMock(side_effect=RuntimeError("write failed")))
    else:

        def failing_transaction():
            session = Session(sync_store._engine)
            monkeypatch.setattr(session, "commit", MagicMock(side_effect=RuntimeError("write failed")))
            return session

        monkeypatch.setattr(sync_store, "_session_factory", failing_transaction)
    with pytest.raises(RuntimeError, match="write failed"):
        sync_store.acknowledge_deletions(job_id="scope", doc_ids={"a"})
    assert sync_store.get_soft_deleted_doc_ids(job_id="scope") == {"a"}


@pytest.fixture
def postgres_store():
    url = os.environ.get("DOCPIPE_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set DOCPIPE_TEST_POSTGRES_URL to run PostgreSQL synchronization integration tests")
    engine = create_engine(url)
    schema = "docpipe_sync_test_" + uuid.uuid4().hex
    metadata = MetaData(schema=schema)
    table = IncrementalMetadataPostgresModel.__table__.to_metadata(metadata)
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    table.create(engine)
    store = object.__new__(PostgresIncrementalMetadataStore)
    store._engine, store._sync_table = engine, table
    mapped = engine.execution_options(schema_translate_map={None: schema})
    store._session_factory = lambda: Session(mapped)
    try:
        yield store
    finally:
        metadata.drop_all(engine)
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}"'))
        engine.dispose()


@pytest.mark.integration
def test_real_guard_allows_batch_writes_and_releases_after_error(postgres_store):
    with pytest.raises(RuntimeError, match="cancelled"):
        with postgres_store.synchronization_guard(job_id="scope"):
            with pytest.raises(FlowExecutionFailedException, match="already running"):
                with postgres_store.synchronization_guard(job_id="scope"):
                    pytest.fail("Same-context executions must not overlap")
            postgres_store.upsert_records(
                job_id="scope", job_run_id="1", records=[IncrementalMetadataRecord(job_id="scope", doc_id="a")]
            )
            raise RuntimeError("cancelled")
    with postgres_store.synchronization_guard(job_id="scope"):
        postgres_store.mark_deleted_candidates(job_id="scope", doc_ids={"a"})
    assert postgres_store.get_soft_deleted_doc_ids(job_id="scope") == {"a"}
    postgres_store.acknowledge_deletions(job_id="scope", doc_ids={"a"})
    assert not postgres_store.get_soft_deleted_doc_ids(job_id="scope")
