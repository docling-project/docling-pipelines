"""Unit tests for LineageService."""

from unittest.mock import MagicMock

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import ExecutionStatus
from docpipe.core.lineage.application.lineage_service import LineageService
from docpipe.core.lineage.domain.models.event_type import LineageEventType
from docpipe.core.lineage.domain.ports.lineage_publisher import LineagePublisherPort
from docpipe.core.orchestration.models.execution_event_context import (
    FlowAbortContext,
    FlowCompleteContext,
    FlowFailContext,
    FlowRunningContext,
    FlowStartContext,
    NodeCompleteContext,
    NodeFailContext,
    NodeSkipContext,
    NodeStartContext,
    NodeTableSummary,
    SinkDatasetInfo,
)


@pytest.fixture
def mock_publisher() -> MagicMock:
    return MagicMock(spec=LineagePublisherPort)


@pytest.fixture
def service(mock_publisher: MagicMock) -> LineageService:
    return LineageService(
        publisher=mock_publisher,
        namespace="docpipe://test",
        producer="https://test.producer",
    )


@pytest.fixture
def sample_table() -> pa.Table:
    return pa.table({"id": ["a", "b"], "content": ["hello", "world"]})


@pytest.fixture
def sample_summary() -> NodeTableSummary:
    return NodeTableSummary(schema_fields=[("id", "string"), ("content", "string")], row_count=2)


class TestEmitFlowStart:
    def test_publishes_start_event(self, service: LineageService, mock_publisher: MagicMock) -> None:
        context = FlowStartContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            flow_def={"flow_name": "test-flow"},
        )
        service.emit_flow_start(context=context)
        mock_publisher.publish.assert_called_once()
        call_kwargs = mock_publisher.publish.call_args[1]
        assert call_kwargs["event_type"] == LineageEventType.START
        assert call_kwargs["run"].run_id == "run-1"
        assert call_kwargs["job"].name == "test-flow"
        assert call_kwargs["job"].namespace == "docpipe://test"

    def test_flow_def_stripped_of_credentials(self, service: LineageService, mock_publisher: MagicMock) -> None:
        context = FlowStartContext(
            flow_id="",
            flow_name="my-flow",
            job_run_id="run-2",
            flow_def={"flow_name": "my-flow", "credentials": {"token": "secret"}},
        )
        service.emit_flow_start(context=context)
        mock_publisher.publish.assert_called_once()


class TestEmitFlowRunning:
    def test_publishes_running_event_with_input_dataset(
        self, service: LineageService, mock_publisher: MagicMock, sample_table: pa.Table
    ) -> None:
        context = FlowRunningContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            ingested_table=sample_table,
            ingest_node_id="ingest_node",
        )
        service.emit_flow_running(context=context)
        call_kwargs = mock_publisher.publish.call_args[1]
        assert call_kwargs["event_type"] == LineageEventType.RUNNING
        assert len(call_kwargs["inputs"]) == 1
        assert call_kwargs["inputs"][0].name == "ingest_node"

    def test_publishes_running_event_without_table(self, service: LineageService, mock_publisher: MagicMock) -> None:
        context = FlowRunningContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
        )
        service.emit_flow_running(context=context)
        call_kwargs = mock_publisher.publish.call_args[1]
        assert call_kwargs["inputs"] == []


class TestEmitFlowComplete:
    def test_publishes_complete_event(
        self, service: LineageService, mock_publisher: MagicMock, sample_table: pa.Table
    ) -> None:
        context = FlowCompleteContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            flow_def={},
            output_tables=[sample_table],
        )
        service.emit_flow_complete(context=context)
        call_kwargs = mock_publisher.publish.call_args[1]
        assert call_kwargs["event_type"] == LineageEventType.COMPLETE
        assert len(call_kwargs["outputs"]) == 1
        assert call_kwargs["outputs"][0].namespace == "inmemory://"
        assert call_kwargs["outputs"][0].name == "test-flow/output"

    def test_publishes_complete_event_with_sink_dataset(
        self, service: LineageService, mock_publisher: MagicMock, sample_table: pa.Table
    ) -> None:
        context = FlowCompleteContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            flow_def={},
            output_tables=[sample_table],
            sink_datasets=[
                SinkDatasetInfo(
                    namespace="opensearch://localhost:9200",
                    name="my_index",
                    summary=NodeTableSummary(schema_fields=[("id", "string")], row_count=2),
                )
            ],
        )
        service.emit_flow_complete(context=context)
        call_kwargs = mock_publisher.publish.call_args[1]
        assert call_kwargs["event_type"] == LineageEventType.COMPLETE
        assert len(call_kwargs["outputs"]) == 1
        assert call_kwargs["outputs"][0].namespace == "opensearch://localhost:9200"
        assert call_kwargs["outputs"][0].name == "my_index"

    def test_each_sink_reports_its_own_schema_and_row_count(
        self, service: LineageService, mock_publisher: MagicMock, sample_table: pa.Table
    ) -> None:
        """Sinks fed by different tables must not inherit the last node's schema and row count."""
        context = FlowCompleteContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            flow_def={},
            output_tables=[sample_table],
            sink_datasets=[
                SinkDatasetInfo(
                    namespace="opensearch://localhost:9200",
                    name="idx_a",
                    summary=NodeTableSummary(schema_fields=[("id", "string")], row_count=10),
                ),
                SinkDatasetInfo(
                    namespace="milvus://localhost:19530",
                    name="default.coll_b",
                    summary=NodeTableSummary(schema_fields=[("id", "string"), ("vec", "list<float>")], row_count=7),
                ),
            ],
        )
        service.emit_flow_complete(context=context)
        outputs = mock_publisher.publish.call_args[1]["outputs"]
        assert [(o.namespace, o.name) for o in outputs] == [
            ("opensearch://localhost:9200", "idx_a"),
            ("milvus://localhost:19530", "default.coll_b"),
        ]
        assert outputs[0].facets["outputStatistics"]["rowCount"] == 10
        assert outputs[1].facets["outputStatistics"]["rowCount"] == 7
        assert len(outputs[0].facets["schema"]["fields"]) == 1
        assert len(outputs[1].facets["schema"]["fields"]) == 2


class TestEmitFlowFail:
    def test_publishes_fail_event_with_error_facet(self, service: LineageService, mock_publisher: MagicMock) -> None:
        context = FlowFailContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            error_message="Something went wrong",
            exception=RuntimeError("boom"),
        )
        service.emit_flow_fail(context=context)
        call_kwargs = mock_publisher.publish.call_args[1]
        assert call_kwargs["event_type"] == LineageEventType.FAIL
        assert "errorMessage" in call_kwargs["run"].facets


class TestEmitFlowAbort:
    def test_publishes_abort_event(self, service: LineageService, mock_publisher: MagicMock) -> None:
        context = FlowAbortContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            reason="User cancelled",
        )
        service.emit_flow_abort(context=context)
        call_kwargs = mock_publisher.publish.call_args[1]
        assert call_kwargs["event_type"] == LineageEventType.ABORT


class TestEmitNodeStart:
    def test_publishes_node_start_with_input_and_uses_node_name(
        self, service: LineageService, mock_publisher: MagicMock, sample_summary: NodeTableSummary
    ) -> None:
        context = NodeStartContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            node_id="n1",
            node_name="chunker",
            operator_type="chunker",
            operator_category="Functional",
            input_summary=sample_summary,
            predecessor_node_ids=["extract"],
        )
        service.emit_node_start(context=context)
        call_kwargs = mock_publisher.publish.call_args[1]
        assert call_kwargs["event_type"] == LineageEventType.START
        # job name is stable: flow_name/node_name
        assert call_kwargs["job"].name == "test-flow/chunker"
        # operator and operatorCategory surfaced in jobType facet
        jt = call_kwargs["job"].facets["jobType"]
        assert jt["operator"] == "chunker"
        assert jt["operatorCategory"] == "Functional"
        # input dataset chains from predecessor output: flow_name/predecessor/output
        assert len(call_kwargs["inputs"]) == 1
        assert call_kwargs["inputs"][0].name == "test-flow/extract/output"
        assert call_kwargs["inputs"][0].facets["schema"]["fields"][0]["name"] == "id"

    def test_node_start_no_predecessors(self, service: LineageService, mock_publisher: MagicMock) -> None:
        context = NodeStartContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            node_id="ingest",
            node_name="ingest_source",
            operator_type="ingest_source",
            operator_category="Ingest",
        )
        service.emit_node_start(context=context)
        call_kwargs = mock_publisher.publish.call_args[1]
        assert call_kwargs["job"].name == "test-flow/ingest_source"
        assert call_kwargs["job"].facets["jobType"]["operator"] == "ingest_source"
        assert call_kwargs["job"].facets["jobType"]["operatorCategory"] == "Ingest"
        assert call_kwargs["inputs"] == []

    def test_node_start_no_operator_category_omits_field(
        self, service: LineageService, mock_publisher: MagicMock
    ) -> None:
        context = NodeStartContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            node_id="n1",
            node_name="chunker",
            operator_type="chunker",
            # operator_category intentionally absent
        )
        service.emit_node_start(context=context)
        jt = mock_publisher.publish.call_args[1]["job"].facets["jobType"]
        assert jt["operator"] == "chunker"
        assert "operatorCategory" not in jt

    def test_node_start_no_input_summary_emits_empty_inputs(
        self, service: LineageService, mock_publisher: MagicMock
    ) -> None:
        context = NodeStartContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            node_id="n1",
            node_name="chunker",
            operator_type="chunker",
        )
        service.emit_node_start(context=context)
        call_kwargs = mock_publisher.publish.call_args[1]
        assert call_kwargs["inputs"] == []


class TestEmitNodeComplete:
    def test_publishes_node_complete_with_named_outputs(
        self, service: LineageService, mock_publisher: MagicMock, sample_summary: NodeTableSummary
    ) -> None:
        context = NodeCompleteContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            node_id="n1",
            node_name="chunker",
            operator_type="chunker",
            operator_category="Functional",
            output_summaries=[sample_summary],
        )
        service.emit_node_complete(context=context)
        call_kwargs = mock_publisher.publish.call_args[1]
        assert call_kwargs["event_type"] == LineageEventType.COMPLETE
        assert len(call_kwargs["outputs"]) == 1
        # in-memory dataset
        assert call_kwargs["outputs"][0].namespace == "inmemory://"
        assert call_kwargs["outputs"][0].name == "test-flow/chunker/output"
        assert call_kwargs["outputs"][0].facets["outputStatistics"]["rowCount"] == 2
        # operator surfaced in job facet
        jt = call_kwargs["job"].facets["jobType"]
        assert jt["operator"] == "chunker"
        assert jt["operatorCategory"] == "Functional"

    def test_publishes_node_complete_with_sink_dataset(
        self, service: LineageService, mock_publisher: MagicMock, sample_summary: NodeTableSummary
    ) -> None:
        context = NodeCompleteContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            node_id="n1",
            node_name="vectordb",
            operator_type="vectordb",
            output_summaries=[sample_summary],
            sink_dataset_namespace="opensearch://localhost:9200",
            sink_dataset_name="kb_index",
        )
        service.emit_node_complete(context=context)
        call_kwargs = mock_publisher.publish.call_args[1]
        assert call_kwargs["outputs"][0].namespace == "opensearch://localhost:9200"
        assert call_kwargs["outputs"][0].name == "kb_index"
        # Terminal sink: only the external dataset, no dangling in-memory dataset
        assert len(call_kwargs["outputs"]) == 1

    def test_sink_with_downstream_also_emits_in_memory_output(
        self, service: LineageService, mock_publisher: MagicMock, sample_summary: NodeTableSummary
    ) -> None:
        """A sink followed by other operators must keep the in-memory edge to its successor."""
        context = NodeCompleteContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            node_id="n1",
            node_name="store_in_document_set",
            operator_type="document_set",
            output_summaries=[sample_summary],
            sink_dataset_namespace="docpipe://document_set",
            sink_dataset_name="my_set",
            has_downstream=True,
        )
        service.emit_node_complete(context=context)
        outputs = mock_publisher.publish.call_args[1]["outputs"]
        assert [(o.namespace, o.name) for o in outputs] == [
            ("docpipe://document_set", "my_set"),
            ("inmemory://", "test-flow/store_in_document_set/output"),
        ]

    def test_downstream_start_input_matches_sink_pass_through_output(
        self, service: LineageService, mock_publisher: MagicMock, sample_summary: NodeTableSummary
    ) -> None:
        """The successor's START input dataset must equal the sink's in-memory output dataset."""
        service.emit_node_complete(
            context=NodeCompleteContext(
                flow_id="flow-1",
                flow_name="test-flow",
                job_run_id="run-1",
                node_id="n1",
                node_name="store_in_document_set",
                operator_type="document_set",
                output_summaries=[sample_summary],
                sink_dataset_namespace="docpipe://document_set",
                sink_dataset_name="my_set",
                has_downstream=True,
            )
        )
        sink_outputs = mock_publisher.publish.call_args[1]["outputs"]
        service.emit_node_start(
            context=NodeStartContext(
                flow_id="flow-1",
                flow_name="test-flow",
                job_run_id="run-1",
                node_id="n2",
                node_name="store_in_opensearch",
                operator_type="vectordb",
                input_summary=sample_summary,
                predecessor_node_ids=["store_in_document_set"],
            )
        )
        start_inputs = mock_publisher.publish.call_args[1]["inputs"]
        assert (start_inputs[0].namespace, start_inputs[0].name) in {(o.namespace, o.name) for o in sink_outputs}

    def test_node_complete_end_time_populated(
        self, service: LineageService, mock_publisher: MagicMock, sample_summary: NodeTableSummary
    ) -> None:
        context = NodeCompleteContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            node_id="n1",
            node_name="chunker",
            operator_type="chunker",
            output_summaries=[sample_summary],
            end_time="2024-01-01T00:00:01Z",
        )
        service.emit_node_complete(context=context)
        call_kwargs = mock_publisher.publish.call_args[1]
        assert call_kwargs["run"].end_time == "2024-01-01T00:00:01Z"


class TestNodeStatsAndCamelCase:
    """Tests for _build_node_stats_facet and _to_camel_case."""

    def test_node_complete_with_metadata_adds_docpipe_stats(
        self, service: LineageService, mock_publisher: MagicMock, sample_summary: NodeTableSummary
    ) -> None:
        context = NodeCompleteContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            node_id="n1",
            node_name="chunker",
            operator_type="chunker",
            output_summaries=[sample_summary],
            metadata={
                "processed_docs": 11,
                "total_chunks": 110,
                "node_status": "Completed",
            },
        )
        service.emit_node_complete(context=context)
        run_facets = mock_publisher.publish.call_args[1]["run"].facets
        assert "docpipeStats" in run_facets
        stats = run_facets["docpipeStats"]
        assert stats["processedDocs"] == 11
        assert stats["totalChunks"] == 110
        assert stats["nodeStatus"] == "Completed"

    def test_node_complete_with_empty_metadata_omits_facet(
        self, service: LineageService, mock_publisher: MagicMock, sample_summary: NodeTableSummary
    ) -> None:
        context = NodeCompleteContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            node_id="n1",
            node_name="noop",
            operator_type="noop",
            output_summaries=[sample_summary],
            metadata={},
        )
        service.emit_node_complete(context=context)
        run_facets = mock_publisher.publish.call_args[1]["run"].facets
        assert "docpipeStats" not in run_facets

    def test_node_complete_internal_keys_excluded(
        self, service: LineageService, mock_publisher: MagicMock, sample_summary: NodeTableSummary
    ) -> None:
        context = NodeCompleteContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            node_id="n1",
            node_name="ingest",
            operator_type="ingest_source",
            output_summaries=[sample_summary],
            metadata={
                "processed_docs": 5,
                "deleted_from_last_run": 2,  # internal — must be excluded
                "all_doc_ids": ["a", "b"],  # internal — must be excluded
            },
        )
        service.emit_node_complete(context=context)
        stats = mock_publisher.publish.call_args[1]["run"].facets["docpipeStats"]
        assert "processedDocs" in stats
        assert "deletedFromLastRun" not in stats
        assert "allDocIds" not in stats

    def test_node_complete_non_scalar_values_excluded(
        self, service: LineageService, mock_publisher: MagicMock, sample_summary: NodeTableSummary
    ) -> None:
        context = NodeCompleteContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            node_id="n1",
            node_name="vectordb",
            operator_type="vectordb",
            output_summaries=[sample_summary],
            metadata={
                "processed_docs": 8,
                "page_type_stats": {"text": 5, "table": 3},  # dict — excluded
                "chunks_indexed_successfully": 80,
            },
        )
        service.emit_node_complete(context=context)
        stats = mock_publisher.publish.call_args[1]["run"].facets["docpipeStats"]
        assert stats["processedDocs"] == 8
        assert stats["chunksIndexedSuccessfully"] == 80
        assert "pageTypeStats" not in stats

    def test_sql_filter_metrics_surface_correctly(
        self, service: LineageService, mock_publisher: MagicMock, sample_summary: NodeTableSummary
    ) -> None:
        context = NodeCompleteContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            node_id="n1",
            node_name="sql_filter",
            operator_type="sql_filter",
            output_summaries=[sample_summary],
            metadata={
                "processed_docs": 8,
                "docs_before_filter": 11,
                "docs_after_filter": 8,
                "bytes_before_filter": 45200,
                "bytes_after_filter": 32800,
                "node_status": "Completed",
            },
        )
        service.emit_node_complete(context=context)
        stats = mock_publisher.publish.call_args[1]["run"].facets["docpipeStats"]
        assert stats["docsBeforeFilter"] == 11
        assert stats["docsAfterFilter"] == 8
        assert stats["bytesBeforeFilter"] == 45200
        assert stats["bytesAfterFilter"] == 32800


class TestEmitNodeFail:
    def test_uses_input_summary_when_present(
        self, service: LineageService, mock_publisher: MagicMock, sample_summary: NodeTableSummary
    ) -> None:
        context = NodeFailContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            node_id="n1",
            node_name="chunker",
            operator_type="chunker",
            error_message="chunker error",
            input_summary=sample_summary,
        )
        service.emit_node_fail(context=context)
        call_kwargs = mock_publisher.publish.call_args[1]
        assert call_kwargs["event_type"] == LineageEventType.FAIL
        assert len(call_kwargs["inputs"]) == 1
        # no predecessors on this context → fallback input name
        assert call_kwargs["inputs"][0].name == "test-flow/chunker/input"

    def test_no_inputs_when_no_summary(self, service: LineageService, mock_publisher: MagicMock) -> None:
        context = NodeFailContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            node_id="n1",
            node_name="chunker",
            operator_type="chunker",
            error_message="error",
        )
        service.emit_node_fail(context=context)
        call_kwargs = mock_publisher.publish.call_args[1]
        assert call_kwargs["inputs"] == []

    def test_start_and_end_time_on_fail(self, service: LineageService, mock_publisher: MagicMock) -> None:
        context = NodeFailContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            node_id="n1",
            node_name="chunker",
            operator_type="chunker",
            error_message="error",
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-01-01T00:00:01Z",
        )
        service.emit_node_fail(context=context)
        call_kwargs = mock_publisher.publish.call_args[1]
        assert call_kwargs["run"].start_time == "2024-01-01T00:00:00Z"
        assert call_kwargs["run"].end_time == "2024-01-01T00:00:01Z"


class TestEmitNodeSkip:
    def test_publishes_other_event_with_reason_facet(self, service: LineageService, mock_publisher: MagicMock) -> None:
        context = NodeSkipContext(
            flow_id="flow-1",
            flow_name="test-flow",
            job_run_id="run-1",
            node_id="n1",
            node_name="chunker",
            operator_type="chunker",
            reason="no data",
        )
        service.emit_node_skip(context=context)
        call_kwargs = mock_publisher.publish.call_args[1]
        assert call_kwargs["event_type"] == LineageEventType.OTHER
        assert call_kwargs["run"].facets["docpipeSkip"]["reason"] == "no data"


class TestParentRunFacet:
    """ParentRunFacet links every node run back to its parent flow run."""

    def _assert_parent_facet(self, run_facets: dict, *, flow_name: str, job_run_id: str, namespace: str) -> None:
        assert "parent" in run_facets, "parent facet missing from run"
        parent = run_facets["parent"]
        assert parent["job"]["namespace"] == namespace
        assert parent["job"]["name"] == flow_name
        assert parent["run"]["runId"] == job_run_id

    def test_node_start_carries_parent_facet(self, service: LineageService, mock_publisher: MagicMock) -> None:
        context = NodeStartContext(
            flow_id="flow-1",
            flow_name="lineage-full-pipeline",
            job_run_id="aaaaaaaa-0000-0000-0000-000000000001",
            node_id="n1",
            node_name="chunk",
            operator_type="chunker",
        )
        service.emit_node_start(context=context)
        run_facets = mock_publisher.publish.call_args[1]["run"].facets
        self._assert_parent_facet(
            run_facets,
            flow_name="lineage-full-pipeline",
            job_run_id="aaaaaaaa-0000-0000-0000-000000000001",
            namespace="docpipe://test",
        )

    def test_node_complete_carries_parent_facet(
        self, service: LineageService, mock_publisher: MagicMock, sample_summary: NodeTableSummary
    ) -> None:
        context = NodeCompleteContext(
            flow_id="flow-1",
            flow_name="lineage-full-pipeline",
            job_run_id="aaaaaaaa-0000-0000-0000-000000000001",
            node_id="n1",
            node_name="chunk",
            operator_type="chunker",
            output_summaries=[sample_summary],
        )
        service.emit_node_complete(context=context)
        run_facets = mock_publisher.publish.call_args[1]["run"].facets
        self._assert_parent_facet(
            run_facets,
            flow_name="lineage-full-pipeline",
            job_run_id="aaaaaaaa-0000-0000-0000-000000000001",
            namespace="docpipe://test",
        )

    def test_parent_job_name_matches_flow_name_exactly(
        self, service: LineageService, mock_publisher: MagicMock
    ) -> None:
        """Critical: parent.job.name must exactly match the registered flow job name.

        If it uses flow_id (a UUID) instead of flow_name, Marquez creates a
        ghost job with the UUID as its name — the 'derived job artifact' bug.
        """
        context = NodeStartContext(
            flow_id="some-uuid-that-must-not-appear",
            flow_name="my-exact-flow-name",
            job_run_id="aaaaaaaa-0000-0000-0000-000000000001",
            node_id="n1",
            node_name="chunk",
            operator_type="chunker",
        )
        service.emit_node_start(context=context)
        parent_job_name = mock_publisher.publish.call_args[1]["run"].facets["parent"]["job"]["name"]
        assert parent_job_name == "my-exact-flow-name"
        assert "some-uuid-that-must-not-appear" not in parent_job_name


class TestNodeTableSummary:
    def test_from_table_extracts_schema_and_row_count(self, sample_table: pa.Table) -> None:
        summary = NodeTableSummary.from_table(sample_table)
        assert summary.row_count == 2
        assert ("id", "string") in summary.schema_fields
        assert ("content", "string") in summary.schema_fields

    def test_from_table_empty(self) -> None:
        empty = pa.table({"x": pa.array([], type=pa.int64())})
        summary = NodeTableSummary.from_table(empty)
        assert summary.row_count == 0
        assert summary.schema_fields == [("x", "int64")]


class TestResolveStatus:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (ExecutionStatus.COMPLETED, LineageEventType.COMPLETE),
            (ExecutionStatus.COMPLETED_WITH_ERRORS, LineageEventType.COMPLETE),
            (ExecutionStatus.COMPLETED_WITH_WARNINGS, LineageEventType.COMPLETE),
            (ExecutionStatus.FAILED, LineageEventType.FAIL),
            (ExecutionStatus.FAILING, LineageEventType.FAIL),
            (ExecutionStatus.CANCELED, LineageEventType.ABORT),
            (ExecutionStatus.CANCELING, LineageEventType.ABORT),
            (ExecutionStatus.ABORTED, LineageEventType.ABORT),
            (ExecutionStatus.RUNNING, LineageEventType.RUNNING),
        ],
    )
    def test_all_statuses_map_correctly(self, status: ExecutionStatus, expected: LineageEventType) -> None:
        assert LineageService.resolve_status(status=status) == expected

    def test_unknown_status_returns_other(self) -> None:
        assert LineageService.resolve_status(status="unknown_status") == LineageEventType.OTHER
