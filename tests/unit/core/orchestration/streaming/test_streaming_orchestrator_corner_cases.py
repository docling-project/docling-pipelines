# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""StreamingOrchestrator corner cases: empty inputs and unknown operators."""

import re
from copy import deepcopy
from typing import Any
from unittest.mock import call
from uuid import UUID

import pyarrow as pa
import pytest

from docpipe.core.constants.constants import ExecutionStatus, Metrics
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.event_streaming.models import InputEvent
from docpipe.core.operators.functional.branching_operator import BranchingOperator
from docpipe.core.operators.functional.chunker import ChunkerOperator
from docpipe.core.operators.ingest.ingest_source import IngestSourceOperator
from docpipe.core.orchestration.streaming.graph.execution_engine import GraphExecutionEngine
from docpipe.core.orchestration.streaming.graph.flow_model import FlowGraph, Node
from docpipe.core.orchestration.streaming.graph.output_buffer import OperatorOutput
from docpipe.core.orchestration.streaming.streaming_orchestrator import StreamingOrchestrator
from docpipe.integrations.secrets import secret_provider

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


@pytest.mark.parametrize("file_reference", ["vault://regression/event#private", "/documents/report.pdf"])
def test_streaming_resolves_config_secrets_without_resolving_event(*, mocker, monkeypatch, file_reference):
    """Resolve stored credentials while passing runtime event data unchanged to ingest."""
    provider = mocker.Mock(spec=secret_provider.SecretProvider)
    provider.get_secret.side_effect = lambda **kwargs: {
        ("global", "extensions"): "pdf",
        ("node", "path"): "/documents",
    }[(kwargs["path"], kwargs["key"])]
    monkeypatch.setattr(secret_provider, "_providers", {"regression": provider})
    event = InputEvent.model_validate(
        {
            "event_id": "00000000-0000-0000-0000-000000000004",
            "event_timestamp": "2026-11-11T00:00:00Z",
            "routing_key": "documents",
            "operation": "create",
            "file_reference": file_reference,
        }
    )
    flow = {
        "name": "event-secrets-flow",
        "global_config": {"include_filter": "vault://regression/global#extensions", "max_files": 1},
        "dag": [
            _node(
                INGEST_ID,
                "source",
                "ingest_source",
                {
                    "provider": "filesystem",
                    "provider_config": {"paths": ["vault://regression/node#path"]},
                    "max_files": 2,
                },
                [],
                [],
            ),
        ],
    }
    params = {"input_event": event.model_dump(mode="json"), "max_files": 3}
    original_flow, original_params = deepcopy(flow), deepcopy(params)

    def capture_ingest(self, table):
        assert self.input_event == event
        assert self.config["input_event"] == original_params["input_event"]
        assert self.config["provider_config"]["paths"] == ["/documents"]
        assert self.config["include_filter"] == "pdf"
        assert self.config["max_files"] == 3
        return [pa.table({})], {}

    transform = mocker.patch.object(IngestSourceOperator, "transform", autospec=True, side_effect=capture_ingest)

    StreamingOrchestrator().execute(flow=flow, params=params)

    transform.assert_called_once()
    assert provider.get_secret.call_args_list == [call(path="global", key="extensions"), call(path="node", key="path")]
    assert flow == original_flow
    assert params == original_params


@pytest.mark.parametrize(
    ("overrides", "expected_max_files"),
    [
        ({}, 99),
        ({"ingest_source": {"max_files": 3}}, 3),
        ({str(INGEST_ID): {"max_files": 2}, "ingest_source": {"max_files": 3}}, 2),
        ({"source": {"max_files": 1}, str(INGEST_ID): {"max_files": 2}, "ingest_source": {"max_files": 3}}, 1),
        ({"source": {}, str(INGEST_ID): {"max_files": 2}, "ingest_source": {"max_files": 3}}, 99),
    ],
    ids=["node-config", "type", "id-before-type", "name-before-id", "empty-name-override"],
)
@pytest.mark.parametrize("runtime_max_files", [None, 4], ids=["saved-config", "runtime-override"])
def test_streaming_applies_operator_overrides(*, mocker, overrides, expected_max_files, runtime_max_files):
    """Apply saved overrides by name, ID, or type before runtime parameters without mutating the flow."""
    flow = {
        "name": "operator-overrides-flow",
        "global_config": {"max_files": 10, **overrides},
        "dag": [_node(INGEST_ID, "source", "ingest_source", {**INGEST_CONFIG, "max_files": 99}, [], [])],
    }
    params = {} if runtime_max_files is None else {"max_files": runtime_max_files}
    original_flow, original_params = deepcopy(flow), deepcopy(params)

    def capture_ingest(self, table):
        expected = expected_max_files if runtime_max_files is None else runtime_max_files
        assert self.config["max_files"] == expected
        return [pa.table({})], {}

    transform = mocker.patch.object(IngestSourceOperator, "transform", autospec=True, side_effect=capture_ingest)

    StreamingOrchestrator().execute(flow=flow, params=params)

    transform.assert_called_once()
    assert flow == original_flow
    assert params == original_params


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


@pytest.mark.parametrize(
    "result_index, table_count",
    [
        (-1, 2),
        (2, 2),
        ("0", 2),
        (None, 2),
        (0.5, 2),
        (True, 2),
        (False, 2),
        (0, 0),
    ],
)
def test_execution_engine_invalid_branch_result_index(*, result_index, table_count):
    """Reject malformed branch indices instead of selecting an unrelated output or raising a bare index error."""
    graph = FlowGraph()
    graph.add_node(Node(id=NEXT_ID, name="branch_by_format", operator_name="branching", operator_config={}))
    engine = GraphExecutionEngine(flow_graph=graph, ordered_operator_ids=[])
    engine.output_buffer.put_output(
        node_id=NEXT_ID,
        output=OperatorOutput(
            tables=[pa.table({"value": [index]}) for index in range(table_count)],
            metadata={"branches": {"branch_1": {"result_index": result_index}}},
        ),
    )

    message = (
        f"Invalid result index {result_index!r} for branch 'branch_1' in branching node "
        f"'branch_by_format': expected an integer in [0, {table_count})."
    )
    with pytest.raises(ValueError, match=f"^{re.escape(message)}$"):
        engine._get_input_table(source_id=NEXT_ID, branch_id="branch_1")


@pytest.mark.parametrize("result_index", [0, 1])
def test_execution_engine_valid_branch_result_index(result_index):
    """Both ends of the valid index range select the original output table."""
    graph = FlowGraph()
    graph.add_node(Node(id=NEXT_ID, name="branch_by_format", operator_name="branching", operator_config={}))
    engine = GraphExecutionEngine(flow_graph=graph, ordered_operator_ids=[])
    tables = [pa.table({"value": [index]}) for index in range(2)]
    engine.output_buffer.put_output(
        node_id=NEXT_ID,
        output=OperatorOutput(
            tables=tables,
            metadata={"branches": {"branch_1": {"result_index": result_index}}},
        ),
    )

    assert engine._get_input_table(source_id=NEXT_ID, branch_id="branch_1") is tables[result_index]


def test_execution_engine_missing_branch_metadata_raises_value_error(mocker):
    """When a branching operator's metadata does not contain the target branch, ValueError is raised."""
    second_sink_id = UUID("00000000-0000-0000-0000-000000000004")
    flow = {
        "name": "missing-branch-metadata-flow",
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
                "simple_chunker",
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

    def _sample_ingest(self, table, *args, **kwargs):
        doc = {"id": "doc_1", "name": "test.pdf", "document_format": ".pdf"}
        return [pa.Table.from_pylist([doc])], {}

    def _branching_missing_branch(self, table, *args, **kwargs):
        doc = {"id": "doc_1", "name": "test.pdf", "document_format": ".pdf"}
        return [pa.Table.from_pylist([doc])], {OperatorConstants.Misc.BRANCHES: {}}

    mocker.patch.object(IngestSourceOperator, "transform", autospec=True, side_effect=_sample_ingest)
    mocker.patch.object(BranchingOperator, "transform", autospec=True, side_effect=_branching_missing_branch)

    with pytest.raises(ValueError, match=r"Branch 'branch_1' not found in branching node 'branch_by_format'\."):
        StreamingOrchestrator().execute(flow=flow, params={})


def test_execution_engine_missing_result_index_raises_value_error(mocker):
    """When branching metadata for a branch is missing result_index, ValueError is raised."""
    second_sink_id = UUID("00000000-0000-0000-0000-000000000004")
    flow = {
        "name": "missing-result-index-flow",
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
                "simple_chunker",
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

    def _sample_ingest(self, table, *args, **kwargs):
        doc = {"id": "doc_1", "name": "test.pdf", "document_format": ".pdf"}
        return [pa.Table.from_pylist([doc])], {}

    def _branching_missing_index(self, table, *args, **kwargs):
        doc = {"id": "doc_1", "name": "test.pdf", "document_format": ".pdf"}
        return [pa.Table.from_pylist([doc])], {OperatorConstants.Misc.BRANCHES: {"branch_1": {}}}

    mocker.patch.object(IngestSourceOperator, "transform", autospec=True, side_effect=_sample_ingest)
    mocker.patch.object(BranchingOperator, "transform", autospec=True, side_effect=_branching_missing_index)

    with pytest.raises(
        ValueError, match=r"Result index missing for branch 'branch_1' in branching node 'branch_by_format'\."
    ):
        StreamingOrchestrator().execute(flow=flow, params={})
