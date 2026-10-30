# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Tests for IncrementalUpdateService."""

import hashlib
import multiprocessing
from types import SimpleNamespace
from unittest.mock import Mock

import pyarrow as pa
import pytest
from filelock import Timeout

from docpipe.core.constants.constants import DocpipeConstants, ExecutionStatus, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.incremental_metadata.adapters.stores.filesystem import FilesystemIncrementalMetadataStore
from docpipe.core.incremental_metadata.application.services import IncrementalUpdateService
from docpipe.core.incremental_metadata.domain.models import IncrementalMetadataRecord
from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator
from docpipe.core.operators.vectordb.vectordb_operator import VectorDBOperator
from docpipe.core.orchestration.python.python_orchestrator import PythonOrchestrator
from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException


@pytest.fixture
def store(*, tmp_path):
    """Create Filesystem store for testing."""
    return FilesystemIncrementalMetadataStore(config={"base_dir": str(tmp_path), "lock_timeout": 5.0})


@pytest.fixture
def service(*, store):
    """Create IncrementalUpdateService with store."""
    return IncrementalUpdateService(store=store)


def _build_table(*, ids: list[str], names: list[str], modified_times: list[int]) -> pa.Table:
    """Helper to build PyArrow table."""
    return pa.Table.from_pydict(
        {
            OperatorConstants.Misc.ID: ids,
            OperatorConstants.Misc.NAME: names,
            OperatorConstants.Metadata.MODIFIED_TIME: modified_times,
        }
    )


class TestIncrementalUpdateService:
    """Test IncrementalUpdateService business logic."""

    def test_save_and_get_processed_docs(self, *, service):
        """Test saving metadata and retrieving processed docs."""
        table = _build_table(ids=["doc-1", "doc-2"], names=["a.pdf", "b.pdf"], modified_times=[1000, 2000])

        service.save_metadata_for_incremental_update(job_id="job-1", job_run_id="run-1", tables=[table])

        result = service.get_all_processed_docs(job_id="job-1")
        assert result == {
            "doc-1": {"modified_time": 1000, "job_run_id": "run-1"},
            "doc-2": {"modified_time": 2000, "job_run_id": "run-1"},
        }

    def test_save_with_failed_doc_ids(self, *, service):
        """Test saving metadata with failed document IDs filtered out."""
        table = _build_table(ids=["doc-1", "doc-2", "doc-3"], names=["a", "b", "c"], modified_times=[1000, 2000, 3000])

        service.save_metadata_for_incremental_update(
            job_id="job-1", job_run_id="run-1", tables=[table], failed_doc_ids=["doc-2"]
        )

        result = service.get_all_processed_docs(job_id="job-1")
        assert result == {
            "doc-1": {"modified_time": 1000, "job_run_id": "run-1"},
            "doc-3": {"modified_time": 3000, "job_run_id": "run-1"},
        }

    def test_save_empty_tables(self, *, service):
        """Test saving empty tables does nothing."""
        empty_table = _build_table(ids=[], names=[], modified_times=[])

        service.save_metadata_for_incremental_update(job_id="job-1", job_run_id="run-1", tables=[empty_table])

        result = service.get_all_processed_docs(job_id="job-1")
        assert result == {}

    def test_delete_failed_doc(self, *, service):
        """Test deleting failed documents."""
        input_table = _build_table(ids=["doc-1", "doc-2", "doc-3"], names=["a", "b", "c"], modified_times=[1, 2, 3])
        result_table = _build_table(ids=["doc-1", "doc-3"], names=["a", "c"], modified_times=[1, 3])

        service.save_metadata_for_incremental_update(job_id="job-1", job_run_id="run-1", tables=[input_table])
        remaining_ids = service.delete_failed_doc(table=input_table, result_table=result_table, job_id="job-1")

        assert remaining_ids == {"doc-1", "doc-2", "doc-3"}
        assert service.get_all_processed_docs(job_id="job-1") == {
            "doc-1": {"modified_time": 1, "job_run_id": "run-1"},
            "doc-3": {"modified_time": 3, "job_run_id": "run-1"},
        }

    def test_concatenate_tables(self, *, service):
        """Test concatenating tables with duplicate handling."""
        table1 = pa.Table.from_pydict({OperatorConstants.Misc.ID: ["doc-1", "doc-2"], "value": [10, 20]})
        table2 = pa.Table.from_pydict({OperatorConstants.Misc.ID: ["doc-2", "doc-3"], "value": [200, 30]})

        result = service.concatenate_tables(table1=table1, table2=table2)

        assert result.num_rows == 3
        result_dict = {row[OperatorConstants.Misc.ID]: row["value"] for row in result.to_pylist()}
        assert result_dict == {"doc-1": 10, "doc-2": 20, "doc-3": 30}  # table1 takes precedence

    def test_filter_rows(self, *, service):
        """Test filtering rows by document IDs."""
        table = _build_table(ids=["doc-1", "doc-2", "doc-3"], names=["a", "b", "c"], modified_times=[1, 2, 3])

        filtered = service.filter_rows(table=table, ids_to_delete=["doc-2"])

        assert filtered.num_rows == 2
        assert set(filtered[OperatorConstants.Misc.ID].to_pylist()) == {"doc-1", "doc-3"}

    def test_filter_rows_with_none_table(self, *, service):
        """Test filtering with None table returns None."""
        result = service.filter_rows(table=None, ids_to_delete=["doc-1"])
        assert result is None

    def test_filter_rows_with_empty_ids(self, *, service):
        """Test filtering with empty IDs returns original table."""
        table = _build_table(ids=["doc-1"], names=["a"], modified_times=[1])

        result = service.filter_rows(table=table, ids_to_delete=[])

        assert result == table

    def test_get_deleted_doc_ids_from_dict(self, *, service):
        """Test identifying deleted documents."""
        previously_processed = {"doc-1": 1000, "doc-2": 2000, "doc-3": 3000}
        current_docs = ["doc-1", "doc-3"]

        deleted = service.get_deleted_doc_ids_from_dict(
            previously_processed_docs_dict=previously_processed, doc_ids=current_docs
        )

        assert set(deleted) == {"doc-2"}

    def test_get_deleted_doc_ids_with_empty_previous(self, *, service):
        """Test getting deleted docs with no previous docs."""
        result = service.get_deleted_doc_ids_from_dict(previously_processed_docs_dict={}, doc_ids=["doc-1"])
        assert result == []

    def test_get_deleted_doc_ids_with_none_previous(self, *, service):
        """Test getting deleted docs with None previous docs."""
        result = service.get_deleted_doc_ids_from_dict(previously_processed_docs_dict=None, doc_ids=["doc-1"])
        assert result == []

    def test_mark_soft_deleted_docs(self, *, service):
        """Test marking documents as soft-deleted."""
        table = _build_table(ids=["doc-1", "doc-2", "doc-3"], names=["a", "b", "c"], modified_times=[1, 2, 3])
        service.save_metadata_for_incremental_update(job_id="job-1", job_run_id="run-1", tables=[table])

        deleted_ids = service.mark_soft_deleted_docs(job_id="job-1", doc_ids=["doc-1", "doc-3"])

        assert deleted_ids == {"doc-2"}
        assert service.get_soft_deleted_doc_ids(job_id="job-1") == {"doc-2"}
        assert service.get_all_processed_docs(job_id="job-1") == {
            "doc-1": {"modified_time": 1, "job_run_id": "run-1"},
            "doc-3": {"modified_time": 3, "job_run_id": "run-1"},
        }

    def test_process_ingested_docs_with_force_ingest(self, *, service):
        """Test process_ingested_docs with force_ingest clears metadata."""
        table = _build_table(ids=["doc-1"], names=["a"], modified_times=[1])
        service.save_metadata_for_incremental_update(job_id="job-1", job_run_id="run-1", tables=[table])

        config = {"force_ingest": True}
        service.process_ingested_docs(config=config, job_id="job-1", doc_ids=["doc-2"])

        assert service.get_all_processed_docs(job_id="job-1") == {}

    def test_process_ingested_docs_with_retain_deleted(self, *, service):
        """Test process_ingested_docs with retain_deleted_docs does nothing."""
        table = _build_table(ids=["doc-1", "doc-2"], names=["a", "b"], modified_times=[1, 2])
        service.save_metadata_for_incremental_update(job_id="job-1", job_run_id="run-1", tables=[table])

        config = {"retain_deleted_docs": True}
        service.process_ingested_docs(config=config, job_id="job-1", doc_ids=["doc-1"])

        # Should not mark doc-2 as deleted
        assert service.get_soft_deleted_doc_ids(job_id="job-1") == set()

    def test_process_ingested_docs_marks_deleted(self, *, service):
        """Test process_ingested_docs marks missing docs as deleted."""
        table = _build_table(ids=["doc-1", "doc-2"], names=["a", "b"], modified_times=[1, 2])
        service.save_metadata_for_incremental_update(job_id="job-1", job_run_id="run-1", tables=[table])

        config = {"retain_deleted_docs": False}
        service.process_ingested_docs(config=config, job_id="job-1", doc_ids=["doc-1"])

        assert service.get_soft_deleted_doc_ids(job_id="job-1") == {"doc-2"}

    def test_delete_docs_for_ids(self, *, service):
        """Test permanently deleting documents."""
        table = _build_table(ids=["doc-1", "doc-2"], names=["a", "b"], modified_times=[1, 2])
        service.save_metadata_for_incremental_update(job_id="job-1", job_run_id="run-1", tables=[table])

        service.delete_docs_for_ids(doc_ids=["doc-2"], job_id="job-1")

        assert service.get_all_processed_docs(job_id="job-1") == {
            "doc-1": {"modified_time": 1, "job_run_id": "run-1"},
        }

    def test_delete_docs_with_empty_list(self, *, service):
        """Test deleting with empty list does nothing."""
        table = _build_table(ids=["doc-1"], names=["a"], modified_times=[1])
        service.save_metadata_for_incremental_update(job_id="job-1", job_run_id="run-1", tables=[table])

        service.delete_docs_for_ids(doc_ids=[], job_id="job-1")

        assert service.get_all_processed_docs(job_id="job-1") == {
            "doc-1": {"modified_time": 1, "job_run_id": "run-1"},
        }

    def test_clear_incremental_table(self, *, service):
        """Test clearing all incremental metadata."""
        table = _build_table(ids=["doc-1"], names=["a"], modified_times=[1])
        service.save_metadata_for_incremental_update(job_id="job-1", job_run_id="run-1", tables=[table])

        service.clear_incremental_table(job_id="job-1")

        assert service.get_all_processed_docs(job_id="job-1") == {}

    def test_save_metadata_exception_handling(self, *, service):
        """Test exception handling in save_metadata."""
        from unittest.mock import patch

        table = _build_table(ids=["doc-1"], names=["a"], modified_times=[1])
        with patch.object(service.store, "upsert_records", side_effect=Exception("Store failure")):
            with pytest.raises(FlowExecutionFailedException, match="Store failure"):
                service.save_metadata_for_incremental_update(job_id="job-1", job_run_id="run-1", tables=[table])

    def test_get_all_processed_docs_exception_handling(self, *, service):
        """Test exception handling in get_all_processed_docs."""
        from unittest.mock import patch

        with patch.object(service.store, "get_processed_docs", side_effect=Exception("Read failure")):
            with pytest.raises(FlowExecutionFailedException, match="Read failure"):
                service.get_all_processed_docs(job_id="job-1")

    def test_mark_soft_deleted_docs_exception_handling(self, *, service):
        """Test exception handling in mark_soft_deleted_docs."""
        from unittest.mock import patch

        with patch.object(service.store, "mark_missing_docs_as_deleted", side_effect=Exception("Mark failure")):
            with pytest.raises(FlowExecutionFailedException, match="Mark failure"):
                service.mark_soft_deleted_docs(job_id="job-1", doc_ids=["doc-1"])

    def test_get_soft_deleted_doc_ids_exception_handling(self, *, service):
        """Test exception handling in get_soft_deleted_doc_ids."""
        from unittest.mock import patch

        with patch.object(service.store, "get_soft_deleted_doc_ids", side_effect=Exception("Deleted failure")):
            with pytest.raises(FlowExecutionFailedException, match="Deleted failure"):
                service.get_soft_deleted_doc_ids(job_id="job-1")

    def test_delete_docs_for_ids_exception_handling(self, *, service):
        """Test exception handling in delete_docs_for_ids."""
        from unittest.mock import patch

        with patch.object(service.store, "delete_docs", side_effect=Exception("Delete failure")):
            with pytest.raises(FlowExecutionFailedException, match="Delete failure"):
                service.delete_docs_for_ids(doc_ids=["doc-1"], job_id="job-1")

    def test_save_multiple_tables(self, *, service):
        """Test saving metadata from multiple tables."""
        table1 = _build_table(ids=["doc-1"], names=["a"], modified_times=[1])
        table2 = _build_table(ids=["doc-2"], names=["b"], modified_times=[2])

        service.save_metadata_for_incremental_update(job_id="job-1", job_run_id="run-1", tables=[table1, table2])

        result = service.get_all_processed_docs(job_id="job-1")
        assert result == {
            "doc-1": {"modified_time": 1, "job_run_id": "run-1"},
            "doc-2": {"modified_time": 2, "job_run_id": "run-1"},
        }


class TestSaveMetadataWithFailedAndNonRecoverableDocs:
    """Verify how save_metadata_for_incremental_update treats failed and non-recoverable documents."""

    def test_all_docs_failed_recoverably_leaves_existing_metadata_untouched(self, *, service):
        """When every document of the run failed recoverably, nothing is written and earlier records survive."""
        previous = _build_table(ids=["doc-1"], names=["a"], modified_times=[1])
        service.save_metadata_for_incremental_update(job_id="job-1", job_run_id="run-1", tables=[previous])
        current = _build_table(ids=["doc-1", "doc-2"], names=["a", "b"], modified_times=[10, 20])

        service.save_metadata_for_incremental_update(
            job_id="job-1", job_run_id="run-2", tables=[current], failed_doc_ids=["doc-1", "doc-2"]
        )

        assert service.get_all_processed_docs(job_id="job-1") == {
            "doc-1": {"modified_time": 1, "job_run_id": "run-1"},
        }

    def test_non_recoverable_docs_are_saved_alongside_successful_docs(self, *, service):
        """Non-recoverable docs are persisted even though they failed; recoverable failures are dropped."""
        successful = _build_table(ids=["doc-1", "doc-3"], names=["a", "c"], modified_times=[1, 3])
        non_recoverable = pa.Table.from_pydict(
            {
                OperatorConstants.Misc.ID: ["doc-2"],
                OperatorConstants.Misc.NAME: ["b"],
                OperatorConstants.Metadata.MODIFIED_TIME: [2],
                "error": ["PDFium: Incorrect password error"],
            }
        )

        service.save_metadata_for_incremental_update(
            job_id="job-1",
            job_run_id="run-1",
            tables=[successful],
            failed_doc_ids=["doc-2", "doc-3"],
            non_recoverable_docs_table=non_recoverable,
        )

        assert service.get_all_processed_docs(job_id="job-1") == {
            "doc-1": {"modified_time": 1, "job_run_id": "run-1"},
            "doc-2": {"modified_time": 2, "job_run_id": "run-1"},
        }

    def test_successful_doc_takes_precedence_over_non_recoverable_duplicate(self, *, service):
        """If a doc id appears in both inputs, the successful row's modified_time is stored."""
        successful = _build_table(ids=["doc-1"], names=["a"], modified_times=[100])
        non_recoverable = _build_table(ids=["doc-1", "doc-2"], names=["a", "b"], modified_times=[1, 2])

        service.save_metadata_for_incremental_update(
            job_id="job-1", job_run_id="run-1", tables=[successful], non_recoverable_docs_table=non_recoverable
        )

        assert service.get_all_processed_docs(job_id="job-1") == {
            "doc-1": {"modified_time": 100, "job_run_id": "run-1"},
            "doc-2": {"modified_time": 2, "job_run_id": "run-1"},
        }

    @pytest.mark.parametrize(
        "tables",
        [
            pytest.param([], id="no-tables"),
            pytest.param([_build_table(ids=[], names=[], modified_times=[])], id="only-empty-tables"),
        ],
    )
    def test_non_recoverable_docs_are_saved_when_run_has_no_successful_docs(self, *, service, tables):
        """A run without successful docs still records its non-recoverable docs as processed."""
        non_recoverable = _build_table(ids=["doc-9"], names=["broken.pdf"], modified_times=[9])

        service.save_metadata_for_incremental_update(
            job_id="job-1",
            job_run_id="run-1",
            tables=tables,
            failed_doc_ids=["doc-9"],
            non_recoverable_docs_table=non_recoverable,
        )

        assert service.get_all_processed_docs(job_id="job-1") == {
            "doc-9": {"modified_time": 9, "job_run_id": "run-1"},
        }

    def test_empty_non_recoverable_table_does_not_protect_failed_docs(self, *, service):
        """An empty non-recoverable table is ignored, so every failed doc is treated as recoverable."""
        successful = _build_table(ids=["doc-1", "doc-2"], names=["a", "b"], modified_times=[1, 2])
        empty_non_recoverable = _build_table(ids=[], names=[], modified_times=[])

        service.save_metadata_for_incremental_update(
            job_id="job-1",
            job_run_id="run-1",
            tables=[successful],
            failed_doc_ids=["doc-2"],
            non_recoverable_docs_table=empty_non_recoverable,
        )

        assert service.get_all_processed_docs(job_id="job-1") == {
            "doc-1": {"modified_time": 1, "job_run_id": "run-1"},
        }


class TestIncrementalUpdateServiceStaticMethods:
    """Verify incremental metadata helpers are static and callable without an instance."""

    STATIC_METHODS = (
        "filter_rows",
        "get_deleted_doc_ids_from_dict",
        "_prepare_records_for_save",
        "_get_ids_to_delete",
    )

    def test_service_helpers_are_static(self):
        """Every converted service helper must be a true staticmethod."""
        import inspect

        for method_name in self.STATIC_METHODS:
            assert isinstance(inspect.getattr_static(IncrementalUpdateService, method_name), staticmethod), (
                f"{method_name} is not a staticmethod"
            )

    def test_get_deleted_doc_ids_from_dict_class_call(self):
        """Deleted-doc detection works when called directly on the class."""
        assert IncrementalUpdateService.get_deleted_doc_ids_from_dict(
            previously_processed_docs_dict={"doc-1": 1, "doc-2": 2}, doc_ids=["doc-1"]
        ) == ["doc-2"]

        assert (
            IncrementalUpdateService.get_deleted_doc_ids_from_dict(previously_processed_docs_dict={}, doc_ids=["doc-1"])
            == []
        )

    def test_get_ids_to_delete_class_call(self):
        """Failed-doc detection works when called directly on the class."""
        input_table = pa.table({OperatorConstants.Misc.ID: ["doc-1", "doc-2", "doc-3"]})
        result_table = pa.table({OperatorConstants.Misc.ID: ["doc-1", "doc-3"]})

        assert set(IncrementalUpdateService._get_ids_to_delete(input_table=input_table, result_table=result_table)) == {
            "doc-2"
        }


@pytest.fixture
def sync_service(*, tmp_path, monkeypatch):
    instance = IncrementalUpdateService(
        store=FilesystemIncrementalMetadataStore(config={"base_dir": str(tmp_path / "tracking"), "lock_timeout": 0.2})
    )
    for module in (
        "operators.ingest.ingest_source",
        "operators.vectordb.vectordb_operator",
        "orchestration.abstract_orchestrator",
    ):
        monkeypatch.setattr(f"docpipe.core.{module}.get_incremental_update_service", lambda: instance)
    return instance


def ingest(*, root, force=False, retain=False, limit=10):
    return IngestSourceOperator(
        {
            "provider": "filesystem",
            "provider_config": {"paths": [str(root)]},
            "context_id": "scope",
            "force_ingest": force,
            "retain_deleted_docs": retain,
            "max_files": limit,
        }
    )


def reconcile(*, sync_service, metadata):
    evidence = metadata[Metrics.Internal.SOURCE_DISCOVERY]
    assert evidence["complete"]
    return sync_service.reconcile_discovery(
        job_id="scope", missing_ids=set(evidence["missing_ids"]), returned_ids=set(evidence["returned_ids"])
    )


def test_ten_runs_select_disjoint_groups_and_detect_only_missing(*, tmp_path, sync_service):
    root = tmp_path / "source"
    root.mkdir()
    for i in range(100):
        (root / f"{i}.txt").write_text(str(i))
    selected: set[str] = set()
    for i in range(10):
        tables, metadata = ingest(root=root).transform(None)
        assert len(tables[0]) == 10
        assert metadata["source_documents_discovered"] == 100
        ids = set(tables[0]["id"].to_pylist())
        assert not ids & selected
        assert reconcile(sync_service=sync_service, metadata=metadata) == set()
        sync_service.save_metadata_for_incremental_update(job_id="scope", job_run_id=str(i), tables=tables)
        selected.update(ids)
    assert len(selected) == 100
    removed = root / "1.txt"
    removed_id = hashlib.md5(f"file://{removed.absolute()}".encode(), usedforsecurity=False).hexdigest()
    removed.unlink()
    tables, metadata = ingest(root=root).transform(None)
    assert tables[0].num_rows == 0
    assert reconcile(sync_service=sync_service, metadata=metadata) == {removed_id}
    # A second complete scan must not purge the unacknowledged tombstone.
    _, metadata = ingest(root=root).transform(None)
    assert reconcile(sync_service=sync_service, metadata=metadata) == {removed_id}


@pytest.mark.parametrize("force", [False, True])
def test_deleted_files_detected_with_forced_ingestion(*, tmp_path, sync_service, force):
    (tmp_path / "a.txt").write_text("a")
    tables, _ = ingest(root=tmp_path).transform(None)
    sync_service.save_metadata_for_incremental_update(job_id="scope", job_run_id="first", tables=tables)
    sync_service.store.upsert_records(
        job_id="scope",
        job_run_id="first",
        records=[IncrementalMetadataRecord(job_id="scope", doc_id="missing", deleted=False)],
    )
    tables, metadata = ingest(root=tmp_path, force=force).transform(None)
    assert tables[0].num_rows == int(force)
    assert reconcile(sync_service=sync_service, metadata=metadata) == {"missing"}
    assert len(sync_service.get_all_processed_docs(job_id="scope")) == 1


def test_acknowledgment_never_deletes_regenerated_rows(sync_service):
    sync_service.store.upsert_records(
        job_id="scope",
        job_run_id="1",
        records=[
            IncrementalMetadataRecord(job_id="scope", doc_id="a", deleted=True),
            IncrementalMetadataRecord(job_id="scope", doc_id="b", deleted=False),
        ],
    )
    sync_service.store.acknowledge_deletions(job_id="scope", doc_ids={"a", "b"})
    assert set(sync_service.get_all_processed_docs(job_id="scope")) == {"b"}
    assert not sync_service.get_soft_deleted_doc_ids(job_id="scope")


def test_reappearance_cancels_tombstone_and_requires_reprocessing(sync_service):
    sync_service.store.upsert_records(
        job_id="scope",
        job_run_id="1",
        records=[IncrementalMetadataRecord(job_id="scope", doc_id="returned", deleted=True)],
    )
    assert sync_service.reconcile_discovery(job_id="scope", missing_ids=set(), returned_ids={"returned"}) == set()
    assert sync_service.get_all_processed_docs(job_id="scope")["returned"]["modified_time"] is None


class VectorSink:
    """A small chunk store with a failing destination option."""

    def __init__(self, *, fail=False):
        self.chunks = {"missing": {"chunk-a", "chunk-b"}, "present": {"keep"}}
        self.fail = fail
        self.closed = False
        self.lookups = 0

    def resolve_source_chunks(self, *, doc_ids):
        self.lookups += 1
        if self.fail:
            raise ConnectionError("lookup failed")
        return {doc_id: self.chunks[doc_id].copy() for doc_id in doc_ids if self.chunks.get(doc_id)}

    def delete_documents_by_ids(self, ids):
        for values in self.chunks.values():
            values.difference_update(ids)
        return len(ids), 0

    def refresh_index(self):
        pass

    def close(self):
        self.closed = True


def operator(*, sink):
    op = object.__new__(VectorDBOperator)
    op.adapter, op.context_id, op.job_id = sink, "scope", "other-job"
    op.job_run_id = "run"
    op.config = {DocpipeConstants.SOURCE_DELETION_CLEANUP: True, "retain_deleted_docs": False}
    op.common_log_arguments = {}
    return op


def test_cleanup_is_idempotent_and_retains_unrelated_chunks(sync_service):
    sync_service.store.upsert_records(
        job_id="scope",
        job_run_id="1",
        records=[IncrementalMetadataRecord(job_id="scope", doc_id="missing", deleted=True)],
    )
    sink = VectorSink()
    op = operator(sink=sink)
    for _ in range(2):
        _, metadata = op.transform(pa.table({}))
        assert metadata[Metrics.Internal.SOURCE_DELETION_RESULT] == ["missing"]
    assert sink.chunks["present"] == {"keep"}
    assert not sink.chunks["missing"]
    assert sink.closed
    assert sync_service.get_soft_deleted_doc_ids(job_id="scope") == {"missing"}


def test_two_destinations_keep_backlog_until_both_succeed(*, sync_service, monkeypatch):
    sync_service.store.upsert_records(
        job_id="scope",
        job_run_id="1",
        records=[IncrementalMetadataRecord(job_id="scope", doc_id="missing", deleted=False)],
    )
    orch = PythonOrchestrator()
    orch.context_id = "scope"
    orch.job_status = ExecutionStatus.RUNNING
    sinks = {"one": VectorSink(), "two": VectorSink(fail=True)}
    monkeypatch.setattr(orch, "_create_empty_result", lambda: None)
    monkeypatch.setattr(orch, "_handle_node_failure", Mock())

    def step(*, op_def, **kwargs):
        _, metadata = operator(sink=sinks[op_def["name"]]).transform(pa.table({}))
        return SimpleNamespace(internal_metadata=metadata)

    monkeypatch.setattr(orch, "_execute_step", step)
    flow = [
        {"operator": "ingest_source"},
        {"operator": "vectordb", "name": "one"},
        {"operator": "vectordb", "name": "two"},
    ]
    config = {"retain_deleted_docs": False, "continue_on_batch_failure": True}
    evidence = {"complete": True, "scope": "scope", "missing_ids": ["missing"]}
    assert orch._synchronize_source_deletions(op_flow=flow, global_config=config, evidence=evidence) == 0
    assert sync_service.get_soft_deleted_doc_ids(job_id="scope") == {"missing"}
    sinks["two"].fail = False
    assert orch._synchronize_source_deletions(op_flow=flow, global_config=config, evidence=evidence) == 1
    assert not sync_service.get_soft_deleted_doc_ids(job_id="scope")


def test_incomplete_scan_never_consumes_pending(sync_service):
    sync_service.store.upsert_records(
        job_id="scope",
        job_run_id="1",
        records=[IncrementalMetadataRecord(job_id="scope", doc_id="missing", deleted=True)],
    )
    orch = PythonOrchestrator()
    orch.context_id = "scope"
    assert (
        orch._synchronize_source_deletions(
            op_flow=[], global_config={"retain_deleted_docs": False}, evidence={"complete": False}
        )
        == 0
    )
    assert sync_service.get_soft_deleted_doc_ids(job_id="scope") == {"missing"}


def _competing_guard(*, base, queue):
    store = FilesystemIncrementalMetadataStore(config={"base_dir": base, "lock_timeout": 0.1})
    try:
        with store.synchronization_guard(job_id="scope"):
            queue.put("acquired")
    except Timeout:
        queue.put("blocked")


def test_guard_blocks_other_process_but_not_batch_writes(sync_service):
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    with sync_service.store.synchronization_guard(job_id="scope"):
        process = ctx.Process(
            target=_competing_guard, kwargs={"base": str(sync_service.store._base_dir), "queue": queue}
        )
        process.start()
        process.join(timeout=20)
        assert process.exitcode == 0
        assert queue.get(timeout=2) == "blocked"
        sync_service.store.mark_deleted_candidates(job_id="scope", doc_ids={"a"})
        with sync_service.store.synchronization_guard(job_id="other"):
            pass
    with sync_service.store.synchronization_guard(job_id="scope"):
        pass
    queue.close()


@pytest.mark.parametrize("batching", [False, True])
@pytest.mark.parametrize("with_documents", [False, True])
@pytest.mark.parametrize("force", [False, True])
def test_deletion_only_run_reaches_real_vector_executor(
    *, tmp_path, sync_service, monkeypatch, batching, with_documents, force
):
    from concurrent.futures import ThreadPoolExecutor

    from docpipe.core.models.session_info import SessionInfo, set_session_info
    from docpipe.core.operators.vectordb.adapters.outbound.factories.vector_store_factory import VectorStoreFactory

    root = tmp_path / "empty"
    root.mkdir()
    if with_documents:
        for index in range(8):
            (root / f"{index}.txt").write_text(str(index))
    sync_service.store.upsert_records(
        job_id="scope", job_run_id="1", records=[IncrementalMetadataRecord(job_id="scope", doc_id="missing")]
    )
    sink = VectorSink()
    monkeypatch.setattr(VectorStoreFactory, "create", lambda *args, **kwargs: sink)
    orch = PythonOrchestrator()
    orch.job_id, orch.job_run_id, orch.context_id = "job", "run", "scope"
    orch.job_status, orch.common_log_arguments = ExecutionStatus.RUNNING, {}
    set_session_info(SessionInfo(job_id="job", job_run_id="run"))
    orch.flow_execution_event_handler = Mock()
    orch.flow_engine = Mock()

    def prepare(*, ingested_table, global_config, **kwargs):
        return [ingested_table.slice(offset, 2) for offset in range(0, len(ingested_table), 2)], global_config

    def run_batches(*, batches, **kwargs):
        assert sink.lookups == 2  # Cleanup happened once, before any processing batches.
        assert not sync_service.get_soft_deleted_doc_ids(job_id="scope")

        def save(table):
            sync_service.save_metadata_for_incremental_update(job_id="scope", job_run_id="run", tables=[table])

        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(save, batches))

    monkeypatch.setattr(orch.batch_manager, "prepare_batches", prepare)
    orch.flow_engine.execute_batch_flow.side_effect = run_batches
    monkeypatch.setattr(orch, "_finalize_dag_flow", Mock())
    monkeypatch.setattr(orch, "_notify_observer", Mock())
    flow = [
        {
            "id": "ingest",
            "name": "ingest",
            "operator": "ingest_source",
            "config": {"provider": "filesystem", "provider_config": {"paths": [str(root)]}, "max_files": 5},
        },
        {
            "id": "vector",
            "name": "vector",
            "operator": "vectordb",
            "config": {"provider": "opensearch", "provider_config": {"index_name": "test"}},
        },
    ]
    config = {
        "context_id": "scope",
        "job_id": "job",
        "job_run_id": "run",
        "retain_deleted_docs": False,
        "enable_micro_batching": batching,
        "force_ingest": force,
        "data_config": {"da_class": "data_processing.data_access.DataAccessMemory"},
    }
    orch.execute_flow(op_flow=flow, global_config=config)
    assert not sync_service.get_soft_deleted_doc_ids(job_id="scope")
    assert sink.chunks["missing"] == set()
    assert sink.chunks["present"] == {"keep"}
    if with_documents:
        orch.flow_engine.execute_batch_flow.assert_called_once()
        assert len(sync_service.get_all_processed_docs(job_id="scope")) == 5
    else:
        orch.flow_engine.execute_batch_flow.assert_not_called()
    orch.flow_execution_event_handler.after_node_skipped.assert_not_called()


def test_large_lazy_inventory_does_not_convert_unselected_documents(*, tmp_path, sync_service, monkeypatch):
    from docpipe.core.operators.ingest.domain.models import Document

    adapter = Mock()

    async def discovery(config, *, full_listing=False):
        for i in range(100_000):
            yield Document(id=str(i), name=f"{i}.txt", content=b"", source_url=str(i))

    adapter.fetch_documents = discovery
    op = ingest(root=tmp_path, limit=10)
    monkeypatch.setattr(op, "_build_adapter_config", lambda provider: (adapter, None))
    convert = Mock(wraps=op._domain_doc_to_langchain)
    monkeypatch.setattr(op, "_domain_doc_to_langchain", convert)
    tables, metadata = op.transform(None)
    assert len(tables[0]) == 10
    assert metadata["source_documents_discovered"] == 100_000
    assert convert.call_count == 10


@pytest.mark.parametrize("force", [False, True])
def test_retention_enabled_never_requires_discovery(*, tmp_path, sync_service, monkeypatch, force):
    (tmp_path / "a.txt").write_text("a")
    op = ingest(root=tmp_path, retain=True, force=force, limit=1)
    monkeypatch.setattr(op, "_process_with_discovery", Mock(side_effect=AssertionError("unexpected full scan")))
    tables, metadata = op.transform(None)
    assert len(tables[0]) == 1
    assert Metrics.Internal.SOURCE_DISCOVERY not in metadata


@pytest.mark.parametrize("accepts_kwargs", [False, True])
def test_legacy_fetch_cannot_authorize_deletions(*, tmp_path, sync_service, monkeypatch, accepts_kwargs):
    async def legacy(config):
        yield

    async def permissive_legacy(config, **kwargs):
        yield

    adapter = Mock()
    adapter.fetch_documents = permissive_legacy if accepts_kwargs else legacy
    op = ingest(root=tmp_path)
    monkeypatch.setattr(op, "_build_adapter_config", lambda provider: (adapter, None))
    fallback = Mock(return_value=[])
    monkeypatch.setattr(op, "process_documents", fallback)
    _, metadata = op.transform(None)
    fallback.assert_called_once()
    assert not metadata[Metrics.Internal.SOURCE_DISCOVERY]["complete"]
    assert not metadata[Metrics.Internal.SOURCE_DISCOVERY]["missing_ids"]


def test_discovery_failure_after_selection_aborts_ingestion(*, tmp_path, sync_service, monkeypatch):
    from docpipe.core.operators.ingest.domain.models import Document

    adapter = Mock()

    async def failing_listing(config, *, full_listing=False):
        yield Document(id="a", name="a.txt", content=b"", source_url="a")
        raise PermissionError("failed next page")

    adapter.fetch_documents = failing_listing
    op = ingest(root=tmp_path)
    monkeypatch.setattr(op, "_build_adapter_config", lambda provider: (adapter, None))
    sync_service.store.upsert_records(
        job_id="scope", job_run_id="1", records=[IncrementalMetadataRecord(job_id="scope", doc_id="tracked")]
    )
    with pytest.raises(PermissionError, match="failed next page"):
        op.transform(None)
    assert set(sync_service.get_all_processed_docs(job_id="scope")) == {"tracked"}
    assert not sync_service.get_soft_deleted_doc_ids(job_id="scope")


def test_cancelled_run_cannot_reconcile(*, sync_service):
    sync_service.store.upsert_records(
        job_id="scope", job_run_id="1", records=[IncrementalMetadataRecord(job_id="scope", doc_id="a")]
    )
    orch = PythonOrchestrator()
    orch.context_id, orch.job_status = "scope", ExecutionStatus.CANCELING
    evidence = {"complete": True, "scope": "scope", "missing_ids": ["a"]}
    assert (
        orch._synchronize_source_deletions(op_flow=[], global_config={"retain_deleted_docs": False}, evidence=evidence)
        == 0
    )
    assert not sync_service.get_soft_deleted_doc_ids(job_id="scope")


def test_discovery_failure_aborts_flow_before_cleanup(*, tmp_path, sync_service, monkeypatch):
    from docpipe.core.operators.ingest.adapters.outbound.sources.filesystem.adapter import FilesystemSourceAdapter
    from docpipe.core.operators.ingest.domain.models import Document

    async def failing_listing(self, config, *, full_listing=False):
        yield Document(id="a", name="a.txt", content=b"", source_url="a")
        raise PermissionError("unreadable subtree")

    monkeypatch.setattr(FilesystemSourceAdapter, "fetch_documents", failing_listing)
    orch = PythonOrchestrator()
    orch.job_id, orch.job_run_id = "job", "run"
    orch.job_status, orch.common_log_arguments = ExecutionStatus.RUNNING, {}
    orch.flow_execution_event_handler = Mock()
    monkeypatch.setattr(orch, "_notify_observer", Mock())
    failed = Mock()
    cleanup = Mock()
    monkeypatch.setattr(orch, "_handle_node_failure", failed)
    monkeypatch.setattr(orch, "_synchronize_source_deletions", cleanup)
    prepare = Mock()
    monkeypatch.setattr(orch.batch_manager, "prepare_batches", prepare)
    flow = [
        {
            "id": "ingest",
            "name": "ingest",
            "operator": "ingest_source",
            "config": {"provider": "filesystem", "provider_config": {"paths": [str(tmp_path)]}, "max_files": 1},
        },
        {"id": "vector", "name": "vector", "operator": "vectordb"},
    ]
    with pytest.raises(PermissionError, match="unreadable subtree"):
        orch.execute_flow(
            op_flow=flow,
            global_config={
                "context_id": "scope",
                "job_id": "job",
                "job_run_id": "run",
                "retain_deleted_docs": False,
                "data_config": {"da_class": "data_processing.data_access.DataAccessMemory"},
            },
        )
    failed.assert_called_once()
    cleanup.assert_not_called()
    prepare.assert_not_called()


@pytest.mark.parametrize("force", [False, True])
def test_full_scan_does_not_materialize_history(*, tmp_path, sync_service, monkeypatch, force):
    (tmp_path / "a.txt").write_text("a")
    tables, _ = ingest(root=tmp_path).transform(None)
    sync_service.save_metadata_for_incremental_update(job_id="scope", job_run_id="first", tables=tables)
    monkeypatch.setattr(sync_service, "get_all_processed_docs", Mock(side_effect=AssertionError("unbounded history")))
    tables, metadata = ingest(root=tmp_path, force=force).transform(None)
    assert tables[0].num_rows == int(force)
    assert metadata["source_documents_missing"] == 0


def test_reappeared_document_beyond_limit_can_be_deleted_again(*, tmp_path, sync_service, monkeypatch):
    from docpipe.core.operators.ingest.domain.models import Document
    from docpipe.core.operators.ingest.ports.outbound.document_source import DocumentSourcePort

    first_id = hashlib.md5(b"first", usedforsecurity=False).hexdigest()
    returned_id = hashlib.md5(b"returned", usedforsecurity=False).hexdigest()
    sync_service.store.upsert_records(
        job_id="scope",
        job_run_id="old",
        records=[IncrementalMetadataRecord(job_id="scope", doc_id=returned_id, modified_time=10)],
    )
    sync_service.store.mark_deleted_candidates(job_id="scope", doc_ids={returned_id})
    documents = [Document(id=key, name=f"{key}.txt", source_url=key, content=b"") for key in ("first", "returned")]
    adapter = Mock()
    adapter._is_processing_eligible = DocumentSourcePort._is_processing_eligible

    async def fetch(config, *, full_listing=False):
        for document in documents:
            yield document

    adapter.fetch_documents = fetch
    op = ingest(root=tmp_path, limit=1)
    monkeypatch.setattr(op, "_build_adapter_config", lambda provider: (adapter, None))
    tables, metadata = op.transform(None)
    assert tables[0]["id"].to_pylist() == [first_id]
    assert reconcile(sync_service=sync_service, metadata=metadata) == set()
    assert sync_service.get_all_processed_docs(job_id="scope")[returned_id]["modified_time"] is None
    sync_service.save_metadata_for_incremental_update(job_id="scope", job_run_id="first", tables=tables)
    documents.pop()
    _, metadata = op.transform(None)
    assert reconcile(sync_service=sync_service, metadata=metadata) == {returned_id}
    sink = VectorSink()
    sink.chunks = {returned_id: {"orphaned-chunk"}, first_id: {"keep"}}
    _, metadata = operator(sink=sink).transform(pa.table({}))
    assert metadata[Metrics.Internal.SOURCE_DELETION_RESULT] == [returned_id]
    assert sink.chunks == {returned_id: set(), first_id: {"keep"}}
