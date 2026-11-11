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
RUN_ID = "run-1"
NODE_ID = "node-4"
BATCH_ID = "batch-1"
SOURCE_NODE = "extract"


class _Executor(AbstractOperatorExecutor):
    """Minimal concrete executor; the operator itself is not needed for these tests."""

    def get_operator(self):
        return Mock()


class _FakeReader:
    """Serves saved node outputs keyed by (job_run_id, node_name, output_index)."""

    def __init__(self) -> None:
        self.tables: dict[tuple[str, str, int], pa.Table] = {}

    def read_rows(self, *, job_run_id, node_name, output_index, doc_ids):
        table = self.tables.get((job_run_id, node_name, output_index))
        if table is None:
            return None
        return table.filter(pa.array([i in doc_ids for i in table.column("id").to_pylist()]))


def _table(*doc_ids: str) -> pa.Table:
    return pa.table(
        {
            "id": list(doc_ids),
            "name": [f"{d}.pdf" for d in doc_ids],
            "modified_time": pa.array([100] * len(doc_ids), type=pa.int64()),
        }
    )


@pytest.fixture
def reader():
    return _FakeReader()


@pytest.fixture
def store(tmp_path, monkeypatch, reader):
    fs_store = FilesystemResumptionStore(root=str(tmp_path))
    monkeypatch.setattr(
        "docpipe.core.orchestration.abstract_operator_executor.create_resumption_service",
        lambda *, config: ResumptionService(store=fs_store, max_retry_attempts=3, output_reader=reader),
    )
    return fs_store


def _executor(*, node_id: str = NODE_ID, plan: dict | None = None, job_stats=None, name: str = "chunker") -> _Executor:
    params = {
        OperatorConstants.Columns.ID: node_id,
        DocpipeConstants.JOB_ID: JOB_ID,
        DocpipeConstants.JOB_RUN_ID: "run-2",
        DocpipeConstants.BATCH_ID: BATCH_ID,
        DocpipeConstants.RESUMPTION_PLAN: plan,
        DocpipeConstants.DATA_STORAGE_TYPE: "local",
    }
    return _Executor(name=name, operator="chunker", params=params, job_stats_service=job_stats)


def _entry(
    doc_id: str = "d1",
    *,
    target: str = NODE_ID,
    pending: tuple[str, ...] = ("node-2", "node-3"),
    run: str = RUN_ID,
    error: str = "original failure",
) -> dict:
    return {
        "doc_id": doc_id,
        "doc_name": f"{doc_id}.pdf",
        "target_node_id": target,
        "job_run_id": run,
        "error_message": error,
        "source_node_name": SOURCE_NODE,
        "source_output_index": 0,
        "pending_node_ids": list(pending),
    }


def _plan(*entries: dict) -> dict:
    return {BATCH_ID: list(entries or [_entry()])}


class TestInjection:
    def test_target_node_receives_saved_rows(self, store, reader):
        reader.tables[(RUN_ID, SOURCE_NODE, 0)] = _table("d1")
        executor = _executor(plan=_plan())

        merged = executor._inject_resumed_documents(tables=_table("fresh"))

        assert merged.column("id").to_pylist() == ["fresh", "d1"]
        assert executor.resumption_injection_pending() is True

    def test_target_node_with_empty_input_still_gets_documents(self, store, reader):
        reader.tables[(RUN_ID, SOURCE_NODE, 0)] = _table("d1")
        executor = _executor(plan=_plan())

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

    def test_missing_saved_output_is_reported_unavailable(self, store):
        executor = _executor(plan=_plan())

        executor._inject_resumed_documents(tables=_table("fresh"))

        assert [e["doc_id"] for e in executor._unavailable_resumed_entries] == ["d1"]

    def test_document_failed_in_two_branches_is_injected_at_each_target(self, store, reader):
        reader.tables[(RUN_ID, SOURCE_NODE, 0)] = _table("d1")
        plan = _plan(_entry(target="branch-a", pending=()), _entry(target="branch-b", pending=()))

        node_a = _executor(node_id="branch-a", plan=plan)
        node_b = _executor(node_id="branch-b", plan=plan)

        assert node_a._inject_resumed_documents(tables=_table()).column("id").to_pylist() == ["d1"]
        assert node_b._inject_resumed_documents(tables=_table()).column("id").to_pylist() == ["d1"]


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

    def test_target_node_has_no_deferred_documents(self, store, reader):
        reader.tables[(RUN_ID, SOURCE_NODE, 0)] = _table("d1")
        executor = _executor(plan=_plan())
        executor._inject_resumed_documents(tables=_table("f1"))
        metadata = {Metrics.External.TOTAL_DOCS: 2}

        executor._apply_resumption_to_metadata(metadata=metadata)

        assert Metrics.External.DEFERRED_EXECUTION_DOCS not in metadata
        assert metadata[Metrics.External.TOTAL_DOCS] == 2

    def test_unavailable_saved_output_becomes_failed_document_with_original_error(self, store, monkeypatch):
        record_failed = Mock()
        monkeypatch.setattr(
            "docpipe.core.orchestration.abstract_operator_executor.AbstractOperator.record_failed_document",
            record_failed,
        )
        executor = _executor(plan=_plan())
        executor._inject_resumed_documents(tables=_table("f1"))
        metadata = {Metrics.External.TOTAL_DOCS: 1, Metrics.External.FAILED_DOCS_COUNT: 0}

        executor._apply_resumption_to_metadata(metadata=metadata)

        record_failed.assert_called_once()
        assert record_failed.call_args.kwargs["doc_id"] == "d1"
        reason = record_failed.call_args.kwargs["reason"]
        assert RUN_ID in reason
        assert "original failure" in reason
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


class TestResumedSuccess:
    def _resumed(self, store, reader) -> _Executor:
        reader.tables[(RUN_ID, SOURCE_NODE, 0)] = _table("d1")
        executor = _executor(plan=_plan())
        executor._inject_resumed_documents(tables=_table("f1"))
        return executor

    @staticmethod
    def _record_failures(store, *node_ids: str) -> None:
        service = ResumptionService(store=store, max_retry_attempts=3)
        for node_id in node_ids:
            service.record_failure(
                job_id=JOB_ID,
                job_run_id=RUN_ID,
                node_id=node_id,
                node_name=node_id,
                input_table=_table("d1"),
                doc_id="d1",
                doc_name="d1.pdf",
                reason="original failure",
            )

    def test_success_at_target_clears_only_this_nodes_failure(self, store, reader):
        self._record_failures(store, NODE_ID, "other-branch")
        executor = self._resumed(store, reader)

        executor._apply_resumption_to_metadata(metadata={Metrics.External.TOTAL_DOCS: 2})

        record = store.get_record(job_id=JOB_ID, doc_id="d1")
        assert [n.node_id for n in record.failed_nodes] == ["other-branch"]

    def test_success_at_only_failed_node_deletes_record(self, store, reader):
        self._record_failures(store, NODE_ID)
        executor = self._resumed(store, reader)

        executor._apply_resumption_to_metadata(metadata={Metrics.External.TOTAL_DOCS: 2})

        assert store.get_record(job_id=JOB_ID, doc_id="d1") is None

    def test_repeated_failure_is_counted_not_cleared(self, store, reader):
        self._record_failures(store, NODE_ID)
        executor = self._resumed(store, reader)
        executor._resumption_input = _table("f1", "d1")
        metadata = {
            Metrics.External.TOTAL_DOCS: 2,
            Metrics.External.FAILED_DOCS: [{"id": "d1", "name": "d1.pdf", "reason": "again"}],
        }

        executor._apply_resumption_to_metadata(metadata=metadata)

        node = store.get_record(job_id=JOB_ID, doc_id="d1").failed_node(node_id=NODE_ID)
        assert node.failure_count == 2
        assert node.job_run_id == RUN_ID
        assert node.error_message == "again"


class TestFailureCapture:
    @staticmethod
    def _executor_with_input(store, *docs: str) -> _Executor:
        executor = _executor(plan=None)
        executor._resumption_input = _table(*docs)
        return executor

    def test_failed_documents_are_recorded_with_run_and_error(self, store):
        executor = self._executor_with_input(store, "d1", "d2")
        metadata = {Metrics.External.FAILED_DOCS: [{"id": "d1", "name": "d1.pdf", "reason": "oops"}]}

        executor._record_failures_from_metadata(metadata=metadata)

        node = store.get_record(job_id=JOB_ID, doc_id="d1").failed_node(node_id=NODE_ID)
        assert node.failure_count == 1
        assert node.job_run_id == "run-2"
        assert node.error_message == "oops"
        assert store.get_record(job_id=JOB_ID, doc_id="d2") is None

    def test_non_recoverable_documents_are_not_recorded(self, store):
        executor = self._executor_with_input(store, "d1")
        metadata = {
            Metrics.External.FAILED_DOCS: [{"id": "d1", "name": "d1.pdf", "reason": "corrupt"}],
            Metrics.Internal.NON_RECOVERABLE_DOCS_TABLE: _table("d1"),
        }

        executor._record_failures_from_metadata(metadata=metadata)

        assert store.get_record(job_id=JOB_ID, doc_id="d1") is None

    def test_exhausted_reason_contains_original_error_and_is_persisted_non_recoverable(self, store, monkeypatch):
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
        assert "oops" in failed["reason"]
        assert saved.call_count == 1
        persisted = saved.call_args.kwargs["tables"][0]
        assert persisted.column("id").to_pylist() == ["d1"]
        assert store.get_record(job_id=JOB_ID, doc_id="d1").exhausted is True

    def test_node_exception_records_every_input_document(self, store):
        executor = self._executor_with_input(store, "d1", "d2")

        executor._record_node_failure(exc=RuntimeError("node down"))

        node = store.get_record(job_id=JOB_ID, doc_id="d1").failed_node(node_id=NODE_ID)
        assert node.error_message.startswith("RuntimeError")
        assert store.get_record(job_id=JOB_ID, doc_id="d2") is not None

    def test_failures_at_two_nodes_are_both_kept(self, store):
        first = self._executor_with_input(store, "d1")
        second = _executor(node_id="node-9", plan=None, name="embeddings")
        second._resumption_input = _table("d1")

        first._record_failures_from_metadata(metadata={Metrics.External.FAILED_DOCS: [{"id": "d1", "reason": "a"}]})
        second._record_failures_from_metadata(metadata={Metrics.External.FAILED_DOCS: [{"id": "d1", "reason": "b"}]})

        record = store.get_record(job_id=JOB_ID, doc_id="d1")
        assert {n.node_id: n.error_message for n in record.failed_nodes} == {NODE_ID: "a", "node-9": "b"}

    def test_failure_capture_is_inactive_without_resumption(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "docpipe.core.orchestration.abstract_operator_executor.create_resumption_service", lambda *, config: None
        )
        executor = _executor(plan=None)
        executor._resumption_input = _table("d1")

        executor._record_failures_from_metadata(metadata={Metrics.External.FAILED_DOCS: [{"id": "d1"}]})
        executor._record_node_failure(exc=RuntimeError("x"))
