# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for node-level failure resumption (ResumptionService and FilesystemResumptionStore)."""

from typing import ClassVar

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.orchestration.adapters.filesystem_resumption_store import FilesystemResumptionStore
from docpipe.core.orchestration.adapters.resumption_factory import create_resumption_service
from docpipe.core.orchestration.application.services.resumption_service import (
    RETRIES_EXHAUSTED_PREFIX,
    ResumptionDecision,
    ResumptionService,
    resumption_batch_key,
)

JOB_ID = "job-1"
NODE_ID = "node-4"
MAX_RETRIES = 3


def _input_table(*doc_ids: str, modified_time: int = 100) -> pa.Table:
    return pa.table(
        {
            "id": list(doc_ids),
            "name": [f"{d}.pdf" for d in doc_ids],
            "modified_time": pa.array([modified_time] * len(doc_ids), type=pa.int64()),
            "content": [f"text-{d}" for d in doc_ids],
        }
    )


@pytest.fixture
def store(tmp_path):
    return FilesystemResumptionStore(root=str(tmp_path))


@pytest.fixture
def service(store):
    return ResumptionService(store=store, max_retry_attempts=MAX_RETRIES)


def _fail(
    service: ResumptionService,
    doc_id: str = "d1",
    *,
    node_id: str = NODE_ID,
    node_name: str = "chunker",
    modified_time: int = 100,
):
    return service.record_failure(
        job_id=JOB_ID,
        node_id=node_id,
        node_name=node_name,
        input_table=_input_table(doc_id, "other", modified_time=modified_time),
        doc_id=doc_id,
        doc_name="",
        reason="boom",
    )


class TestFilesystemResumptionStore:
    def test_checkpoint_roundtrip(self, store):
        path = store.write_checkpoint(job_id=JOB_ID, node_id=NODE_ID, doc_id="d1", table=_input_table("d1"))

        assert store.checkpoint_exists(job_id=JOB_ID, path=path)
        assert store.read_checkpoint(job_id=JOB_ID, path=path).num_rows == 1
        store.delete_checkpoint(job_id=JOB_ID, path=path)
        assert not store.checkpoint_exists(job_id=JOB_ID, path=path)

    def test_path_traversal_is_rejected(self, store):
        assert store.read_checkpoint(job_id=JOB_ID, path="../../etc/passwd") is None
        assert not store.checkpoint_exists(job_id=JOB_ID, path="../../etc/passwd")

    @pytest.mark.parametrize("job_id", ["../escape", "a/b", "", ".."])
    def test_invalid_job_id_is_rejected(self, store, job_id):
        with pytest.raises(ValueError, match="Invalid job_id"):
            store.get_all_records(job_id=job_id)

    def test_unreadable_record_is_ignored(self, store, tmp_path):
        service = ResumptionService(store=store, max_retry_attempts=MAX_RETRIES)
        _fail(service)
        record_file = next((tmp_path / JOB_ID / "resumption" / "records").glob("*.json"))
        record_file.write_text("not json")

        assert store.get_all_records(job_id=JOB_ID) == {}
        assert store.get_record(job_id=JOB_ID, doc_id="d1") is None


class TestFailureCounting:
    def test_first_failure_writes_checkpoint_of_only_the_failed_row(self, service, store):
        record = _fail(service)

        assert record.failure_count == 1
        assert record.exhausted is False
        assert record.modified_time == 100
        checkpoint = store.read_checkpoint(job_id=JOB_ID, path=record.checkpoint_path)
        assert checkpoint.column("id").to_pylist() == ["d1"]

    def test_consecutive_failures_at_same_node_accumulate(self, service):
        counts = [_fail(service).failure_count for _ in range(3)]

        assert counts == [1, 2, 3]

    def test_failure_at_different_node_resets_counter(self, service):
        _fail(service)
        _fail(service)

        assert _fail(service, node_id="node-5", node_name="embed").failure_count == 1

    def test_third_failure_is_still_within_threshold(self, service):
        # 1 initial attempt + 2 retries failed -> 3rd retry (4th attempt) is still allowed
        for _ in range(3):
            record = _fail(service)

        assert record.exhausted is False
        decision, _ = service.classify(job_id=JOB_ID, doc_id="d1", modified_time=100)
        assert decision == ResumptionDecision.DEFER

    def test_fourth_failure_exhausts_retries(self, service):
        # 1 initial attempt + 3 retries = 4 consecutive failures > max_retry_attempts
        for _ in range(4):
            record = _fail(service)

        assert record.exhausted is True
        decision, stored = service.classify(job_id=JOB_ID, doc_id="d1", modified_time=100)
        assert decision == ResumptionDecision.EXHAUSTED
        assert stored.failure_count == 4

    def test_exhausted_checkpoint_is_retained(self, service, store):
        for _ in range(4):
            record = _fail(service)

        assert store.checkpoint_exists(job_id=JOB_ID, path=record.checkpoint_path)

    def test_document_missing_from_input_is_not_recorded(self, service):
        record = service.record_failure(
            job_id=JOB_ID,
            node_id=NODE_ID,
            node_name="chunker",
            input_table=_input_table("other"),
            doc_id="d1",
            doc_name="",
            reason="x",
        )

        assert record is None

    def test_exhausted_reason_names_node_and_error(self, service):
        for _ in range(4):
            record = _fail(service)

        reason = service.format_exhausted_reason(record=record)

        assert reason.startswith(RETRIES_EXHAUSTED_PREFIX)
        assert "chunker" in reason
        assert "boom" in reason

    def test_zero_retries_exhausts_on_first_failure(self, store):
        service = ResumptionService(store=store, max_retry_attempts=0)

        assert _fail(service).exhausted is True


class TestClassify:
    def test_unknown_document_is_fresh(self, service):
        decision, record = service.classify(job_id=JOB_ID, doc_id="new", modified_time=1)

        assert (decision, record) == (ResumptionDecision.FRESH, None)

    def test_unmodified_source_is_deferred(self, service):
        _fail(service, modified_time=100)

        decision, record = service.classify(job_id=JOB_ID, doc_id="d1", modified_time=100)

        assert decision == ResumptionDecision.DEFER
        assert record.failed_node_id == NODE_ID

    def test_newer_source_invalidates_checkpoint(self, service, store):
        record = _fail(service, modified_time=100)

        decision, stored = service.classify(job_id=JOB_ID, doc_id="d1", modified_time=101)

        assert (decision, stored) == (ResumptionDecision.FRESH, None)
        assert not store.checkpoint_exists(job_id=JOB_ID, path=record.checkpoint_path)
        assert store.get_record(job_id=JOB_ID, doc_id="d1") is None

    def test_older_source_does_not_invalidate(self, service):
        _fail(service, modified_time=100)

        decision, _ = service.classify(job_id=JOB_ID, doc_id="d1", modified_time=99)

        assert decision == ResumptionDecision.DEFER

    def test_missing_checkpoint_falls_back_to_root_ingestion(self, service, store):
        record = _fail(service)
        store.delete_checkpoint(job_id=JOB_ID, path=record.checkpoint_path)

        decision, stored = service.classify(job_id=JOB_ID, doc_id="d1", modified_time=100)

        assert (decision, stored) == (ResumptionDecision.FRESH, None)
        assert store.get_record(job_id=JOB_ID, doc_id="d1") is None

    def test_newer_source_invalidates_even_exhausted_document(self, service):
        for _ in range(4):
            _fail(service, modified_time=100)

        decision, _ = service.classify(job_id=JOB_ID, doc_id="d1", modified_time=200)

        assert decision == ResumptionDecision.FRESH


class TestPlanning:
    NODES: ClassVar[list] = ["ingest", "extract", "chunker", "embed", "vdb"]

    def _entry(self, doc_id: str, target: str) -> dict:
        return {"doc_id": doc_id, "target_node_id": target, "checkpoint_path": f"c/{doc_id}"}

    def test_plan_marks_ancestors_as_pending(self):
        plan, unresolved = ResumptionService.build_plan(
            entries=[self._entry("d1", "embed")], node_ids=self.NODES, batch_keys=["b0"]
        )

        assert unresolved == []
        assert plan["b0"][0]["pending_node_ids"] == ["extract", "chunker"]

    def test_entries_are_spread_across_batches(self):
        entries = [self._entry(f"d{i}", "embed") for i in range(5)]

        plan, _ = ResumptionService.build_plan(entries=entries, node_ids=self.NODES, batch_keys=["b0", "b1"])

        assert [len(plan["b0"]), len(plan["b1"])] == [3, 2]

    def test_unknown_or_ingest_target_is_unresolved(self):
        entries = [self._entry("d1", "ghost"), self._entry("d2", "ingest")]

        plan, unresolved = ResumptionService.build_plan(entries=entries, node_ids=self.NODES, batch_keys=["b0"])

        assert plan == {}
        assert {e["doc_id"] for e in unresolved} == {"d1", "d2"}

    def test_target_node_is_remapped_by_name_when_ids_change_between_runs(self):
        entry = {**self._entry("d1", "old-embed-id"), "target_node_name": "embed"}

        plan, unresolved = ResumptionService.build_plan(
            entries=[entry], node_ids=self.NODES, batch_keys=["b0"], node_names=self.NODES
        )

        assert unresolved == []
        assert plan["b0"][0]["target_node_id"] == "embed"
        assert plan["b0"][0]["pending_node_ids"] == ["extract", "chunker"]

    def test_entries_for_node_splits_inject_and_carry(self):
        plan, _ = ResumptionService.build_plan(
            entries=[self._entry("d1", "embed")], node_ids=self.NODES, batch_keys=["b0"]
        )

        inject_mid, carried_mid = ResumptionService.entries_for_node(plan=plan, batch_id="b0", node_id="chunker")
        inject_target, carried_target = ResumptionService.entries_for_node(plan=plan, batch_id="b0", node_id="embed")

        assert (inject_mid, [e["doc_id"] for e in carried_mid]) == ([], ["d1"])
        assert ([e["doc_id"] for e in inject_target], carried_target) == (["d1"], [])

    def test_entries_for_node_without_plan_or_batch(self):
        assert ResumptionService.entries_for_node(plan=None, batch_id=None, node_id="x") == ([], [])
        assert ResumptionService.entries_for_node(plan={"b0": []}, batch_id="other", node_id="x") == ([], [])

    def test_batch_key_for_non_batched_run(self):
        assert resumption_batch_key(batch_id=None) == resumption_batch_key(batch_id="")
        assert resumption_batch_key(batch_id="abc") == "abc"


class TestInjection:
    def test_checkpoint_rows_are_appended_to_input(self, service):
        record = _fail(service)
        entries = [{"doc_id": "d1", "checkpoint_path": record.checkpoint_path}]

        merged, injected, unavailable = service.inject_checkpoints(
            job_id=JOB_ID, table=_input_table("fresh"), entries=entries
        )

        assert merged.column("id").to_pylist() == ["fresh", "d1"]
        assert injected == ["d1"]
        assert unavailable == []

    def test_injection_into_empty_input(self, service):
        record = _fail(service)
        entries = [{"doc_id": "d1", "checkpoint_path": record.checkpoint_path}]

        merged, injected, _ = service.inject_checkpoints(job_id=JOB_ID, table=_input_table(), entries=entries)

        assert merged.column("id").to_pylist() == ["d1"]
        assert injected == ["d1"]

    def test_missing_checkpoint_is_reported_unavailable(self, service):
        entries = [{"doc_id": "d1", "checkpoint_path": "checkpoints/x/y.parquet"}]
        base = _input_table("fresh")

        merged, injected, unavailable = service.inject_checkpoints(job_id=JOB_ID, table=base, entries=entries)

        assert merged is base
        assert injected == []
        assert [e["doc_id"] for e in unavailable] == ["d1"]


class TestCompletion:
    def test_completed_document_state_is_cleared(self, service, store):
        record = _fail(service)

        service.clear_completed(job_id=JOB_ID, doc_ids=["d1"])

        assert store.get_record(job_id=JOB_ID, doc_id="d1") is None
        assert not store.checkpoint_exists(job_id=JOB_ID, path=record.checkpoint_path)

    def test_exhausted_state_survives_completion_sweep(self, service, store):
        for _ in range(4):
            record = _fail(service)

        service.clear_completed(job_id=JOB_ID, doc_ids=["d1"])

        assert store.get_record(job_id=JOB_ID, doc_id="d1") is not None
        assert store.checkpoint_exists(job_id=JOB_ID, path=record.checkpoint_path)

    def test_discard_all_removes_everything(self, service, store):
        for _ in range(4):
            record = _fail(service)

        service.discard_all(job_id=JOB_ID)

        assert store.get_all_records(job_id=JOB_ID) == {}
        assert not store.checkpoint_exists(job_id=JOB_ID, path=record.checkpoint_path)


class TestFactory:
    def test_disabled_without_local_storage(self):
        assert create_resumption_service(config={DocpipeConstants.DATA_STORAGE_TYPE: "memory"}) is None
        assert create_resumption_service(config={}) is None

    def test_enabled_with_local_storage_and_default_retries(self):
        service = create_resumption_service(config={DocpipeConstants.DATA_STORAGE_TYPE: "local"})

        assert service.max_retry_attempts == DocpipeConstants.DEFAULT_MAX_RETRY_ATTEMPTS

    def test_max_retry_attempts_is_configurable(self):
        service = create_resumption_service(
            config={DocpipeConstants.DATA_STORAGE_TYPE: "local", DocpipeConstants.MAX_RETRY_ATTEMPTS: 5}
        )

        assert service.max_retry_attempts == 5


class TestFailureCountAcrossRuns:
    def test_same_node_name_with_new_node_id_keeps_counting(self, tmp_path):
        service = ResumptionService(store=FilesystemResumptionStore(root=str(tmp_path)), max_retry_attempts=3)
        _fail(service, node_id="run-1-id")

        assert _fail(service, node_id="run-2-id").failure_count == 2
