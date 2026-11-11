# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""StreamingOrchestrator corner cases: empty inputs and unknown operators."""

import re
from typing import Any
from uuid import UUID

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import ExecutionStatus, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.functional.branching_operator import BranchingOperator
from docpipe.core.operators.functional.chunker import ChunkerOperator
from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator
from docpipe.core.orchestration.streaming.graph.execution_engine import GraphExecutionEngine
from docpipe.core.orchestration.streaming.streaming_orchestrator import StreamingOrchestrator

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

    outputs = StreamingOrchestrator().execute(flow=flow, params={})

    chunker_transform.assert_not_called()
    assert list(outputs) == [NEXT_ID]
    (table,) = outputs[NEXT_ID].tables
    assert table.num_rows == 0
    assert table.column_names == ["id", "name", "document_format"]


def test_streaming_orchestrator_empty_input_skips_branching_node(mocker):
    """A branching node that receives an empty table is skipped and every branch gets the empty table."""
    second_sink_id = UUID("00000000-0000-0000-0000-000000000004")
    flow = {
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
                {"branches": [{"link_id": "branch_1"}, {"link_id": "branch_2"}]},
                [{"node_id_ref": str(INGEST_ID)}],
                [
                    {"node_id_ref": str(LAST_ID), "link_name": "branch_1"},
                    {"node_id_ref": str(second_sink_id), "link_name": "branch_2"},
                ],
            ),
            _node(
                LAST_ID,
                "simple_chunker_1",
                "chunker",
                CHUNKER_CONFIG,
                [{"node_id_ref": str(NEXT_ID), "link_name": "branch_1"}],
                [],
            ),
            _node(
                second_sink_id,
                "simple_chunker_2",
                "chunker",
                CHUNKER_CONFIG,
                [{"node_id_ref": str(NEXT_ID), "link_name": "branch_2"}],
                [],
            ),
        ],
    }
    mocker.patch.object(IngestSourceOperator, "transform", autospec=True, side_effect=_empty_ingest)
    branching_transform = mocker.patch.object(BranchingOperator, "transform", autospec=True)
    chunker_transform = mocker.patch.object(ChunkerOperator, "transform", autospec=True)
    branching_execution = mocker.spy(GraphExecutionEngine, "_execute_branching_node")

    outputs = StreamingOrchestrator().execute(flow=flow, params={})

    branching_transform.assert_not_called()
    chunker_transform.assert_not_called()
    branching_execution.assert_called_once()
    branch_output = branching_execution.spy_return
    assert branch_output.metadata == {
        Metrics.External.TOTAL_DOCS: 0,
        Metrics.External.PROCESSED_DOCS: 0,
        Metrics.External.FAILED_DOCS_COUNT: 0,
        Metrics.External.FAILED_DOCS: [],
        Metrics.External.SKIPPED_DOCS_COUNT: 0,
        Metrics.External.SKIPPED_DOCS: [],
        Metrics.External.NODE_STATUS: ExecutionStatus.COMPLETED.value,
        OperatorConstants.Misc.BRANCHES: {
            "branch_1": {OperatorConstants.Misc.RESULT_INDEX: 0},
            "branch_2": {OperatorConstants.Misc.RESULT_INDEX: 0},
        },
    }
    assert len(branch_output.tables) == 1
    assert branch_output.tables[0].num_rows == 0
    assert list(outputs) == [LAST_ID, second_sink_id]
    (table,) = outputs[LAST_ID].tables
    assert table.num_rows == 0


def test_streaming_orchestrator_rejects_unknown_branch_before_execution(mocker):
    """A mismatched branch route fails graph validation before any transform runs."""
    flow = {
        "name": "invalid-branch-route",
        "dag": [
            _node(INGEST_ID, "source", "ingest_source", INGEST_CONFIG, [], [{"node_id_ref": str(NEXT_ID)}]),
            _node(
                NEXT_ID,
                "branch_by_format",
                "branching",
                {"branches": [{"link_id": "configured"}, {"link_id": "other"}]},
                [{"node_id_ref": str(INGEST_ID)}],
                [{"node_id_ref": str(LAST_ID), "link_name": "unknown"}],
            ),
            _node(LAST_ID, "sink", "chunker", CHUNKER_CONFIG, [{"node_id_ref": str(NEXT_ID)}], []),
        ],
    }
    ingest_transform = mocker.patch.object(IngestSourceOperator, "transform", autospec=True)
    branching_transform = mocker.patch.object(BranchingOperator, "transform", autospec=True)

    with pytest.raises(ValueError, match=r"branch_by_format.*configured branch IDs do not match outgoing edges"):
        StreamingOrchestrator().execute(flow=flow, params={})

    ingest_transform.assert_not_called()
    branching_transform.assert_not_called()


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
    with pytest.raises(ValueError, match=f"^{re.escape('Operator:does_not_exist not found.')}$"):
        StreamingOrchestrator().execute(flow=flow, params={})


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

    with pytest.raises(RuntimeError, match="Operator boom"):
        engine.execute()

    assert len(engine.output_buffer.data_buffer) == 0
