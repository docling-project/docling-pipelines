# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for IngestSourceOperator deferred-document emission (node-level failure resumption)."""

import hashlib

import pyarrow as pa
import pytest
from langchain_core.documents import Document

from docpipe.core.constants.constants import DocpipeConstants, Metrics
from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator
from docpipe.core.orchestration.application.services.resumption_service import ResumptionService
from docpipe.storage.file_system.key_value_file_system_storage import KeyValueFileSystemStorage

JOB_ID = "job-ingest"
NODE_ID = "node-4"
MAX_RETRIES = 3


def _doc_id(source: str) -> str:
    return hashlib.md5(source.encode(), usedforsecurity=False).hexdigest()


def _document(source: str, last_modified: int) -> Document:
    return Document(
        page_content="x",
        metadata={"source": source, "name": source, "last_modified": last_modified, "extension": ".txt"},
    )


@pytest.fixture
def store(tmp_path):
    return KeyValueFileSystemStorage(base_dir=str(tmp_path))


@pytest.fixture
def service(store):
    return ResumptionService(record_storage=store, max_retry_attempts=MAX_RETRIES)


@pytest.fixture
def operator(service, tmp_path):
    op = IngestSourceOperator(
        {
            "provider": "filesystem",
            "provider_config": {"paths": [str(tmp_path)]},
            "max_files": 100,
            "job_id": JOB_ID,
            DocpipeConstants.DATA_STORAGE_TYPE: "local",
        }
    )
    op._resumption_service = service
    op.previously_processed_docs_dict = None
    return op


def _fail(
    service: ResumptionService,
    source: str,
    *,
    modified_time: int,
    times: int = 1,
    node_id: str = NODE_ID,
    node_name: str = "embeddings",
    job_run_id: str = "run-1",
):
    doc_id = _doc_id(source)
    table = pa.table({"id": [doc_id], "name": [source], "modified_time": pa.array([modified_time], type=pa.int64())})
    record = None
    for _ in range(times):
        record = service.record_failure(
            job_id=JOB_ID,
            job_run_id=job_run_id,
            node_id=node_id,
            node_name=node_name,
            input_table=table,
            doc_id=doc_id,
            doc_name=source,
            reason="timeout",
        )
    return record


def _metadata(operator: IngestSourceOperator) -> dict:
    return operator.create_base_metadata(total_docs_count=0)


class TestDeferredEmission:
    def test_unmodified_failed_document_is_deferred_not_emitted(self, operator, service):
        _fail(service, "a.txt", modified_time=100)
        metadata = _metadata(operator)

        row = operator.process_document(_document("a.txt", 100), 0, metadata)

        assert row is None
        assert [e["doc_id"] for e in operator._deferred_entries] == [_doc_id("a.txt")]
        assert operator._deferred_entries[0]["target_node_id"] == NODE_ID
        assert operator._deferred_entries[0]["job_run_id"] == "run-1"
        assert operator._deferred_entries[0]["error_message"] == "timeout"
        assert "checkpoint_path" not in operator._deferred_entries[0]
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 0
        assert metadata[Metrics.External.SKIPPED_DOCS_COUNT] == 0

    def test_document_failed_at_several_nodes_is_deferred_once_per_node(self, operator, service):
        _fail(service, "a.txt", modified_time=100, node_id="branch-a", node_name="name-a", job_run_id="run-1")
        _fail(service, "a.txt", modified_time=100, node_id="branch-b", node_name="name-b", job_run_id="run-2")
        metadata = _metadata(operator)

        row = operator.process_document(_document("a.txt", 100), 0, metadata)

        assert row is None
        entries = {e["target_node_id"]: e["job_run_id"] for e in operator._deferred_entries}
        assert entries == {"branch-a": "run-1", "branch-b": "run-2"}

    def test_modified_source_is_ingested_fresh(self, operator, service):
        _fail(service, "a.txt", modified_time=100)

        row = operator.process_document(_document("a.txt", 101), 0, _metadata(operator))

        assert row is not None
        assert row["id"] == _doc_id("a.txt")
        assert operator._deferred_entries == []

    def test_unknown_document_is_ingested_fresh(self, operator):
        row = operator.process_document(_document("new.txt", 5), 0, _metadata(operator))

        assert row is not None
        assert operator._deferred_entries == []

    def test_exhausted_document_is_reported_failed_and_not_deferred(self, operator, service):
        _fail(service, "a.txt", modified_time=100, times=MAX_RETRIES + 1)
        metadata = _metadata(operator)

        row = operator.process_document(_document("a.txt", 100), 0, metadata)

        assert row is None
        assert operator._deferred_entries == []
        assert metadata[Metrics.External.FAILED_DOCS_COUNT] == 1
        reason = metadata[Metrics.External.FAILED_DOCS][0]["reason"]
        assert "Maximum retries exhausted" in reason
        assert "timeout" in reason

    def test_force_ingest_bypasses_resumption(self, operator, service):
        _fail(service, "a.txt", modified_time=100)
        operator.force_ingest = True

        row = operator.process_document(_document("a.txt", 100), 0, _metadata(operator))

        assert row is not None
        assert operator._deferred_entries == []

    def test_resumption_inactive_without_service(self, operator, service):
        _fail(service, "a.txt", modified_time=100)
        operator._resumption_service = None

        row = operator.process_document(_document("a.txt", 100), 0, _metadata(operator))

        assert row is not None


class TestScopeAccounting:
    def _transform(self, operator, service, monkeypatch, *, fresh: int, deferred: int):
        for i in range(deferred):
            _fail(service, f"failed-{i}.txt", modified_time=100)
        docs = [_document(f"fresh-{i}.txt", 10) for i in range(fresh)]
        docs += [_document(f"failed-{i}.txt", 100) for i in range(deferred)]

        monkeypatch.setattr(operator, "_get_document_iterator", lambda: iter(docs))
        # Force the LangChain loader path instead of the registered filesystem adapter
        monkeypatch.setattr(
            "docpipe.core.operators.ingest.ingest_source.SourceAdapterFactory.is_registered", lambda _name: False
        )
        monkeypatch.setattr(operator, "_resumption_service", service, raising=False)
        # transform() recreates the service from config; keep the test service
        monkeypatch.setattr(
            "docpipe.core.operators.ingest.ingest_source.create_resumption_service", lambda *, config: service
        )
        monkeypatch.setattr(
            "docpipe.core.operators.ingest.ingest_source.get_incremental_update_service",
            lambda: type("S", (), {"get_all_processed_docs": staticmethod(lambda *, job_id: {})})(),
        )
        return operator.transform(None)

    def test_documents_in_scope_is_fresh_plus_deferred(self, operator, service, monkeypatch):
        tables, metadata = self._transform(operator, service, monkeypatch, fresh=10, deferred=2)

        assert tables[0].num_rows == 10
        assert metadata[Metrics.External.TOTAL_DOCS] == 12
        assert metadata[Metrics.External.PROCESSED_DOCS] == 10
        assert len(metadata[Metrics.External.DEFERRED_EXECUTION_DOCS]) == 2
        assert metadata[Metrics.External.DEFERRED_EXECUTION_DOCS_COUNT] == 2
        assert len(metadata[Metrics.Internal.DEFERRED_ENTRIES]) == 2

    def test_no_deferred_keys_when_nothing_deferred(self, operator, service, monkeypatch):
        _, metadata = self._transform(operator, service, monkeypatch, fresh=3, deferred=0)

        assert metadata[Metrics.External.TOTAL_DOCS] == 3
        assert Metrics.External.DEFERRED_EXECUTION_DOCS not in metadata
        assert Metrics.Internal.DEFERRED_ENTRIES not in metadata
