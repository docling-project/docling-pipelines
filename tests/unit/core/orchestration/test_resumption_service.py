# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for node-level failure resumption (ResumptionService on key-value and table storages)."""

import hashlib
from typing import ClassVar

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.orchestration.adapters.resumption_factory import create_resumption_service
from docpipe.core.orchestration.application.services.resumption_service import (
    RETRIES_EXHAUSTED_PREFIX,
    ResumptionDecision,
    ResumptionService,
    resumption_batch_key,
)
from docpipe.core.orchestration.models.resumption_plan import FailedNode, ResumptionRecord
from docpipe.storage.file_system.key_value_file_system_storage import KeyValueFileSystemStorage
from docpipe.storage.file_system.table_file_system_storage import TableFileSystemStorage

JOB_ID = "job-1"
RUN_ID = "run-1"
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


COLLECTION = f"{JOB_ID}/resumption"


@pytest.fixture
def store(tmp_path):
    return KeyValueFileSystemStorage(base_dir=str(tmp_path))


@pytest.fixture
def service(store):
    return ResumptionService(record_storage=store, max_retry_attempts=MAX_RETRIES)


def _stored(store, doc_id: str) -> ResumptionRecord | None:
    """Read the record of a document straight from the key-value storage."""
    data = store.get_record(collection=COLLECTION, key=hashlib.sha256(doc_id.encode()).hexdigest())
    return ResumptionRecord.model_validate(data) if data is not None else None


def _existing(store, doc_id: str) -> ResumptionRecord:
    """Like ``_stored`` but fails the test when the record is absent."""
    record = _stored(store, doc_id)
    assert record is not None
    return record


def _stored_ids(store) -> set[str]:
    return {data["doc_id"] for data in store.list_records(collection=COLLECTION)}


def _fail(
    service: ResumptionService,
    doc_id: str = "d1",
    *,
    node_id: str = NODE_ID,
    node_name: str = "chunker",
    job_run_id: str = RUN_ID,
    modified_time: int = 100,
    reason: str = "boom",
    batch_num: int | None = None,
):
    return service.record_failure(
        job_id=JOB_ID,
        job_run_id=job_run_id,
        node_id=node_id,
        node_name=node_name,
        input_table=_input_table(doc_id, "other", modified_time=modified_time),
        doc_id=doc_id,
        doc_name="",
        reason=reason,
        batch_num=batch_num,
    )


class TestRecordStorage:
    @pytest.mark.parametrize("job_id", ["../escape", "a/b", "", ".."])
    def test_invalid_job_id_is_rejected(self, service, job_id):
        with pytest.raises(ValueError, match="Invalid job_id"):
            service.discard_all(job_id=job_id)

    def test_unreadable_record_is_ignored(self, service, tmp_path):
        _fail(service)
        record_file = next((tmp_path / COLLECTION).glob("*.json"))
        record_file.write_text("not json")

        assert service.classify(job_id=JOB_ID, doc_id="d1", modified_time=100)[0] == ResumptionDecision.FRESH

    def test_only_records_are_persisted(self, service, tmp_path):
        _fail(service)

        files = [p for p in (tmp_path / JOB_ID).rglob("*") if p.is_file()]

        assert [p.parent.name for p in files] == ["resumption"]
        assert all(p.suffix == ".json" for p in files)


class TestFailureCounting:
    def test_first_failure_stores_job_run_and_original_error(self, service):
        record = _fail(service, reason="parser exploded")

        node = record.failed_node(node_id=NODE_ID)
        assert (node.failure_count, node.exhausted) == (1, False)
        assert node.job_run_id == RUN_ID
        assert node.error_message == "parser exploded"
        assert record.modified_time == 100

    def test_record_does_not_carry_a_checkpoint_path(self):
        assert "checkpoint_path" not in ResumptionRecord.model_fields
        assert "checkpoint_path" not in FailedNode.model_fields

    def test_consecutive_failures_at_same_node_accumulate(self, service):
        counts = [_fail(service).failed_node(node_id=NODE_ID).failure_count for _ in range(3)]

        assert counts == [1, 2, 3]

    def test_repeated_failure_keeps_first_job_run_and_latest_error(self, service):
        _fail(service, job_run_id="run-1", reason="first")
        record = _fail(service, job_run_id="run-2", reason="second")

        node = record.failed_node(node_id=NODE_ID)
        assert node.job_run_id == "run-1"
        assert node.error_message == "second"

    def test_batch_num_is_stored_and_kept_from_first_failure(self, service):
        first = _fail(service, job_run_id="run-1", batch_num=3)
        assert first.failed_node(node_id=NODE_ID).batch_num == 3

        record = _fail(service, job_run_id="run-2", batch_num=7)

        assert record.failed_node(node_id=NODE_ID).batch_num == 3

    def test_batch_num_defaults_to_none_without_micro_batching(self, service):
        assert _fail(service).failed_node(node_id=NODE_ID).batch_num is None

    def test_batch_num_is_part_of_the_deferred_record(self, service):
        record = _fail(service, batch_num=2)

        (deferred,) = ResumptionService.to_deferred_records(record=record)

        assert (deferred.job_run_id, deferred.batch_num) == (RUN_ID, 2)

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
        assert stored.failed_node(node_id=NODE_ID).failure_count == 4

    def test_document_missing_from_input_is_not_recorded(self, service):
        record = service.record_failure(
            job_id=JOB_ID,
            job_run_id=RUN_ID,
            node_id=NODE_ID,
            node_name="chunker",
            input_table=_input_table("other"),
            doc_id="d1",
            doc_name="",
            reason="x",
        )

        assert record is None

    def test_exhausted_reason_names_node_and_original_error(self, service):
        for _ in range(4):
            record = _fail(service, reason="original failure text")

        reason = service.format_exhausted_reason(record=record)

        assert reason.startswith(RETRIES_EXHAUSTED_PREFIX)
        assert "chunker" in reason
        assert "original failure text" in reason

    def test_zero_retries_exhausts_on_first_failure(self, store):
        service = ResumptionService(record_storage=store, max_retry_attempts=0)

        assert _fail(service).exhausted is True

    def test_same_node_name_with_new_node_id_keeps_counting(self, service):
        _fail(service, node_id="run-1-id")

        record = _fail(service, node_id="run-2-id")

        assert len(record.failed_nodes) == 1
        assert record.failed_node(node_id="run-2-id").failure_count == 2

    def test_different_node_ids_and_names_are_counted_separately(self, service):
        _fail(service, node_id="run-1-id", node_name="chunker")

        record = _fail(service, node_id="run-2-id", node_name="embed")

        assert record.failed_node(node_id="run-2-id", node_name="embed").failure_count == 1


class TestMultipleFailedNodes:
    def test_failures_at_different_nodes_are_all_stored(self, service, store):
        _fail(service, node_id="branch-a", node_name="chunker_a", reason="err a")
        _fail(service, node_id="branch-b", node_name="chunker_b", job_run_id="run-2", reason="err b")

        record = _existing(store, "d1")

        assert {n.node_id for n in record.failed_nodes} == {"branch-a", "branch-b"}
        assert record.failed_node(node_id="branch-a").error_message == "err a"
        assert record.failed_node(node_id="branch-b").job_run_id == "run-2"

    def test_failure_at_another_node_does_not_reset_counter(self, service):
        _fail(service, node_id="branch-a", node_name="name-a")
        _fail(service, node_id="branch-a", node_name="name-a")

        record = _fail(service, node_id="branch-b", node_name="name-b")

        assert record.failed_node(node_id="branch-a").failure_count == 2
        assert record.failed_node(node_id="branch-b").failure_count == 1

    def test_one_deferred_record_per_failed_node(self, service):
        _fail(service, node_id="branch-a", node_name="name-a", reason="err a")
        record = _fail(service, node_id="branch-b", node_name="name-b", job_run_id="run-2", reason="err b")

        deferred = ResumptionService.to_deferred_records(record=record)

        assert {(d.target_node_id, d.job_run_id, d.error_message) for d in deferred} == {
            ("branch-a", RUN_ID, "err a"),
            ("branch-b", "run-2", "err b"),
        }

    def test_exhausted_at_any_node_exhausts_document(self, service):
        for _ in range(4):
            _fail(service, node_id="branch-a", node_name="name-a")
        _fail(service, node_id="branch-b", node_name="name-b")

        decision, record = service.classify(job_id=JOB_ID, doc_id="d1", modified_time=100)

        assert decision == ResumptionDecision.EXHAUSTED
        reason = service.format_exhausted_reason(record=record)
        assert "name-a" in reason
        assert "name-b" not in reason
        assert reason.count(RETRIES_EXHAUSTED_PREFIX) == 1

    def test_success_at_one_node_keeps_the_other_failure(self, service, store):
        _fail(service, node_id="branch-a", node_name="name-a")
        _fail(service, node_id="branch-b", node_name="name-b")

        service.clear_node_success(job_id=JOB_ID, node_id="branch-a", node_name="name-a", doc_ids=["d1"])

        record = _existing(store, "d1")
        assert [n.node_id for n in record.failed_nodes] == ["branch-b"]

    def test_success_at_last_failed_node_deletes_record(self, service, store):
        _fail(service, node_id="branch-a", node_name="name-a")

        service.clear_node_success(job_id=JOB_ID, node_id="branch-a", node_name="name-a", doc_ids=["d1"])

        assert _stored(store, "d1") is None

    def test_exhausted_entry_survives_success_sweep(self, service, store):
        for _ in range(4):
            _fail(service)

        service.clear_node_success(job_id=JOB_ID, node_id=NODE_ID, doc_ids=["d1"])

        assert _stored(store, "d1") is not None

    def test_success_is_matched_by_name_when_node_id_changed(self, service, store):
        _fail(service, node_id="old-id", node_name="chunker")

        service.clear_node_success(job_id=JOB_ID, node_id="new-id", node_name="chunker", doc_ids=["d1"])

        assert _stored(store, "d1") is None

    def test_success_at_unrelated_node_changes_nothing(self, service, store):
        _fail(service)

        service.clear_node_success(job_id=JOB_ID, node_id="elsewhere", doc_ids=["d1", "unknown"])

        assert _stored(store, "d1") is not None


class TestClassify:
    def test_unknown_document_is_fresh(self, service):
        decision, record = service.classify(job_id=JOB_ID, doc_id="new", modified_time=1)

        assert (decision, record) == (ResumptionDecision.FRESH, None)

    def test_unmodified_source_is_deferred(self, service):
        _fail(service, modified_time=100)

        decision, record = service.classify(job_id=JOB_ID, doc_id="d1", modified_time=100)

        assert decision == ResumptionDecision.DEFER
        assert record.failed_nodes[0].node_id == NODE_ID

    def test_newer_source_invalidates_failure_state(self, service, store):
        _fail(service, modified_time=100)

        decision, stored = service.classify(job_id=JOB_ID, doc_id="d1", modified_time=101)

        assert (decision, stored) == (ResumptionDecision.FRESH, None)
        assert _stored(store, "d1") is None

    def test_older_source_does_not_invalidate(self, service):
        _fail(service, modified_time=100)

        decision, _ = service.classify(job_id=JOB_ID, doc_id="d1", modified_time=99)

        assert decision == ResumptionDecision.DEFER

    def test_newer_source_invalidates_even_exhausted_document(self, service):
        for _ in range(4):
            _fail(service, modified_time=100)

        decision, _ = service.classify(job_id=JOB_ID, doc_id="d1", modified_time=200)

        assert decision == ResumptionDecision.FRESH

    def test_record_without_failed_nodes_is_fresh(self, service, store):
        service._save_record(job_id=JOB_ID, record=ResumptionRecord(doc_id="d1"))

        decision, _ = service.classify(job_id=JOB_ID, doc_id="d1", modified_time=None)

        assert decision == ResumptionDecision.FRESH
        assert _stored(store, "d1") is None


def _node(node_id: str, *, parents: list[str] | None = None, operator: str = "noop", **extra) -> dict:
    node = {"id": node_id, "name": node_id, "operator": operator, **extra}
    if parents is not None:
        node["input_edges"] = [{"node_id_ref": p} for p in parents]
    return node


class TestPlanning:
    FLOW: ClassVar[list] = [_node(n) for n in ["ingest", "extract", "chunker", "embed", "vdb"]]

    @staticmethod
    def _entry(doc_id: str, target: str) -> dict:
        return {"doc_id": doc_id, "target_node_id": target, "job_run_id": RUN_ID}

    def test_plan_resolves_source_and_marks_ancestors_as_pending(self):
        plan, unresolved = ResumptionService.build_plan(
            entries=[self._entry("d1", "embed")], op_flow=self.FLOW, batch_keys=["b0"]
        )

        assert unresolved == []
        entry = plan["b0"][0]
        assert entry["pending_node_ids"] == ["extract", "chunker"]
        assert entry["source_node_name"] == "chunker"
        assert entry["source_output_index"] == 0

    def test_entries_are_spread_across_batches(self):
        entries = [self._entry(f"d{i}", "embed") for i in range(5)]

        plan, _ = ResumptionService.build_plan(entries=entries, op_flow=self.FLOW, batch_keys=["b0", "b1"])

        assert [len(plan["b0"]), len(plan["b1"])] == [3, 2]

    def test_unknown_or_ingest_target_is_unresolved(self):
        entries = [self._entry("d1", "ghost"), self._entry("d2", "ingest")]

        plan, unresolved = ResumptionService.build_plan(entries=entries, op_flow=self.FLOW, batch_keys=["b0"])

        assert plan == {}
        assert {e["doc_id"] for e in unresolved} == {"d1", "d2"}

    def test_target_id_is_preferred_over_name(self):
        entry = {**self._entry("d1", "embed"), "target_node_name": "chunker"}

        plan, _ = ResumptionService.build_plan(entries=[entry], op_flow=self.FLOW, batch_keys=["b0"])

        assert plan["b0"][0]["target_node_id"] == "embed"

    def test_target_is_found_by_name_when_id_changed_between_runs(self):
        entry = {**self._entry("d1", "old-embed-id"), "target_node_name": "embed"}

        plan, unresolved = ResumptionService.build_plan(entries=[entry], op_flow=self.FLOW, batch_keys=["b0"])

        assert unresolved == []
        assert plan["b0"][0]["target_node_id"] == "embed"
        assert plan["b0"][0]["pending_node_ids"] == ["extract", "chunker"]

    def test_unknown_id_without_matching_name_is_unresolved(self):
        entry = {**self._entry("d1", "old-id"), "target_node_name": "ghost"}

        plan, unresolved = ResumptionService.build_plan(entries=[entry], op_flow=self.FLOW, batch_keys=["b0"])

        assert plan == {}
        assert unresolved == [entry]

    def test_ambiguous_node_name_is_unresolved(self):
        flow = [_node("ingest"), _node("a", name="dup"), _node("b", name="dup")]
        entry = {**self._entry("d1", "old-id"), "target_node_name": "dup"}

        plan, unresolved = ResumptionService.build_plan(entries=[entry], op_flow=flow, batch_keys=["b0"])

        assert plan == {}
        assert unresolved == [entry]

    def test_no_batches_leaves_everything_unresolved(self):
        entries = [self._entry("d1", "embed")]

        plan, unresolved = ResumptionService.build_plan(entries=entries, op_flow=self.FLOW, batch_keys=[])

        assert (plan, unresolved) == ({}, entries)

    def test_all_failed_nodes_of_a_document_go_to_the_same_batch(self):
        entries = [self._entry("d1", "chunker"), self._entry("d1", "embed"), self._entry("d2", "embed")]

        plan, unresolved = ResumptionService.build_plan(entries=entries, op_flow=self.FLOW, batch_keys=["b0", "b1"])

        assert unresolved == []
        assert [(e["doc_id"], e["target_node_id"]) for e in plan["b0"]] == [("d1", "chunker"), ("d1", "embed")]
        assert [e["doc_id"] for e in plan["b1"]] == ["d2"]

    def test_document_with_one_unresolvable_node_is_unresolved_entirely(self):
        entries = [self._entry("d1", "embed"), self._entry("d1", "ghost")]

        plan, unresolved = ResumptionService.build_plan(entries=entries, op_flow=self.FLOW, batch_keys=["b0"])

        assert plan == {}
        assert len(unresolved) == 2

    def test_dag_source_follows_input_edges_and_skips_sibling_branches(self):
        flow = [
            _node("ingest"),
            _node("extract", parents=["ingest"]),
            _node("branch_a", parents=["extract"]),
            _node("branch_b", parents=["extract"]),
            _node("embed_b", parents=["branch_b"]),
        ]

        plan, _ = ResumptionService.build_plan(entries=[self._entry("d1", "embed_b")], op_flow=flow, batch_keys=["b0"])

        entry = plan["b0"][0]
        assert entry["source_node_name"] == "branch_b"
        assert entry["pending_node_ids"] == ["extract", "branch_b"]

    def test_branching_output_index_comes_from_link_id(self):
        flow = [
            _node("ingest"),
            _node("extract", parents=["ingest"]),
            _node(
                "split",
                parents=["extract"],
                operator="branching",
                config={"branch_criteria": [{"link_id": "left"}, {"link_id": "right"}]},
            ),
            _node("after_left", parents=["split"], link_id="left"),
            _node("after_right", parents=["split"], link_id="right"),
        ]

        plan, unresolved = ResumptionService.build_plan(
            entries=[self._entry("d1", "after_right"), self._entry("d2", "after_left")],
            op_flow=flow,
            batch_keys=["b0"],
        )

        assert unresolved == []
        indexes = {e["target_node_id"]: e["source_output_index"] for e in plan["b0"]}
        assert indexes == {"after_right": 1, "after_left": 0}
        assert {e["source_node_name"] for e in plan["b0"]} == {"split"}

    def test_node_with_several_inputs_is_unresolved(self):
        flow = [
            _node("ingest"),
            _node("a", parents=["ingest"]),
            _node("b", parents=["ingest"]),
            _node("merge", parents=["a", "b"], operator="merge"),
        ]

        plan, unresolved = ResumptionService.build_plan(
            entries=[self._entry("d1", "merge")], op_flow=flow, batch_keys=["b0"]
        )

        assert plan == {}
        assert [e["doc_id"] for e in unresolved] == ["d1"]

    def test_entries_for_node_splits_inject_and_carry(self):
        plan, _ = ResumptionService.build_plan(
            entries=[self._entry("d1", "embed")], op_flow=self.FLOW, batch_keys=["b0"]
        )

        inject_mid, carried_mid = ResumptionService.entries_for_node(plan=plan, batch_id="b0", node_id="chunker")
        inject_target, carried_target = ResumptionService.entries_for_node(plan=plan, batch_id="b0", node_id="embed")

        assert (inject_mid, [e["doc_id"] for e in carried_mid]) == ([], ["d1"])
        assert ([e["doc_id"] for e in inject_target], carried_target) == (["d1"], [])

    def test_document_injected_at_a_node_is_not_carried_by_it(self):
        plan, _ = ResumptionService.build_plan(
            entries=[self._entry("d1", "chunker"), self._entry("d1", "embed")], op_flow=self.FLOW, batch_keys=["b0"]
        )

        inject, carried = ResumptionService.entries_for_node(plan=plan, batch_id="b0", node_id="chunker")

        assert [e["target_node_id"] for e in inject] == ["chunker"]
        assert carried == []

    def test_entries_for_node_without_plan_or_batch(self):
        assert ResumptionService.entries_for_node(plan=None, batch_id=None, node_id="x") == ([], [])
        assert ResumptionService.entries_for_node(plan={"b0": []}, batch_id="other", node_id="x") == ([], [])

    def test_batch_key_for_non_batched_run(self):
        assert resumption_batch_key(batch_id=None) == resumption_batch_key(batch_id="")
        assert resumption_batch_key(batch_id="abc") == "abc"


def _write_node_output(base, run_id: str, folder: str, table: pa.Table, *, batch: str | None = None) -> None:
    """Write a node output the way the executors save it: <base>/<job>/<run>/data/<node>_<idx>[/<batch>]."""
    target = base / JOB_ID / run_id / "data" / folder
    if batch:
        target = target / batch
    target.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, target / "output.parquet")


def _table_name(*, job_run_id: str, node_name: str, output_index: int, batch_num: int | None) -> str:
    folder = f"{JOB_ID}/{job_run_id}/data/{node_name}_{output_index}"
    return folder if batch_num is None else f"{folder}/{batch_num}"


class TestInjection:
    @staticmethod
    def _entry(
        doc_id: str, *, run: str = RUN_ID, node: str = "chunker", index: int = 0, batch_num: int | None = None
    ) -> dict:
        return {
            "doc_id": doc_id,
            "job_run_id": run,
            "source_node_name": node,
            "source_output_index": index,
            "batch_num": batch_num,
        }

    @staticmethod
    def _service(tmp_path, *, with_tables: bool = True) -> ResumptionService:
        return ResumptionService(
            record_storage=KeyValueFileSystemStorage(base_dir=str(tmp_path)),
            max_retry_attempts=MAX_RETRIES,
            table_storage=TableFileSystemStorage(base_dir=str(tmp_path)) if with_tables else None,
            output_table_name=_table_name if with_tables else None,
        )

    def test_saved_rows_are_appended_to_input(self, tmp_path):
        _write_node_output(tmp_path, RUN_ID, "chunker_0", _input_table("d1", "d2"))

        merged, injected, unavailable = self._service(tmp_path).inject_saved_rows(
            table=_input_table("fresh"), entries=[self._entry("d1")]
        )

        assert merged.column("id").to_pylist() == ["fresh", "d1"]
        assert (injected, unavailable) == (["d1"], [])

    def test_injection_into_empty_input(self, tmp_path):
        _write_node_output(tmp_path, RUN_ID, "chunker_0", _input_table("d1"))

        merged, injected, _ = self._service(tmp_path).inject_saved_rows(table=None, entries=[self._entry("d1")])

        assert merged.column("id").to_pylist() == ["d1"]
        assert injected == ["d1"]

    def test_rows_spread_over_batch_subfolders_are_found(self, tmp_path):
        _write_node_output(tmp_path, RUN_ID, "chunker_0", _input_table("d1"), batch="0")
        _write_node_output(tmp_path, RUN_ID, "chunker_0", _input_table("d2"), batch="1")

        merged, injected, unavailable = self._service(tmp_path).inject_saved_rows(
            table=None, entries=[self._entry("d1"), self._entry("d2")]
        )

        assert sorted(merged.column("id").to_pylist()) == ["d1", "d2"]
        assert (sorted(injected), unavailable) == (["d1", "d2"], [])

    def test_batch_num_selects_the_batch_folder_of_the_failed_run(self, tmp_path):
        # The same document id may sit in several batch folders (e.g. an earlier resumed copy); only the batch of the
        # failed run is read.
        _write_node_output(tmp_path, RUN_ID, "chunker_0", _input_table("d1", "other"), batch="0")
        _write_node_output(tmp_path, RUN_ID, "chunker_0", _input_table("d2"), batch="1")

        merged, injected, unavailable = self._service(tmp_path).inject_saved_rows(
            table=None, entries=[self._entry("d2", batch_num=1)]
        )

        assert merged.column("id").to_pylist() == ["d2"]
        assert (injected, unavailable) == (["d2"], [])

    def test_document_in_another_batch_is_unavailable(self, tmp_path):
        _write_node_output(tmp_path, RUN_ID, "chunker_0", _input_table("d1"), batch="0")

        _, injected, unavailable = self._service(tmp_path).inject_saved_rows(
            table=None, entries=[self._entry("d1", batch_num=1)]
        )

        assert injected == []
        assert [e["doc_id"] for e in unavailable] == ["d1"]

    def test_missing_output_is_reported_unavailable(self, tmp_path):
        base = _input_table("fresh")

        merged, injected, unavailable = self._service(tmp_path).inject_saved_rows(
            table=base, entries=[self._entry("d1")]
        )

        assert merged is base
        assert injected == []
        assert [e["doc_id"] for e in unavailable] == ["d1"]

    def test_unknown_document_is_reported_unavailable(self, tmp_path):
        _write_node_output(tmp_path, RUN_ID, "chunker_0", _input_table("d1"))

        _, injected, unavailable = self._service(tmp_path).inject_saved_rows(table=None, entries=[self._entry("zz")])

        assert injected == []
        assert [e["doc_id"] for e in unavailable] == ["zz"]

    def test_without_table_storage_everything_is_unavailable(self, tmp_path):
        entries = [self._entry("d1")]

        _, injected, unavailable = self._service(tmp_path, with_tables=False).inject_saved_rows(
            table=None, entries=entries
        )

        assert (injected, unavailable) == ([], entries)

    @pytest.mark.parametrize("run_id", ["../x", "a/b", "..", ""])
    def test_unsafe_job_run_id_is_unavailable(self, tmp_path, run_id):
        entries = [self._entry("d1", run=run_id)]

        _, injected, unavailable = self._service(tmp_path).inject_saved_rows(table=None, entries=entries)

        assert (injected, unavailable) == ([], entries)

    def test_entries_are_read_per_job_run_and_output(self, tmp_path):
        _write_node_output(tmp_path, "run-1", "chunker_0", _input_table("d1"))
        _write_node_output(tmp_path, "run-2", "split_1", _input_table("d2"))
        entries = [self._entry("d1", run="run-1"), self._entry("d2", run="run-2", node="split", index=1)]

        merged, injected, unavailable = self._service(tmp_path).inject_saved_rows(table=None, entries=entries)

        assert sorted(merged.column("id").to_pylist()) == ["d1", "d2"]
        assert sorted(injected) == ["d1", "d2"]
        assert unavailable == []

    def test_document_failed_at_two_nodes_is_injected_for_each_entry(self, tmp_path):
        _write_node_output(tmp_path, RUN_ID, "split_0", _input_table("d1"))
        _write_node_output(tmp_path, RUN_ID, "split_1", _input_table("d1"))
        entries = [self._entry("d1", node="split", index=0), self._entry("d1", node="split", index=1)]

        merged, injected, unavailable = self._service(tmp_path).inject_saved_rows(table=None, entries=entries)

        assert merged.num_rows == 2
        assert injected == ["d1", "d1"]
        assert unavailable == []


class TestDiscard:
    def test_discard_all_removes_everything(self, service, store):
        for _ in range(4):
            _fail(service)

        service.discard_all(job_id=JOB_ID)

        assert _stored_ids(store) == set()

    def test_discard_all_for_ids_only_removes_listed_documents(self, service, store):
        _fail(service, "d1")
        _fail(service, "d2")

        service.discard_all_for_ids(job_id=JOB_ID, doc_ids=["d1", "never-failed"])

        assert _stored_ids(store) == {"d2"}


class TestFactory:
    def test_disabled_for_memory_storage(self):
        assert create_resumption_service(config={DocpipeConstants.DATA_STORAGE_TYPE: "memory"}) is None
        assert create_resumption_service(config={}) is None

    def test_enabled_for_local_storage_with_default_retries(self):
        service = create_resumption_service(config={DocpipeConstants.DATA_STORAGE_TYPE: "local"})

        assert service.max_retry_attempts == DocpipeConstants.DEFAULT_MAX_RETRY_ATTEMPTS

    def test_output_table_name_includes_batch_num(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DOCPIPE_DATA_PATH", str(tmp_path))
        job_id, failed_run = "job-1", "run-failed"
        target = tmp_path / job_id / failed_run / "data" / "chunker_0" / "3"
        target.mkdir(parents=True)
        pq.write_table(_input_table("d1"), target / "output.parquet")
        other = tmp_path / job_id / failed_run / "data" / "chunker_0" / "0"
        other.mkdir(parents=True)
        pq.write_table(_input_table("d2"), other / "output.parquet")
        service = create_resumption_service(
            config={
                DocpipeConstants.DATA_STORAGE_TYPE: "local",
                DocpipeConstants.JOB_ID: job_id,
                DocpipeConstants.JOB_RUN_ID: "run-current",
            }
        )
        entry = {"job_run_id": failed_run, "source_node_name": "chunker", "source_output_index": 0}

        merged, injected, unavailable = service.inject_saved_rows(
            table=None, entries=[{**entry, "doc_id": "d1", "batch_num": 3}]
        )
        _, other_injected, other_unavailable = service.inject_saved_rows(
            table=None, entries=[{**entry, "doc_id": "d1", "batch_num": 0}]
        )

        assert (merged.column("id").to_pylist(), injected, unavailable) == (["d1"], ["d1"], [])
        assert other_injected == []
        assert [e["doc_id"] for e in other_unavailable] == ["d1"]

    def test_max_retry_attempts_is_configurable(self):
        service = create_resumption_service(
            config={DocpipeConstants.DATA_STORAGE_TYPE: "local", DocpipeConstants.MAX_RETRY_ATTEMPTS: 5}
        )

        assert service.max_retry_attempts == 5
