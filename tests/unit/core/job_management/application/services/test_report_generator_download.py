"""JobReportGenerator.download_report with real stores and real files.

Job and node stats live in the production ``JobTrackerService`` over an
``InMemoryJobStatsStore``; flow definition snapshots, operator parquet output
and the generated CSV report are real files below ``tmp_path`` (the data path,
the snapshot storage and the report storage all resolve to it).
"""

import asyncio
import csv
import io
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.responses import StreamingResponse

import docpipe.storage.file_system.key_value_file_system_storage  # noqa: F401  (registers the filesystem backend)
from docpipe.core.constants.constants import DocpipeConstants, ExecutionStatus
from docpipe.core.job_management.adapters.config import (
    flow_definition_snapshot_storage_factory,
    report_storage_factory,
)
from docpipe.core.job_management.adapters.services.job_tracker_service import JobTrackerService
from docpipe.core.job_management.adapters.stores.inmemory.inmemory_job_stats_store import InMemoryJobStatsStore
from docpipe.core.job_management.application.services.node_stats_aggregator import NodeStatsAggregator
from docpipe.core.job_management.application.services.report_generator import (
    GENERIC_FAILURE_MESSAGE,
    JobReportGenerator,
)
from docpipe.core.job_management.domain.models import JobStats, NodeStats
from docpipe.core.models.session_info import session_info_var
from docpipe.exceptions.docpipe_exceptions import (
    JobRunInvalidStateException,
    JobRunNotFoundException,
    JobRunOperationFailedException,
)

JOB_ID = "job-invoices"
JOB_RUN_ID = "run-0001"
INGEST_ID = "node-ingest"
EXTRACT_ID = "node-extract"
CHUNK_ID = "node-chunk"
VECTOR_ID = "node-vector"
DOCSET_ID = "node-docset"

INGEST_START = 1000
NEW_YEAR_2026 = 1767225600  # 2026-01-01T00:00:00Z

# ingest -> extract -> [vector DB, document set]
BRANCHED_DAG = [
    {
        "id": INGEST_ID,
        "name": "Ingest files",
        "operator": "ingest_source",
        "input_edges": [],
        "output_edges": [EXTRACT_ID],
    },
    {
        "id": EXTRACT_ID,
        "name": "Extract text",
        "operator": "extract_operator",
        "input_edges": [INGEST_ID],
        "output_edges": [VECTOR_ID, DOCSET_ID],
    },
    {"id": VECTOR_ID, "name": "Vector DB", "operator": "vectordb", "input_edges": [EXTRACT_ID], "output_edges": []},
    {
        "id": DOCSET_ID,
        "name": "Document set",
        "operator": "document_set",
        "input_edges": [EXTRACT_ID],
        "output_edges": [],
    },
]

# ingest -> extract -> chunker -> vector DB
LINEAR_DAG = [
    {
        "id": INGEST_ID,
        "name": "Ingest files",
        "operator": "ingest_source",
        "input_edges": [],
        "output_edges": [EXTRACT_ID],
    },
    {
        "id": EXTRACT_ID,
        "name": "Extract text",
        "operator": "extract_operator",
        "input_edges": [INGEST_ID],
        "output_edges": [CHUNK_ID],
    },
    {"id": CHUNK_ID, "name": "Chunk", "operator": "chunker", "input_edges": [EXTRACT_ID], "output_edges": [VECTOR_ID]},
    {"id": VECTOR_ID, "name": "Vector DB", "operator": "vectordb", "input_edges": [CHUNK_ID], "output_edges": []},
]

INGESTED_DOCUMENTS: list[dict[str, Any]] = [
    {"id": "d1", "name": "invoice-001.pdf", "modified_time": NEW_YEAR_2026},
    {"id": "d2", "name": "invoice-002.pdf", "modified_time": NEW_YEAR_2026 * 1000},  # epoch milliseconds
    {"id": "d3", "name": "scan.pdf", "modified_time": NEW_YEAR_2026 + 86400},
    {"id": "d4", "name": "contract.docx", "modified_time": None},
    {"id": None, "name": "row-without-id.pdf", "modified_time": NEW_YEAR_2026},
]


def _reasons(*, node_id: str, operator: str, failed=(), skipped=()) -> dict:
    """NodeMetadataItem-shaped metadata carrying per-document reasons."""
    return {
        "id": node_id,
        "operator": operator,
        "node_metadata": {
            "failed_docs": [{"id": doc_id, "reason": reason} for doc_id, reason in failed],
            "skipped_docs": [{"id": doc_id, "reason": reason} for doc_id, reason in skipped],
        },
    }


@pytest.fixture(autouse=True)
def isolated_session_info():
    """download_report writes job_id/job_run_id into the current SessionInfo."""
    token = session_info_var.set(None)
    yield
    session_info_var.reset(token)


@pytest.fixture
def data_root(*, tmp_path, monkeypatch) -> Path:
    """Resolve the data path, the snapshot storage and the report storage to tmp_path."""
    monkeypatch.setenv(DocpipeConstants.DOCPIPE_DATA_PATH, str(tmp_path))
    monkeypatch.setenv("DOCPIPE_CONFIG_PATH", str(tmp_path / "no-config.yaml"))
    monkeypatch.setattr(flow_definition_snapshot_storage_factory, "_default_factory", None)
    monkeypatch.setattr(report_storage_factory, "_default_factory", None)
    return tmp_path


@pytest.fixture
def tracker() -> JobTrackerService:
    """Production JobTrackerService over an in-memory store."""
    store = InMemoryJobStatsStore()
    return JobTrackerService(job_stats_store=store, node_stats_aggregator=NodeStatsAggregator(job_stats_store=store))


def _write_parquet(*, data_root: Path, node_name: str, rows: list[dict], batch_num: int | None = None) -> None:
    folder = data_root / JOB_ID / JOB_RUN_ID / "data" / f"{node_name.replace(' ', '_')}_0"
    if batch_num is not None:
        folder /= str(batch_num)
    folder.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), folder / "output.parquet")


def _start_run(*, tracker: JobTrackerService, dag: list[dict] | None) -> None:
    tracker.start_tracking_job(job_id=JOB_ID, job_run_id=JOB_RUN_ID, flow_id="flow-1", flow_name="Invoices")
    if dag is not None:
        tracker.save_flow_definition(job_id=JOB_ID, job_run_id=JOB_RUN_ID, flow_definition={"dag": dag})


def _store(tracker: JobTrackerService, **fields) -> None:
    tracker.job_stats_store.store_node_stats(job_run_id=JOB_RUN_ID, node_stats=NodeStats(**fields))


def _record_branched_run(*, tracker: JobTrackerService, data_root: Path) -> None:
    """Non-batched run: d1 -> vector DB, d2 skipped at vector DB, d3 failed at extract, d4 -> document set."""
    _start_run(tracker=tracker, dag=BRANCHED_DAG)
    all_docs = ["d1", "d2", "d3", "d4"]
    _store(
        tracker,
        id=INGEST_ID,
        name="Ingest files",
        node_status="Completed",
        start_time=INGEST_START,
        end_time=1005,
        total_docs=all_docs,
        docs_completed=all_docs,
    )
    _store(
        tracker,
        id=EXTRACT_ID,
        name="Extract text",
        node_status="Completed",
        start_time=1005,
        end_time=1030,
        total_docs=all_docs,
        docs_completed=["d1", "d2", "d4"],
        failed_docs=["d3"],
        node_metadata=_reasons(node_id=EXTRACT_ID, operator="Extract text", failed=[("d3", "Password protected")]),
    )
    _store(
        tracker,
        id=VECTOR_ID,
        name="Vector DB",
        node_status="Completed",
        start_time=1030,
        end_time=1042,
        total_docs=["d1", "d2"],
        docs_completed=["d1"],
        skipped_docs=["d2"],
        node_metadata=_reasons(node_id=VECTOR_ID, operator="Vector DB", skipped=[("d2", "Duplicate document")]),
    )
    _store(
        tracker,
        id=DOCSET_ID,
        name="Document set",
        node_status="Completed",
        start_time=1030,
        end_time=1030,  # finished within the same second as extract
        total_docs=["d4"],
        docs_completed=["d4"],
    )
    tracker.end_job(job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED_WITH_ERRORS.value)

    _write_parquet(data_root=data_root, node_name="Ingest files", rows=INGESTED_DOCUMENTS)
    _write_parquet(
        data_root=data_root,
        node_name="Extract text",
        rows=[
            {"id": "d1", "pages_processed": 3},
            {"id": "d2", "pages_processed": 1},
            {"id": "d3", "pages_processed": None},
            {"id": "d4", "pages_processed": 12},
            {"id": "not-ingested", "pages_processed": 5},
        ],
    )


def _record_cancelled_batched_run(*, tracker: JobTrackerService, data_root: Path) -> None:
    """Micro-batched run cancelled while batch 1 was in the chunker.

    Batch 0: d1 reaches the vector DB, d2 fails at extract.
    Batch 1: d3 and d4 pass extract; the chunker never finished, the vector DB never started.
    """
    _start_run(tracker=tracker, dag=LINEAR_DAG)
    all_docs = ["d1", "d2", "d3", "d4"]
    _store(
        tracker,
        id=INGEST_ID,
        name="Ingest files",
        node_status="Completed",
        start_time=INGEST_START,
        end_time=1004,
        total_docs=all_docs,
        docs_completed=all_docs,
    )
    _store(
        tracker,
        id=EXTRACT_ID,
        name="Extract text",
        node_status="Completed",
        batch_id="b0",
        batch_num=0,
        start_time=1004,
        end_time=1020,
        total_docs=["d1", "d2"],
        docs_completed=["d1"],
        failed_docs=["d2"],
        node_metadata=_reasons(node_id=EXTRACT_ID, operator="Extract text", failed=[("d2", "Corrupt PDF")]),
    )
    _store(
        tracker,
        id=EXTRACT_ID,
        name="Extract text",
        node_status="Completed",
        batch_id="b1",
        batch_num=1,
        start_time=1020,
        end_time=1025,
        total_docs=["d3", "d4"],
        docs_completed=["d3", "d4"],
    )
    _store(
        tracker,
        id=CHUNK_ID,
        name="Chunk",
        node_status="Completed",
        batch_id="b0",
        batch_num=0,
        start_time=1020,
        end_time=1030,
        total_docs=["d1"],
        docs_completed=["d1"],
    )
    _store(
        tracker,
        id=CHUNK_ID,
        name="Chunk",
        node_status="Running",
        batch_id="b1",
        batch_num=1,
        start_time=1025,
        total_docs=["d3", "d4"],
    )
    _store(
        tracker,
        id=VECTOR_ID,
        name="Vector DB",
        node_status="Completed",
        batch_id="b0",
        batch_num=0,
        start_time=1030,
        end_time=1040,
        total_docs=["d1"],
        docs_completed=["d1"],
    )
    tracker.end_job(job_run_id=JOB_RUN_ID, status=ExecutionStatus.CANCELED.value)

    _write_parquet(data_root=data_root, node_name="Ingest files", rows=INGESTED_DOCUMENTS[:4])
    _write_parquet(
        data_root=data_root,
        node_name="Extract text",
        batch_num=0,
        rows=[{"id": "d1", "pages_processed": 2}, {"id": "d2", "pages_processed": None}],
    )
    _write_parquet(
        data_root=data_root,
        node_name="Extract text",
        batch_num=1,
        rows=[{"id": "d3", "pages_processed": 7}, {"id": "d4", "pages_processed": 4}],
    )


async def _read_body(response: StreamingResponse) -> str:
    chunks = [chunk async for chunk in response.body_iterator]
    return "".join(chunk if isinstance(chunk, str) else bytes(chunk).decode("utf-8") for chunk in chunks)


def _download(tracker: JobTrackerService) -> tuple[StreamingResponse, list[dict[str, str]], str]:
    response = JobReportGenerator.download_report(job_run_id=JOB_RUN_ID, job_stats_service=tracker)
    body = asyncio.run(_read_body(response))
    return response, list(csv.DictReader(io.StringIO(body))), body


def _row(guid, name, status, reason, timestamp, pages, seconds) -> dict[str, str]:
    return dict(zip(JobReportGenerator.HEADERS, [guid, name, status, reason, timestamp, pages, seconds], strict=True))


class TestDownloadReportPreconditions:
    """The report is only produced for known, finished runs with intermediate data."""

    def test_unknown_run_is_not_found(self, *, tracker, data_root):
        with pytest.raises(JobRunNotFoundException) as caught:
            JobReportGenerator.download_report(job_run_id="missing-run", job_stats_service=tracker)

        assert caught.value.status_code == 404
        assert caught.value.job_run_id == "missing-run"

    @pytest.mark.parametrize("status", [ExecutionStatus.QUEUED, ExecutionStatus.RUNNING, ExecutionStatus.CANCELING])
    def test_unfinished_run_is_too_early(self, *, tracker, data_root, status):
        tracker.start_tracking_job(job_id=JOB_ID, job_run_id=JOB_RUN_ID, flow_id="flow-1", initial_status=status)

        with pytest.raises(JobRunInvalidStateException) as caught:
            JobReportGenerator.download_report(job_run_id=JOB_RUN_ID, job_stats_service=tracker)

        assert caught.value.status_code == 425
        assert caught.value.current_state == status

    def test_run_without_intermediate_data_is_unprocessable(self, *, tracker, data_root):
        _start_run(tracker=tracker, dag=BRANCHED_DAG)
        tracker.end_job(job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED.value)

        with pytest.raises(JobRunOperationFailedException, match="Data directory not found") as caught:
            JobReportGenerator.download_report(job_run_id=JOB_RUN_ID, job_stats_service=tracker)

        assert caught.value.status_code == 422
        assert caught.value.operation == "generate_report"

    def test_run_without_flow_snapshot_has_no_document_data(self, *, tracker, data_root):
        _start_run(tracker=tracker, dag=None)
        tracker.end_job(job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED.value)
        _write_parquet(data_root=data_root, node_name="Ingest files", rows=INGESTED_DOCUMENTS[:1])

        with pytest.raises(JobRunOperationFailedException, match="No document data found") as caught:
            JobReportGenerator.download_report(job_run_id=JOB_RUN_ID, job_stats_service=tracker)

        assert caught.value.status_code == 422
        assert not (data_root / JOB_ID / JOB_RUN_ID / f"job_report_{JOB_RUN_ID}.csv").exists()

    def test_unreadable_flow_snapshot_fails_generation(self, *, tracker, data_root):
        _start_run(tracker=tracker, dag=None)
        tracker.end_job(job_run_id=JOB_RUN_ID, status=ExecutionStatus.COMPLETED.value)
        _write_parquet(data_root=data_root, node_name="Ingest files", rows=INGESTED_DOCUMENTS[:1])
        (data_root / JOB_ID / JOB_RUN_ID / "flow_definition.json").write_text("{truncated", encoding="utf-8")

        with pytest.raises(JobRunOperationFailedException, match=r"^Failed to generate report: ") as caught:
            JobReportGenerator.download_report(job_run_id=JOB_RUN_ID, job_stats_service=tracker)

        assert caught.value.status_code == 500
        assert caught.value.__cause__ is not None


class TestDownloadReportGeneration:
    """Reports are generated on demand from node stats and parquet output, then cached."""

    def test_branched_run_report_is_generated_saved_and_reused(self, *, tracker, data_root):
        _record_branched_run(tracker=tracker, data_root=data_root)

        response, rows, body = _download(tracker)

        assert response.media_type == "text/csv"
        assert response.headers["content-disposition"] == f'attachment; filename="job_report_{JOB_RUN_ID}.csv"'
        assert rows == [
            _row("d1", "invoice-001.pdf", "Ingested", "", "2026-01-01:00:00:00", "3", "42"),
            _row("d2", "invoice-002.pdf", "Skipped", "Duplicate document", "2026-01-01:00:00:00", "1", "42"),
            _row("d3", "scan.pdf", "Failed", "Password protected", "2026-01-02:00:00:00", "", "30"),
            _row("d4", "contract.docx", "Ingested", "", "", "12", "30"),
        ]
        assert body.startswith(",".join(JobReportGenerator.HEADERS))
        saved_report = data_root / JOB_ID / JOB_RUN_ID / f"job_report_{JOB_RUN_ID}.csv"
        assert list(csv.DictReader(io.StringIO(saved_report.read_text(encoding="utf-8")))) == rows

        # Once saved, the report is served from storage even without the parquet data.
        for parquet_file in (data_root / JOB_ID / JOB_RUN_ID / "data").rglob("output.parquet"):
            parquet_file.unlink()
        _, cached_rows, _ = _download(tracker)
        assert cached_rows == rows

    def test_cancelled_micro_batched_run_report(self, *, tracker, data_root):
        _record_cancelled_batched_run(tracker=tracker, data_root=data_root)

        _, rows, _ = _download(tracker)

        assert rows == [
            _row("d1", "invoice-001.pdf", "Ingested", "", "2026-01-01:00:00:00", "2", "40"),
            _row("d2", "invoice-002.pdf", "Failed", "Corrupt PDF", "2026-01-01:00:00:00", "", "20"),
            _row("d3", "scan.pdf", "Failed", GENERIC_FAILURE_MESSAGE, "2026-01-02:00:00:00", "7", "25"),
            _row("d4", "contract.docx", "Failed", GENERIC_FAILURE_MESSAGE, "", "4", "25"),
        ]


class TestBatchEdgeCases:
    """Batch records that the on-demand path can receive from older or partial runs."""

    @staticmethod
    def _generator(*, batch_node_stats, dag_nodes=None, node_stats=None) -> JobReportGenerator:
        job_stats = JobStats(
            job_id=JOB_ID,
            job_run_id=JOB_RUN_ID,
            status=ExecutionStatus.COMPLETED,
            node_stats=node_stats or {},
            batch_node_stats=batch_node_stats,
        )
        return JobReportGenerator(job_stats=job_stats, dag_nodes=dag_nodes if dag_nodes is not None else [])

    def test_batch_records_without_batch_num_use_the_unbatched_parquet_path(self):
        generator = self._generator(
            batch_node_stats={EXTRACT_ID: {"b0": NodeStats(id=EXTRACT_ID, name="Extract text", batch_id="b0")}}
        )

        assert generator._get_actual_batch_nums(EXTRACT_ID) == {None}

    def test_first_batch_node_falls_back_to_batch_stats_order_when_dag_has_none_of_them(self):
        generator = self._generator(
            batch_node_stats={"node-from-other-compile": {"b0": NodeStats(id="node-from-other-compile", name="x")}},
            dag_nodes=LINEAR_DAG,
        )

        assert generator._find_first_batching_operator() == "node-from-other-compile"

    def test_batch_timing_without_destination_nodes_uses_latest_node_end_time(self):
        cyclic_dag = [
            {"id": INGEST_ID, "name": "Ingest files", "input_edges": [], "output_edges": [EXTRACT_ID]},
            {"id": EXTRACT_ID, "name": "Extract text", "input_edges": [INGEST_ID], "output_edges": [INGEST_ID]},
        ]
        generator = self._generator(
            batch_node_stats={
                EXTRACT_ID: {
                    "b0": NodeStats(id=EXTRACT_ID, name="Extract text", batch_id="b0", end_time=1012, total_docs=["d1"])
                }
            },
            dag_nodes=cyclic_dag,
            node_stats={INGEST_ID: NodeStats(id=INGEST_ID, name="Ingest files", start_time=INGEST_START)},
        )

        assert generator._build_doc_to_batch_mapping() == {"d1": "12"}
