# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
Integration test for node-level resumption of failed documents.

Flow: ingest_source -> noop -> noop2

Run 1: the second node raises, so every document fails at that node.
Run 2 (same job_id): the documents resume at the failing node with the saved
output of the first node as input, instead of being re-ingested.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

_FIXTURES_DIR = Path(__file__).parents[2] / "fixtures" / "customer_support_docs"
_FAILING_NODE_NAME = "failing_node"
# The failing node is identified by this distinctive sleep_sec value.
_FAILING_MARKER = 2


def _make_flow(*, docs_path: str, job_id: str, max_retry_attempts: int) -> dict:
    return {
        "flow_name": "integration-node-level-resumption",
        "flow_id": str(uuid.uuid4()),
        "job_id": job_id,
        "global_config": {
            "doc_column": "content",
            "data_storage_type": "local",
            "enable_micro_batching": False,
            "max_retry_attempts": max_retry_attempts,
        },
        "flow": [
            {
                "type": "ingest_source",
                "name": "ingest",
                "config": {
                    "provider": "filesystem",
                    "provider_config": {"paths": [docs_path]},
                    "include_filter": "txt",
                    "max_files": 3,
                },
            },
            {"type": "noop", "name": "first_node", "depends_on": ["ingest"], "config": {"sleep_sec": 0}},
            {
                "type": "noop",
                "name": _FAILING_NODE_NAME,
                "depends_on": ["first_node"],
                "config": {"sleep_sec": _FAILING_MARKER},
            },
        ],
    }


@pytest.mark.integration
class TestNodeLevelResumption:
    @pytest.fixture(autouse=True)
    def _isolated_storage(self, tmp_path, monkeypatch):
        if not _FIXTURES_DIR.exists():
            pytest.skip(f"Fixture directory not found: {_FIXTURES_DIR}")
        monkeypatch.setenv("DOCPIPE_DATA_PATH", str(tmp_path / "data"))
        monkeypatch.chdir(tmp_path)

    @staticmethod
    def _patch_noop(*, monkeypatch, fail: dict) -> None:
        from docpipe.core.operators.functional.noop import NOOPOperator

        original_transform = NOOPOperator.transform

        def _patched(self, table):
            is_failing_node = self.sleep == _FAILING_MARKER
            self.sleep = 0
            if is_failing_node and fail["enabled"]:
                msg = "simulated failure"
                raise RuntimeError(msg)
            return original_transform(self, table)

        monkeypatch.setattr(NOOPOperator, "transform", _patched)

    @staticmethod
    def _run(*, flow_def: dict, job_id: str) -> None:
        from docpipe.lib.docpipe_flow_manager import DocpipeFlowManager

        DocpipeFlowManager(
            flow_def=flow_def, job_id=job_id, enable_execution_reporter=False, configure_logging=False
        ).execute()

    def test_failed_documents_resume_at_failed_node(self, monkeypatch):
        from docpipe.core.orchestration.adapters.filesystem_resumption_store import FilesystemResumptionStore

        job_id = str(uuid.uuid4())
        fail = {"enabled": True}
        self._patch_noop(monkeypatch=monkeypatch, fail=fail)
        flow_def = _make_flow(docs_path=str(_FIXTURES_DIR), job_id=job_id, max_retry_attempts=3)

        # Run 1: the second noop node raises for the whole batch.
        with pytest.raises(Exception):  # noqa: B017
            self._run(flow_def=flow_def, job_id=job_id)

        records = FilesystemResumptionStore().get_all_records(job_id=job_id)
        assert records, "failed documents must have resumption records after run 1"
        assert all(record.failure_count == 1 for record in records.values())
        assert all(record.checkpoint_path for record in records.values())

        # Run 2: same job, failure cleared. Documents resume at the failed node.
        fail["enabled"] = False
        self._run(flow_def=flow_def, job_id=job_id)

        remaining = FilesystemResumptionStore().get_all_records(job_id=job_id)
        assert not remaining, "resumption state must be cleared after documents complete"

    def test_documents_are_exhausted_after_max_retries(self, monkeypatch):
        from docpipe.core.orchestration.adapters.filesystem_resumption_store import FilesystemResumptionStore

        job_id = str(uuid.uuid4())
        self._patch_noop(monkeypatch=monkeypatch, fail={"enabled": True})
        # max_retry_attempts=1 -> 1 initial attempt + 1 retry = 2 attempts.
        flow_def = _make_flow(docs_path=str(_FIXTURES_DIR), job_id=job_id, max_retry_attempts=1)
        store = FilesystemResumptionStore()

        with pytest.raises(Exception):  # noqa: B017
            self._run(flow_def=flow_def, job_id=job_id)
        first_run_ids = set(store.get_all_records(job_id=job_id))
        assert first_run_ids

        # Run 2 resumes the same documents at the failing node (max_files only caps fresh documents).
        with pytest.raises(Exception):  # noqa: B017
            self._run(flow_def=flow_def, job_id=job_id)

        records = store.get_all_records(job_id=job_id)
        for doc_id in first_run_ids:
            assert records[doc_id].exhausted
            assert records[doc_id].failure_count == 2
            assert records[doc_id].checkpoint_path, "checkpoints are retained for exhausted documents"
