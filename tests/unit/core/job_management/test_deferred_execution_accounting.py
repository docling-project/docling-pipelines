# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Unit tests for deferred-execution accounting in aggregation, persistence and reporting."""

from typing import ClassVar
from unittest.mock import patch

import pytest

from docpipe.core.constants.constants import ExecutionStatus, Metrics
from docpipe.core.job_management.application.aggregation import MetadataAggregator, aggregate_batch_node_stats
from docpipe.core.job_management.application.aggregation.strategies import DEFAULT_STRATEGIES
from docpipe.core.job_management.application.services.report_generator import (
    RETRIES_EXHAUSTED_PREFIX,
    JobReportGenerator,
)
from docpipe.core.job_management.domain.models import JobStats, NodeStats

NODE_ID = "node-2"
INGEST_ID = "node-1"
DEST_ID = "node-4"


def _payload(inner: dict) -> dict:
    return {"id": NODE_ID, "operator": "Extract", "node_metadata": inner}


def _batch(num: int, **fields) -> NodeStats:
    return NodeStats(
        id=NODE_ID,
        name="Extract",
        node_status=ExecutionStatus.COMPLETED.value,
        batch_id=f"batch-{num}",
        batch_num=num,
        **fields,
    )


class TestNodeStatsModel:
    def test_defaults_to_empty_list(self):
        assert NodeStats(id="n", name="n").deferred_execution_docs == []

    def test_null_from_legacy_rows_is_normalised(self):
        assert NodeStats(id="n", name="n", deferred_execution_docs=None).deferred_execution_docs == []

    def test_roundtrips_through_json(self):
        stats = NodeStats(id="n", name="n", deferred_execution_docs=["a", "b"])

        assert NodeStats.model_validate_json(stats.model_dump_json()).deferred_execution_docs == ["a", "b"]


class TestMetadataStrategy:
    def test_deferred_docs_use_union(self):
        assert DEFAULT_STRATEGIES[Metrics.External.DEFERRED_EXECUTION_DOCS].value == "union"

    def test_union_deduplicates_across_batches(self):
        merged = MetadataAggregator().aggregate_metadata(
            metadata_list=[
                _payload({Metrics.External.DEFERRED_EXECUTION_DOCS: ["a", "b"]}),
                _payload({Metrics.External.DEFERRED_EXECUTION_DOCS: ["b", "c"]}),
            ]
        )

        assert merged["node_metadata"][Metrics.External.DEFERRED_EXECUTION_DOCS] == ["a", "b", "c"]


class TestBatchAggregation:
    def _aggregate(self, records: list[NodeStats]) -> NodeStats:
        return aggregate_batch_node_stats(node_id=NODE_ID, batch_records=records, aggregator=MetadataAggregator())

    def test_deferred_docs_are_unioned_and_reported(self):
        records = [
            _batch(0, total_docs=["f1", "d1"], docs_completed=["f1"], deferred_execution_docs=["d1"]),
            _batch(1, total_docs=["f2", "d2"], docs_completed=["f2"], deferred_execution_docs=["d2"]),
        ]

        result = self._aggregate(records)
        inner = result.node_metadata["node_metadata"]

        assert result.deferred_execution_docs == ["d1", "d2"]
        assert inner[Metrics.External.DEFERRED_EXECUTION_DOCS] == ["d1", "d2"]
        assert inner[Metrics.External.DEFERRED_EXECUTION_DOCS_COUNT] == 2

    def test_scope_equals_processed_plus_deferred(self):
        # 10 fresh + 2 deferred: total = processed + deferred + failed + skipped
        fresh = [f"f{i}" for i in range(10)]
        records = [
            _batch(0, total_docs=[*fresh, "d1", "d2"], docs_completed=fresh, deferred_execution_docs=["d1", "d2"])
        ]

        result = self._aggregate(records)
        inner = result.node_metadata["node_metadata"]

        assert inner[Metrics.External.TOTAL_DOCS] == 12
        assert inner[Metrics.External.PROCESSED_DOCS] == 10
        assert inner[Metrics.External.TOTAL_DOCS] == inner[Metrics.External.PROCESSED_DOCS] + inner[
            Metrics.External.DEFERRED_EXECUTION_DOCS_COUNT
        ] + len(result.failed_docs) + len(result.skipped_docs)

    def test_resumption_node_has_no_deferred_docs(self):
        fresh = [f"f{i}" for i in range(10)]
        records = [_batch(0, total_docs=[*fresh, "d1", "d2"], docs_completed=[*fresh, "d1", "d2"])]

        result = self._aggregate(records)
        inner = result.node_metadata["node_metadata"]

        assert inner[Metrics.External.PROCESSED_DOCS] == 12
        assert inner[Metrics.External.DEFERRED_EXECUTION_DOCS] == []
        assert inner[Metrics.External.DEFERRED_EXECUTION_DOCS_COUNT] == 0

    def test_document_resolved_in_another_record_is_no_longer_deferred(self):
        records = [
            _batch(0, total_docs=["d1"], deferred_execution_docs=["d1"]),
            _batch(1, total_docs=["d1"], docs_completed=["d1"]),
        ]

        assert self._aggregate(records).deferred_execution_docs == []


class TestReportGeneration:
    DAG: ClassVar[list] = [
        {"id": INGEST_ID, "name": "Ingest", "output_edges": [{"node_id_ref": DEST_ID}]},
        {"id": DEST_ID, "name": "VectorDB", "input_edges": [{"node_id_ref": INGEST_ID}], "output_edges": []},
    ]

    def _generator(self, node_stats: dict, node_metadata_list: list[dict]) -> JobReportGenerator:
        job_stats = JobStats(
            job_id="job",
            job_run_id="run",
            status=ExecutionStatus.COMPLETED_WITH_ERRORS,
            node_stats=node_stats,
        )
        return JobReportGenerator(job_stats=job_stats, dag_nodes=self.DAG, node_metadata_list=node_metadata_list)

    def _rows(self, generator: JobReportGenerator, ingest_docs: dict) -> dict[str, dict]:
        with patch.object(JobReportGenerator, "_read_parquet_file", return_value=ingest_docs):
            rows = generator.generate_report_data()
        return {row["File name"]: row for row in rows}

    def test_exhausted_document_reported_failed_with_exhaustion_reason(self):
        reason = f"{RETRIES_EXHAUSTED_PREFIX} (4 attempts, max_retry_attempts=3) at node 'embed': timeout"
        failed_meta = {"node_metadata": {"failed_docs": [{"id": "x1", "name": "x1.pdf", "reason": reason}]}}
        generator = self._generator(
            {
                INGEST_ID: NodeStats(id=INGEST_ID, name="Ingest", failed_docs=["x1"]),
                DEST_ID: NodeStats(id=DEST_ID, name="VectorDB", docs_completed=[]),
            },
            [failed_meta],
        )

        rows = self._rows(generator, {})

        assert rows["x1.pdf"]["Status"] == "Failed"
        assert rows["x1.pdf"]["Status reason"].startswith(RETRIES_EXHAUSTED_PREFIX)
        assert "embed" in rows["x1.pdf"]["Status reason"]

    def test_exhaustion_reason_wins_over_other_failure_reasons(self):
        exhausted = f"{RETRIES_EXHAUSTED_PREFIX} (4 attempts) at node 'embed': timeout"
        generator = self._generator(
            {INGEST_ID: NodeStats(id=INGEST_ID, name="Ingest", failed_docs=["x1"])},
            [
                {"node_metadata": {"failed_docs": [{"id": "x1", "reason": "generic"}]}},
                {"node_metadata": {"failed_docs": [{"id": "x1", "reason": exhausted}]}},
            ],
        )

        assert generator._find_failure_reason("x1") == exhausted

    def test_resumed_document_missing_from_ingest_output_is_reported_ingested(self):
        generator = self._generator(
            {
                INGEST_ID: NodeStats(id=INGEST_ID, name="Ingest", deferred_execution_docs=["d1"]),
                DEST_ID: NodeStats(id=DEST_ID, name="VectorDB", docs_completed=["f1", "d1"]),
            },
            [{"node_metadata": {}}],
        )

        rows = self._rows(generator, {"f1": {"id": "f1", "name": "f1.pdf", "modified_time": 0}})

        assert rows["f1.pdf"]["Status"] == "Ingested"
        assert rows["d1"]["Status"] == "Ingested"

    @pytest.mark.parametrize("status", [ExecutionStatus.COMPLETED])
    def test_no_documents_still_returns_empty_report(self, status):
        generator = self._generator({}, [])

        assert self._rows(generator, {}) == {}
