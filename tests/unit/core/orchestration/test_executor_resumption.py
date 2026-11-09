# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for resumption handling in AbstractOperatorExecutor (injection, deferred accounting, failure capture)."""

from unittest.mock import Mock

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import DocpipeConstants, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.orchestration.abstract_operator_executor import AbstractOperatorExecutor
from docpipe.core.orchestration.adapters.filesystem_resumption_store import FilesystemResumptionStore
from docpipe.core.orchestration.application.services.resumption_service import ResumptionService

JOB_ID = "job-exec"
NODE_ID = "node-4"
BATCH_ID = "batch-1"


class _Executor(AbstractOperatorExecutor):
    """Minimal concrete executor; the operator itself is not needed for these tests."""

    def get_operator(self):
        return Mock()


def _table(*doc_ids: str) -> pa.Table:
    return pa.table(
        {
            "id": list(doc_ids),
            "name": [f"{d}.pdf" for d in doc_ids],
            "modified_time": pa.array([100] * len(doc_ids), type=pa.int64()),
        }
    )


@pytest.fixture
def store(tmp_path, monkeypatch):
    fs_store = FilesystemResumptionStore(root=str(tmp_path))
    monkeypatch.setattr(
        "docpipe.core.orchestration.abstract_operator_executor.create_resumption_service",
        lambda *, config: ResumptionService(store=fs_store, max_retry_attempts=3),
    )
    return fs_store


def _executor(*, node_id: str = NODE_ID, plan: dict | None = None, job_stats=None) -> _Executor:
    params = {
        OperatorConstants.Columns.ID: node_id,
        DocpipeConstants.JOB_ID: JOB_ID,
        DocpipeConstants.JOB_RUN_ID: "run-1",
        DocpipeConstants.BATCH_ID: BATCH_ID,
        DocpipeConstants.RESUMPTION_PLAN: plan,
        DocpipeConstants.DATA_STORAGE_TYPE: "memory",
    }
    return _Executor(name="chunker", operator="chunker", params=params, job_stats_service=job_stats)


def _plan(*, target: str = NODE_ID, pending: tuple[str, ...] = ("node-2", "node-3"), path: str = "p") -> dict:
    return {
        BATCH_ID: [
            {"doc_id": "d1", "target_node_id": target, "checkpoint_path": path, "pending_node_ids": list(pending)}
        ]
    }


class TestInjection:
    def test_target_node_receives_checkpoint_rows(self, store):
        path = store.write_checkpoint(job_id=JOB_ID, node_id="node-3", doc_id="d1", table=_table("d1"))
        executor = _executor(plan=_plan(path=path))

        merged = executor._inject_resumed_documents(tables=_table("fresh"))

        assert merged.column("id").to_pylist() == ["fresh", "d1"]
        assert executor.resumption_injection_pending() is True

    def test_target_node_with_empty_input_still_gets_documents(self, store):
        path = store.write_checkpoint(job_id=JOB_ID, node_id="node-3", doc_id="d1", table=_table("d1"))
        executor = _executor(plan=_plan(path=path))

        merged = executor._inject_resumed_documents(tables=_table())

        assert merged.column("id").to_pylist() == ["d1"]

    def test_upstream_node_carries_but_does_not_inject(self, store):
        executor = _executor(node_id="node-2", plan=_plan())
        base = _table("fresh")

        merged = executor._inject_resumed_documents(tables=base)

        assert merged is base
        assert executor._carried_deferred_ids == ["d1"]
        assert executor.resumption_injection_pending() is False

    def test_node_after_target_is_unaffected(self, store):
        executor = _executor(node_id="node-5", plan=_plan())
        base = _table("fresh")

        assert executor._inject_resumed_documents(tables=base) is base
        assert executor._carried_deferred_ids == []

    def test_no_plan_is_a_noop(self, store):
        executor = _executor(plan=None)
        base = _table("fresh")

        assert executor._inject_resumed_documents(tables=base) is base
        assert executor.resumption_injection_pending() is False

    def test_missing_checkpoint_is_reported_unavailable(self, store):
        executor = _executor(plan=_plan(path="checkpoints/none/none.parquet"))

        executor._inject_resumed_documents(tables=_table("fresh"))

        assert [e["doc_id"] for e in executor._unavailable_resumed_entries] == ["d1"]


class TestDeferredAccounting:
    def test_upstream_node_reports_deferred_and_scope(self, store):
        executor = _executor(node_id="node-2", plan=_plan())
        executor._inject_resumed_documents(tables=_table("f1", "f2"))
        metadata = {Metrics.External.TOTAL_DOCS: 2}

        executor._apply_resumption_to_metadata(metadata=metadata)

        assert metadata[Metrics.External.TOTAL_DOCS] == 3
        assert metadata[Metrics.External.DEFERRED_EXECUTION_DOCS] == ["d1"]
        assert metadata[Metrics.External.DEFERRED_EXECUTION_DOCS_COUNT] == 1

    def test_total_docs_in_scope_includes_carried_documents(self, store):
        executor = _executor(node_id="node-2", plan=_plan())
        executor._inject_resumed_documents(tables=_table("f1"))

        assert executor._total_docs_in_scope(tables=_table("f1")) == ["f1", "d1"]

    def test_target_node_has_no_deferred_documents(self, store):
        path = store.write_checkpoint(job_id=JOB_ID, node_id="node-3", doc_id="d1", table=_table("d1"))
        executor = _executor(plan=_plan(path=path))
        executor._inject_resumed_documents(tables=_table("f1"))
        metadata = {Metrics.External.TOTAL_DOCS: 2}

        executor._apply_resumption_to_metadata(metadata=metadata)

        assert Metrics.External.DEFERRED_EXECUTION_DOCS not in metadata
        assert metadata[Metrics.External.TOTAL_DOCS] == 2

    def test_unavailable_checkpoint_becomes_failed_document(self, store, monkeypatch):
        record_failed = Mock()
        monkeypatch.setattr(
            "docpipe.core.orchestration.abstract_operator_executor.AbstractOperator.record_failed_document",
            record_failed,
        )
        executor = _executor(plan=_plan(path="checkpoints/none/none.parquet"))
        executor._inject_resumed_documents(tables=_table("f1"))
        metadata = {Metrics.External.TOTAL_DOCS: 1, Metrics.External.FAILED_DOCS_COUNT: 0}

        executor._apply_resumption_to_metadata(metadata=metadata)

        record_failed.assert_called_once()
        assert record_failed.call_args.kwargs["doc_id"] == "d1"
        assert metadata[Metrics.External.TOTAL_DOCS] == 2

    def test_final_stats_pass_deferred_docs_to_job_stats_service(self, store):
        job_stats = Mock()
        executor = _executor(node_id="node-2", plan=_plan(), job_stats=job_stats)
        executor._inject_resumed_documents(tables=_table("f1"))
        metadata = {
            Metrics.External.TOTAL_DOCS: 1,
            Metrics.External.NODE_STATUS: "Completed",
            Metrics.External.FAILED_DOCS: [],
            Metrics.External.SKIPPED_DOCS: [],
        }

        executor.update_final_node_stats(tables=[_table("f1")], metadata=metadata)

        kwargs = job_stats.complete_node_execution.call_args.kwargs
        assert kwargs["deferred_execution_docs"] == ["d1"]
        assert kwargs["docs_completed"] == ["f1"]
        assert Metrics.Internal.DEFERRED_ENTRIES not in kwargs["node_metadata"]


class TestFailureCapture:
    def _executor_with_input(self, store, *docs: str) -> _Executor:
        executor = _executor(plan=None)
        executor._resumption_input = _table(*docs)
        executor._params[DocpipeConstants.DATA_STORAGE_TYPE] = "local"
        return executor

    def test_failed_documents_are_recorded_with_checkpoint(self, store):
        executor = self._executor_with_input(store, "d1", "d2")
        metadata = {Metrics.External.FAILED_DOCS: [{"id": "d1", "name": "d1.pdf", "reason": "oops"}]}

        executor._record_failures_from_metadata(metadata=metadata)

        record = store.get_record(job_id=JOB_ID, doc_id="d1")
        assert record.failed_node_id == NODE_ID
        assert record.failure_count == 1
        assert store.get_record(job_id=JOB_ID, doc_id="d2") is None
        assert store.checkpoint_exists(job_id=JOB_ID, path=record.checkpoint_path)

    def test_non_recoverable_documents_are_not_recorded(self, store):
        executor = self._executor_with_input(store, "d1")
        metadata = {
            Metrics.External.FAILED_DOCS: [{"id": "d1", "name": "d1.pdf", "reason": "corrupt"}],
            Metrics.Internal.NON_RECOVERABLE_DOCS_TABLE: _table("d1"),
        }

        executor._record_failures_from_metadata(metadata=metadata)

        assert store.get_record(job_id=JOB_ID, doc_id="d1") is None

    def test_exhausted_document_reason_is_rewritten_and_persisted_non_recoverable(self, store, monkeypatch):
        saved = Mock()
        monkeypatch.setattr(
            "docpipe.core.incremental_metadata.get_incremental_update_service",
            lambda: Mock(save_metadata_for_incremental_update=saved),
        )
        executor = self._executor_with_input(store, "d1")
        failed = {"id": "d1", "name": "d1.pdf", "reason": "oops"}
        for _ in range(4):
            failed["reason"] = "oops"
            executor._record_failures_from_metadata(metadata={Metrics.External.FAILED_DOCS: [failed]})

        assert failed["reason"].startswith("Maximum retries exhausted")
        assert saved.call_count == 1
        persisted = saved.call_args.kwargs["tables"][0]
        assert persisted.column("id").to_pylist() == ["d1"]
        assert store.get_record(job_id=JOB_ID, doc_id="d1").exhausted is True

    def test_node_exception_records_every_input_document(self, store):
        executor = self._executor_with_input(store, "d1", "d2")

        executor._record_node_failure(exc=RuntimeError("node down"))

        assert store.get_record(job_id=JOB_ID, doc_id="d1").last_reason.startswith("RuntimeError")
        assert store.get_record(job_id=JOB_ID, doc_id="d2") is not None

    def test_failure_capture_is_inactive_without_local_storage(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "docpipe.core.orchestration.abstract_operator_executor.create_resumption_service", lambda *, config: None
        )
        executor = _executor(plan=None)
        executor._resumption_input = _table("d1")

        executor._record_failures_from_metadata(metadata={Metrics.External.FAILED_DOCS: [{"id": "d1"}]})
        executor._record_node_failure(exc=RuntimeError("x"))
