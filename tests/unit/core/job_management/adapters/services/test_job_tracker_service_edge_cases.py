"""JobTrackerService edge cases on the real in-memory store, aggregator and DTO mapper.

The flow definition snapshot storage is a process-wide singleton built from the YAML config, so
the tests point its accessor at a real KeyValueFileSystemStorage in tmp_path.
"""

import uuid
from pathlib import Path
from typing import Any

import pytest

from docpipe.core.constants.constants import ExecutionStatus, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.job_management.adapters.config import flow_definition_snapshot_storage_factory as snapshot_factory
from docpipe.core.job_management.adapters.services.job_tracker_service import JobTrackerService
from docpipe.core.job_management.adapters.stores.inmemory.inmemory_job_stats_store import InMemoryJobStatsStore
from docpipe.core.job_management.application.services.node_stats_aggregator import NodeStatsAggregator
from docpipe.core.job_management.domain.models import NodeStats
from docpipe.core.operators.abstract_operator import OperatorCategory
from docpipe.exceptions.docpipe_exceptions import DocpipeException, JobRunNotFoundException
from docpipe.storage.file_system.key_value_file_system_storage import KeyValueFileSystemStorage

JOB_ID = "6f1b6e2c-3d4a-4c5b-9e8f-0a1b2c3d4e5f"


@pytest.fixture
def store() -> InMemoryJobStatsStore:
    return InMemoryJobStatsStore()


@pytest.fixture
def service(store: InMemoryJobStatsStore) -> JobTrackerService:
    return JobTrackerService(job_stats_store=store, node_stats_aggregator=NodeStatsAggregator(job_stats_store=store))


@pytest.fixture
def run(service: JobTrackerService) -> str:
    job_run_id = str(uuid.uuid4())
    service.start_tracking_job(job_id=JOB_ID, job_run_id=job_run_id, flow_id="flow-1")
    return job_run_id


def _node(store: InMemoryJobStatsStore, job_run_id: str, node_id: str, batch_id: str | None = None) -> NodeStats:
    return store.get_node_stats_by_batch_and_node(job_run_id=job_run_id, batch_id=batch_id, node_id=node_id)


class TestJobLifecycle:
    def test_end_job_records_report_timestamps(self, service, run):
        service.end_job(
            job_run_id=run,
            status=ExecutionStatus.COMPLETED,
            job_run_stats={"report_generation_started_at": 10, "report_generation_completed_at": 20},
        )

        stats = service.get_job_run_stats(job_run_id=run)
        assert (stats.report_generation_started_at, stats.report_generation_completed_at) == (10, 20)

    def test_cancel_request_for_an_unknown_run(self, service):
        with pytest.raises(JobRunNotFoundException, match="Job run not found: nope"):
            service.request_cancel_job(job_run_id="nope")

    def test_canceling_job_is_finished_and_logged(self, service, run, tmp_path):
        service.request_cancel_job(job_run_id=run)
        log_path = tmp_path / "job.log"

        assert service.cancel_job_run_if_cancelling(job_run_id=run, job_log_path=str(log_path)) is True

        assert service.get_job_run_stats(job_run_id=run).status == ExecutionStatus.CANCELED
        assert log_path.is_file()

    def test_store_and_list_delegate_to_the_store(self, service, run, store):
        stats = service.get_job_run_stats(job_run_id=run)
        stats.message = "updated"

        service.store_job_stats(job_stats=stats)
        service.bulk_store_node_stats(job_id=JOB_ID, job_run_id=run, node_stats_list=[NodeStats(id="n1", name="N1")])

        assert [j.message for j in service.list_job_runs(job_id=JOB_ID)] == ["updated"]
        assert [n.id for n in store.get_node_stats(job_run_id=run)] == ["n1"]


class TestNodeExecution:
    def test_completed_node_reports_failed_and_skipped_docs(self, service, run, store):
        service.start_node_execution(job_run_id=run, node_id="n1", node_name="N1", total_docs=["a", "b", "c"])

        service.complete_node_execution(
            job_run_id=run,
            node_id="n1",
            node_name="N1",
            docs_completed=["a"],
            failed_docs=["b"],
            skipped_docs=["c"],
            col_names=[],
            node_status=ExecutionStatus.COMPLETED_WITH_ERRORS,
        )

        assert _node(store, run, "n1").error == "Node completed with issues: 1 failed, 1 skipped"

    def test_completed_node_with_only_skipped_docs(self, service, run, store):
        service.start_node_execution(job_run_id=run, node_id="n1", node_name="N1", total_docs=["c"])
        service.complete_node_execution(
            job_run_id=run,
            node_id="n1",
            node_name="N1",
            docs_completed=[],
            failed_docs=[],
            skipped_docs=["c"],
            col_names=[],
            node_status=ExecutionStatus.COMPLETED_WITH_WARNINGS,
        )

        assert _node(store, run, "n1").error == "Node completed with issues: 1 skipped"

    @pytest.mark.parametrize(
        ("finish", "extra"),
        [
            ("fail_node_execution", {"error": "boom"}),
            ("cancel_node_execution", {}),
            ("abort_node_execution", {"reason": "upstream failed"}),
            ("skip_node_execution", {"reason": "no input", "col_names": []}),
        ],
        ids=["fail", "cancel", "abort", "skip"],
    )
    def test_batch_number_of_the_started_node_is_kept(self, service, run, store, finish, extra):
        service.start_node_execution(
            job_run_id=run, node_id="n1", node_name="N1", total_docs=["a"], batch_id="b1", batch_num=3
        )

        getattr(service, finish)(job_run_id=run, node_id="n1", node_name="N1", batch_id="b1", **extra)

        assert _node(store, run, "n1", batch_id="b1").batch_num == 3


class TestDocCounts:
    def test_metadata_updates_counts_pages_and_page_types(self, service, run):
        service.update_doc_counts(
            job_run_id=run,
            operator_category=OperatorCategory.Ingest.value,
            metadata={
                Metrics.External.DELETED_DOC_COUNT: 2,
                Metrics.External.TOTAL_DOCS: ["a", "b", "c"],
                OperatorConstants.Metadata.TOTAL_PAGES_PROCESSED: 4,
                OperatorConstants.Metadata.PAGE_TYPE_STATS: {"text": 3},
            },
        )
        service.update_doc_counts(
            job_run_id=run,
            operator_category=OperatorCategory.Ingest.value,
            metadata={
                Metrics.External.TOTAL_DOCS: 5,
                OperatorConstants.Metadata.TOTAL_PAGES_PROCESSED: 1,
                OperatorConstants.Metadata.PAGE_TYPE_STATS: {"text": 1, "scanned": 2},
            },
        )

        stats = service.get_job_run_stats(job_run_id=run)
        assert (stats.deleted_doc_count, stats.total_docs, stats.total_pages_processed) == (2, 5, 5)
        assert stats.page_type_stats == {"text": 4, "scanned": 2}
        assert stats.execution_time is not None

    def test_values_of_unexpected_types_are_ignored(self, service, run):
        service.update_doc_counts(
            job_run_id=run,
            operator_category=OperatorCategory.Ingest.value,
            metadata={
                Metrics.External.TOTAL_DOCS: "many",
                OperatorConstants.Metadata.TOTAL_PAGES_PROCESSED: "4",
                OperatorConstants.Metadata.PAGE_TYPE_STATS: {},
            },
        )

        stats = service.get_job_run_stats(job_run_id=run)
        assert (stats.total_docs, stats.total_pages_processed, stats.page_type_stats) == (0, 0, None)


class TestFinalDocumentCounts:
    def test_without_an_ingest_node_no_documents_are_skipped(self, service, run):
        service.start_node_execution(job_run_id=run, node_id="sink", node_name="Sink", total_docs=["a"])
        job = service.get_job(job_run_id=run, include_node_stats=True)
        dag = [{"id": None}, {"id": "sink", "input_edges": ["x"]}]

        service.determine_and_update_final_documents_count(job_stats=job, dag_nodes=dag)

        assert (job.completed_docs, job.failed_docs, job.skipped_docs) == (0, 0, 0)

    def test_count_mismatch_with_total_docs_is_kept(self, service, run):
        service.start_node_execution(job_run_id=run, node_id="ingest", node_name="Ingest", total_docs=["a", "b"])
        job = service.get_job(job_run_id=run, include_node_stats=True)
        job.total_docs = 5

        service.determine_and_update_final_documents_count(job_stats=job, dag_nodes=[{"id": "ingest"}])

        assert (job.total_docs, job.processed_docs, job.skipped_docs) == (5, 2, 2)


@pytest.mark.parametrize(("value", "expected"), [(["a", "b"], 2), (None, 0), (3, 3), ("x", 0)])
def test_count_items(value: Any, expected: int):
    assert JobTrackerService._count_items(value=value) == expected


class TestFormattedStats:
    def test_formatted_stats_for_a_run(self, service, run):
        response = service.get_formatted_job_stats(job_run_id=run)

        assert (response.job_stats.job_run_id, response.node_sequence) == (run, [])

    def test_formatted_stats_for_an_unknown_run(self, service):
        with pytest.raises(JobRunNotFoundException, match="Job run not found: nope"):
            service.get_formatted_job_stats(job_run_id="nope")


class TestFlowDefinitionSnapshots:
    @pytest.fixture
    def snapshots(self, tmp_path: Path, monkeypatch) -> KeyValueFileSystemStorage:
        storage = KeyValueFileSystemStorage(base_dir=str(tmp_path / "snapshots"))
        monkeypatch.setattr(snapshot_factory, "get_flow_definitions_snapshot_storage", lambda: storage)
        return storage

    def test_saved_definition_is_returned(self, service, run, snapshots):
        service.save_flow_definition(job_id=JOB_ID, job_run_id=run, flow_definition={"flow_name": "f"})

        assert service.get_flow_definition(job_run_id=run) == {"flow_name": "f"}

    def test_missing_definition_is_none(self, service, run, snapshots):
        assert service.get_flow_definition(job_run_id=run) is None

    def test_unknown_run(self, service, snapshots):
        with pytest.raises(DocpipeException, match="Job run not found: nope") as exc:
            service.get_flow_definition(job_run_id="nope")

        assert exc.value.status_code == 404

    @pytest.mark.parametrize(
        ("error", "status_code"),
        [(DocpipeException("disk is read-only", status_code=503), 503), (OSError("disk full"), 500)],
        ids=["docpipe-error", "unexpected-error"],
    )
    def test_storage_errors(self, service, run, snapshots, monkeypatch, error, status_code):
        def _fail(**kwargs):
            raise error

        monkeypatch.setattr(snapshots, "save_record", _fail)
        monkeypatch.setattr(snapshots, "get_record", _fail)

        with pytest.raises(DocpipeException) as saved:
            service.save_flow_definition(job_id=JOB_ID, job_run_id=run, flow_definition={})
        with pytest.raises(DocpipeException) as read:
            service.get_flow_definition(job_run_id=run)

        assert (saved.value.status_code, read.value.status_code) == (status_code, status_code)


class TestNothingToDo:
    def test_ingest_metadata_without_total_docs_keeps_the_count(self, service, run):
        service.update_doc_counts(job_run_id=run, operator_category=OperatorCategory.Ingest.value, metadata={})

        assert service.get_job_run_stats(job_run_id=run).total_docs == 0

    def test_no_pending_stats_without_batches(self, service, run, store):
        service.create_pending_batch_node_stats(
            job_run_id=run, batch_ids=[], batch_nums=[], downstream_node_ids=["n1"], downstream_node_names=["N1"]
        )

        assert store.get_node_stats(job_run_id=run) == []

    def test_finished_batches_are_not_marked_as_skipped(self, service, run, store):
        service.start_node_execution(job_run_id=run, node_id="n1", node_name="N1", total_docs=["a"], batch_id="b1")
        service.cancel_node_execution(job_run_id=run, node_id="n1", node_name="N1", batch_id="b1")

        service.mark_pending_batches_as_skipped(job_run_id=run, reason="job failed")

        assert _node(store, run, "n1", batch_id="b1").node_status == ExecutionStatus.CANCELED
