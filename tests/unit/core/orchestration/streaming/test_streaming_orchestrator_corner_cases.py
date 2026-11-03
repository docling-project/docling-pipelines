# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""StreamingOrchestrator corner cases: empty inputs and unknown operators."""

from typing import Any
from uuid import UUID

import pyarrow as pa
import pytest

from docpipe.core.operators.functional.branching_operator import BranchingOperator
from docpipe.core.operators.functional.chunker import ChunkerOperator
from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator
from docpipe.core.orchestration.streaming.graph.execution_engine import GraphExecutionEngine
from docpipe.core.orchestration.streaming.graph.flow_model import Node
from docpipe.core.orchestration.streaming.streaming_orchestrator import StreamingOrchestrator
from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException

INGEST_ID = UUID("00000000-0000-0000-0000-000000000001")
NEXT_ID = UUID("00000000-0000-0000-0000-000000000002")
LAST_ID = UUID("00000000-0000-0000-0000-000000000003")

INGEST_CONFIG = {"provider": "filesystem", "provider_config": {"paths": ["/documents"]}, "include_filter": "pdf"}
CHUNKER_CONFIG = {"chunk_type": "simple", "chunk_size": 512, "chunk_overlap": 50, "retain_original_content": False}


def _node(
    node_id: UUID, name: str, operator: str, config: dict[str, Any], inputs: list[dict], outputs: list[dict]
) -> dict[str, Any]:
    """Build one DAG node in the runtime-flow format."""
    return {
        "id": str(node_id),
        "name": name,
        "operator": operator,
        "config": config,
        "input_edges": inputs,
        "output_edges": outputs,
    }


def _empty_ingest(self, table, *args, **kwargs):
    """Mimic ``IngestSourceOperator`` finding no documents: an empty table with the ingest columns."""
    schema = pa.schema([("id", pa.string()), ("name", pa.string()), ("document_format", pa.string())])
    return [schema.empty_table()], {}


def test_streaming_orchestrator_empty_input_skips_simple_node(mocker):
    """A simple node that receives an empty table is skipped and the empty table is passed through."""
    flow = {
        "name": "empty-linear-flow",
        "dag": [
            _node(
                INGEST_ID,
                "ingest_source_filesystem",
                "ingest_source",
                INGEST_CONFIG,
                [],
                [{"node_id_ref": str(NEXT_ID)}],
            ),
            _node(NEXT_ID, "simple_chunker", "chunker", CHUNKER_CONFIG, [{"node_id_ref": str(INGEST_ID)}], []),
        ],
    }
    mocker.patch.object(IngestSourceOperator, "transform", autospec=True, side_effect=_empty_ingest)
    chunker_transform = mocker.patch.object(ChunkerOperator, "transform", autospec=True)

    execution = mocker.spy(GraphExecutionEngine, "execute")
    result = StreamingOrchestrator().execute(flow=flow, params={})

    assert result is None
    outputs = execution.spy_return

    chunker_transform.assert_not_called()
    assert list(outputs) == [NEXT_ID]
    (table,) = outputs[NEXT_ID].tables
    assert table.num_rows == 0
    assert table.column_names == ["id", "name", "document_format"]


def test_streaming_orchestrator_empty_input_skips_branching_node(mocker):
    """A branching node that receives an empty table is skipped and every branch gets the empty table."""
    flow: dict[str, Any] = {
        "name": "empty-branching-flow",
        "dag": [
            _node(
                INGEST_ID,
                "ingest_source_filesystem",
                "ingest_source",
                INGEST_CONFIG,
                [],
                [{"node_id_ref": str(NEXT_ID)}],
            ),
            _node(
                NEXT_ID,
                "branch_by_format",
                "branching",
                {"branches": {"branch_1": {"link_name": "pdf_documents"}}},
                [{"node_id_ref": str(INGEST_ID)}],
                [{"node_id_ref": str(LAST_ID), "link_name": "branch_1"}],
            ),
            _node(
                LAST_ID,
                "simple_chunker_1",
                "chunker",
                CHUNKER_CONFIG,
                [{"node_id_ref": str(NEXT_ID), "link_name": "branch_1"}],
                [],
            ),
        ],
    }
    flow["dag"][-1]["link_id"] = "branch_1"
    mocker.patch.object(IngestSourceOperator, "transform", autospec=True, side_effect=_empty_ingest)
    branching_transform = mocker.patch.object(BranchingOperator, "transform", autospec=True)
    chunker_transform = mocker.patch.object(ChunkerOperator, "transform", autospec=True)

    execution = mocker.spy(GraphExecutionEngine, "execute")
    result = StreamingOrchestrator().execute(flow=flow, params={})

    assert result is None
    outputs = execution.spy_return

    branching_transform.assert_not_called()
    chunker_transform.assert_not_called()
    assert list(outputs) == [LAST_ID]
    (table,) = outputs[LAST_ID].tables
    assert table.num_rows == 0


def test_streaming_orchestrator_unknown_operator_fails(mocker):
    """A node whose operator is not registered fails with a clear error."""
    flow = {
        "name": "unknown-operator-flow",
        "dag": [
            _node(
                INGEST_ID,
                "ingest_source_filesystem",
                "ingest_source",
                INGEST_CONFIG,
                [],
                [{"node_id_ref": str(NEXT_ID)}],
            ),
            _node(NEXT_ID, "mystery_step", "does_not_exist", {}, [{"node_id_ref": str(INGEST_ID)}], []),
        ],
    }

    def _sample_ingest(self, table, *args, **kwargs):
        doc = {"id": "doc_1", "name": "test.pdf", "document_format": ".pdf"}
        return [pa.Table.from_pylist([doc])], {}

    mocker.patch.object(IngestSourceOperator, "transform", autospec=True, side_effect=_sample_ingest)
    with pytest.raises(FlowExecutionFailedException, match="Operator:does_not_exist not found") as error:
        StreamingOrchestrator().execute(flow=flow, params={})

    assert "node=mystery_step operator=does_not_exist" in str(error.value)
    assert isinstance(error.value.__cause__, ValueError)


def test_streaming_orchestrator_cycle_detection_fails():
    # A cycle between operators is rejected with a ValueError listing cycle node names.
    merge_config = {
        "input_links": [
            {"node_id_ref": str(INGEST_ID), "link_name": "in_1"},
            {"node_id_ref": str(LAST_ID), "link_name": "in_2"},
        ]
    }
    flow = {
        "name": "cyclic-flow",
        "dag": [
            _node(
                INGEST_ID,
                "ingest_source_filesystem",
                "ingest_source",
                INGEST_CONFIG,
                [],
                [{"node_id_ref": str(NEXT_ID)}],
            ),
            _node(
                NEXT_ID,
                "merge_branches",
                "merge",
                merge_config,
                [{"node_id_ref": str(INGEST_ID)}, {"node_id_ref": str(LAST_ID)}],
                [{"node_id_ref": str(LAST_ID)}],
            ),
            _node(
                LAST_ID,
                "simple_chunker",
                "chunker",
                CHUNKER_CONFIG,
                [{"node_id_ref": str(NEXT_ID)}],
                [{"node_id_ref": str(NEXT_ID)}],
            ),
        ],
    }
    with pytest.raises(
        ValueError,
        match=r"^Cycle detected in flow graph: (merge_branches -> simple_chunker -> merge_branches|simple_chunker -> merge_branches -> simple_chunker)\.$",
    ):
        StreamingOrchestrator().execute(flow=flow, params={})


def test_execution_engine_clears_buffer_on_failure(mocker):
    # Output buffer is cleared when operator execution raises an exception.
    from docpipe.core.orchestration.streaming.graph.execution_engine import GraphExecutionEngine
    from docpipe.core.orchestration.streaming.graph.flow_builder import FlowBuilder

    flow = {
        "name": "failing-flow",
        "dag": [
            _node(
                INGEST_ID,
                "ingest_source_filesystem",
                "ingest_source",
                INGEST_CONFIG,
                [],
                [{"node_id_ref": str(NEXT_ID)}],
            ),
            _node(NEXT_ID, "failing_chunker", "chunker", CHUNKER_CONFIG, [{"node_id_ref": str(INGEST_ID)}], []),
        ],
    }

    def _sample_ingest(self, table, *args, **kwargs):
        doc = {"id": "doc_1", "name": "test.pdf", "document_format": ".pdf"}
        return [pa.Table.from_pylist([doc])], {}

    mocker.patch.object(IngestSourceOperator, "transform", autospec=True, side_effect=_sample_ingest)
    mocker.patch.object(ChunkerOperator, "transform", autospec=True, side_effect=RuntimeError("Operator boom"))

    builder = FlowBuilder(flow=flow, params={})
    flow_graph = builder.build_graph()
    ordered_ids = FlowBuilder.sort_graph(flow_graph=flow_graph)
    engine = GraphExecutionEngine(flow_graph=flow_graph, ordered_operator_ids=ordered_ids)

    with pytest.raises(FlowExecutionFailedException, match="Operator boom"):
        engine.execute()

    assert len(engine.output_buffer.data_buffer) == 0


def test_reported_failure_omits_document_reason():
    """Failure metadata can stop execution without exposing document details."""
    node = Node(id=INGEST_ID, name="source", operator_name="ingest_source", operator_config={})
    with pytest.raises(FlowExecutionFailedException, match="reported a failed execution") as error:
        GraphExecutionEngine._raise_if_node_failed(
            node=node, metadata={"failed_docs_count": 1, "failed_docs": [{"reason": "Sensitive document details"}]}
        )

    assert "ingest_source" in str(error.value)
    assert "Sensitive document details" not in str(error.value)
