"""Tests for IncrementalUpdateService."""

import pyarrow as pa
import pytest

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.incremental_metadata.adapters.stores.filesystem import FilesystemIncrementalMetadataStore
from docpipe.core.incremental_metadata.application.services import IncrementalUpdateService
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

        with patch.object(service.store, "get_soft_deleted_doc_ids", side_effect=Exception("Mark failure")):
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
