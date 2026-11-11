# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""StreamFlowValidator coverage."""

import re
from copy import deepcopy
from uuid import UUID

import pytest

from docpipe.core.orchestration.streaming.graph.flow_builder import FlowBuilder
from docpipe.core.orchestration.streaming.graph.flow_model import Edge, FlowGraph, Node
from docpipe.core.orchestration.streaming.graph.stream_flow_validator import StreamFlowValidator

NODE_IDS = [UUID(f"00000000-0000-0000-0000-{index:012d}") for index in range(1, 10)]
BRANCH_CONFIG = {"branches": [{"link_id": "branch_1"}, {"link_id": "branch_2"}]}


def _graph(
    *,
    nodes: list[tuple[UUID, str, str] | tuple[UUID, str, str, dict]],
    edges: list[Edge],
) -> FlowGraph:
    """Build a FlowGraph from (id, name, operator[, config]) tuples and edges."""
    graph = FlowGraph()
    for item in nodes:
        if len(item) == 4:
            node_id, name, operator_name, config = item  # type: ignore[misc]
        else:
            node_id, name, operator_name = item  # type: ignore[misc]
            config = {}
        graph.add_node(Node(id=node_id, name=name, operator_name=operator_name, operator_config=config))
    for edge in edges:
        graph.add_edge(edge)
    return graph


def _exact(message: str) -> str:
    """Return a ``match`` pattern that requires the entire exception message to equal ``message``."""
    return f"^{re.escape(message)}$"


@pytest.fixture
def runtime_flow():
    """Provide a compiled runtime definition with all fields needed for graph construction."""
    return {"dag": [{"id": str(NODE_IDS[0]), "name": "source", "operator": "ingest_source", "output_edges": []}]}


class TestStreamFlowValidatorJson:
    """Validate raw data that graph construction parses or could overwrite."""

    def test_valid_definition_passes(self, runtime_flow):
        original = deepcopy(runtime_flow)
        StreamFlowValidator.validate_json(flow=runtime_flow)
        assert runtime_flow == original

    @pytest.mark.parametrize("flow", [None, [], {}, {"dag": None}, {"dag": {}}, {"dag": []}, {"dag": [None]}])
    def test_invalid_dag_fails(self, flow):
        with pytest.raises(ValueError, match=r"(flow|DAG|node)"):
            StreamFlowValidator.validate_json(flow=flow)

    @pytest.mark.parametrize("field", ["id", "name", "operator"])
    @pytest.mark.parametrize("value", [None, "", " ", 1])
    def test_invalid_required_fields_fail(self, *, runtime_flow, field, value):
        runtime_flow["dag"][0][field] = value
        with pytest.raises(ValueError, match=_exact(f"Node at index 0 requires a nonempty string '{field}'.")):
            StreamFlowValidator.validate_json(flow=runtime_flow)

    def test_invalid_node_uuid_fails(self, runtime_flow):
        runtime_flow["dag"][0]["id"] = "invalid-uuid"
        with pytest.raises(ValueError, match="invalid UUID"):
            StreamFlowValidator.validate_json(flow=runtime_flow)

    @pytest.mark.parametrize("duplicate_id", [str(NODE_IDS[0]), NODE_IDS[0].hex])
    def test_duplicate_node_identities_fail(self, *, runtime_flow, duplicate_id):
        duplicate = {**runtime_flow["dag"][0], "id": duplicate_id, "name": "duplicate"}
        runtime_flow["dag"].append(duplicate)
        with pytest.raises(ValueError, match=_exact(f"Duplicate node id: '{NODE_IDS[0]}'.")):
            StreamFlowValidator.validate_json(flow=runtime_flow)

    @pytest.mark.parametrize(
        "edges",
        [
            None,
            {},
            [None],
            [{}],
            [{"node_id_ref": 1}],
            [{"node_id_ref": "invalid"}],
            [{"node_id_ref": str(NODE_IDS[0]), "link_name": []}],
        ],
    )
    def test_invalid_edge_fields_fail(self, *, runtime_flow, edges):
        runtime_flow["dag"][0]["output_edges"] = edges
        with pytest.raises(ValueError, match=r"(output_edges|node_id_ref|link_name)"):
            StreamFlowValidator.validate_json(flow=runtime_flow)

    def test_unknown_target_is_left_for_graph_validation(self, runtime_flow):
        runtime_flow["dag"][0]["output_edges"] = [{"node_id_ref": str(NODE_IDS[1])}]
        StreamFlowValidator.validate_json(flow=runtime_flow)
        with pytest.raises(ValueError, match="Connection references an unknown node"):
            FlowBuilder(flow=runtime_flow, params={}).build_graph()

    @pytest.mark.parametrize("value", [[], "invalid", 1])
    @pytest.mark.parametrize("level", ["global_config", "config"])
    def test_invalid_configuration_shapes_fail(self, *, runtime_flow, level, value):
        container = runtime_flow if level == "global_config" else runtime_flow["dag"][0]
        container[level] = value
        with pytest.raises(ValueError, match="must be an object"):
            StreamFlowValidator.validate_json(flow=runtime_flow)

    def test_builder_validates_json_before_constructing_graph(self, *, runtime_flow, mocker):
        runtime_flow["dag"].append({**runtime_flow["dag"][0], "id": NODE_IDS[0].hex})
        graph_class = mocker.patch("docpipe.core.orchestration.streaming.graph.flow_builder.FlowGraph")
        with pytest.raises(ValueError, match="Duplicate node id"):
            FlowBuilder(flow=runtime_flow, params={}).build_graph()
        graph_class.assert_not_called()


class TestStreamFlowValidatorGraph:
    """Each validation block has a passing test followed by its failing test."""

    @pytest.mark.parametrize(
        "root_operator, error",
        [
            ("chunker", "Root node 'source' must be an ingest operator"),
            ("ingest_source", "Branching node 'branch' requires at least two configured branches"),
        ],
    )
    def test_root_and_branch_checks_precede_merge_checks(self, *, root_operator, error):
        """Report the root first, then branching, before a merge with too few inputs."""
        graph = _graph(
            nodes=[
                (NODE_IDS[0], "source", root_operator),
                (NODE_IDS[1], "branch", "branching"),
                (NODE_IDS[2], "merge", "merge"),
            ],
            edges=[
                Edge(source_id=NODE_IDS[0], target_id=NODE_IDS[1]),
                Edge(source_id=NODE_IDS[1], target_id=NODE_IDS[2], branch_id="route"),
            ],
        )
        with pytest.raises(ValueError, match=re.escape(error)):
            StreamFlowValidator.validate_graph(flow_graph=graph)

    def test_graph_with_nodes_passes(self):
        """A graph with at least one node is accepted."""
        graph = _graph(nodes=[(NODE_IDS[0], "ingest_source_filesystem", "ingest_source")], edges=[])

        StreamFlowValidator.validate_graph(flow_graph=graph)

    def test_graph_without_nodes_fails(self):
        """A graph with no nodes is rejected."""
        graph = _graph(nodes=[], edges=[])

        with pytest.raises(ValueError, match=_exact("A flow must have exactly one root node, found 0.")):
            StreamFlowValidator.validate_graph(flow_graph=graph)

    def test_edges_between_known_nodes_pass(self):
        """Edges whose source and target are both in the graph are accepted."""
        graph = _graph(
            nodes=[
                (NODE_IDS[0], "ingest_source_filesystem", "ingest_source"),
                (NODE_IDS[1], "extract_with_docling", "extract_operator"),
            ],
            edges=[Edge(source_id=NODE_IDS[0], target_id=NODE_IDS[1])],
        )

        StreamFlowValidator.validate_graph(flow_graph=graph)

    def test_edge_to_unknown_node_fails(self):
        """An edge whose target is not in the graph is rejected."""
        graph = _graph(
            nodes=[(NODE_IDS[0], "ingest_source_filesystem", "ingest_source")],
            edges=[Edge(source_id=NODE_IDS[0], target_id=NODE_IDS[1])],
        )

        with pytest.raises(
            ValueError,
            match=_exact(f"Connection references an unknown node: '{NODE_IDS[0]}' -> '{NODE_IDS[1]}'."),
        ):
            StreamFlowValidator.validate_graph(flow_graph=graph)

    def test_branching_edges_with_branch_ids_pass(self):
        """Every output edge of a branching node carries a branch ID."""
        graph = _graph(
            nodes=[
                (NODE_IDS[0], "ingest_source_filesystem", "ingest_source"),
                (NODE_IDS[1], "branch_by_format", "branching", BRANCH_CONFIG),
                (NODE_IDS[2], "simple_chunker_1", "chunker"),
                (NODE_IDS[3], "simple_chunker_2", "chunker"),
            ],
            edges=[
                Edge(source_id=NODE_IDS[0], target_id=NODE_IDS[1]),
                Edge(source_id=NODE_IDS[1], target_id=NODE_IDS[2], branch_id="branch_1"),
                Edge(source_id=NODE_IDS[1], target_id=NODE_IDS[3], branch_id="branch_2"),
            ],
        )

        StreamFlowValidator.validate_graph(flow_graph=graph)

    def test_single_configured_branch_fails(self):
        """A branching node must split into at least two configured routes."""
        graph = _graph(
            nodes=[
                (NODE_IDS[0], "source", "ingest_source"),
                (NODE_IDS[1], "branch", "branching", {"branches": [{"link_id": "only"}]}),
                (NODE_IDS[2], "sink", "chunker"),
            ],
            edges=[
                Edge(source_id=NODE_IDS[0], target_id=NODE_IDS[1]),
                Edge(source_id=NODE_IDS[1], target_id=NODE_IDS[2], branch_id="only"),
            ],
        )
        with pytest.raises(
            ValueError, match=_exact("Branching node 'branch' requires at least two configured branches.")
        ):
            StreamFlowValidator.validate_graph(flow_graph=graph)

    @pytest.mark.parametrize("operator", ["ingest_source", "chunker", "merge"])
    def test_non_branching_fan_out_fails_before_operator_specific_checks(self, operator):
        """Only branching nodes may have multiple outputs, including before merge-specific checks."""
        source_id = NODE_IDS[0] if operator == "ingest_source" else NODE_IDS[1]
        nodes: list[tuple[UUID, str, str] | tuple[UUID, str, str, dict]] = [(NODE_IDS[0], "source", "ingest_source")]
        edges = []
        if source_id != NODE_IDS[0]:
            nodes.append((source_id, "fan_out", operator))
            edges.append(Edge(source_id=NODE_IDS[0], target_id=source_id))
        nodes.extend([(NODE_IDS[2], "sink_1", "chunker"), (NODE_IDS[3], "sink_2", "chunker")])
        edges.extend(
            [Edge(source_id=source_id, target_id=NODE_IDS[2]), Edge(source_id=source_id, target_id=NODE_IDS[3])]
        )
        graph = _graph(nodes=nodes, edges=edges)
        with pytest.raises(ValueError, match="cannot have multiple outgoing edges"):
            StreamFlowValidator.validate_graph(flow_graph=graph)

    def test_branching_edge_without_branch_id_fails(self):
        """An output edge of a branching node without a branch ID is rejected."""
        graph = _graph(
            nodes=[
                (NODE_IDS[0], "ingest_source_filesystem", "ingest_source"),
                (NODE_IDS[1], "branch_by_format", "branching", BRANCH_CONFIG),
                (NODE_IDS[2], "simple_chunker_1", "chunker"),
                (NODE_IDS[3], "simple_chunker_2", "chunker"),
            ],
            edges=[
                Edge(source_id=NODE_IDS[0], target_id=NODE_IDS[1]),
                Edge(source_id=NODE_IDS[1], target_id=NODE_IDS[2], branch_id="branch_1"),
                Edge(source_id=NODE_IDS[1], target_id=NODE_IDS[3]),
            ],
        )

        with pytest.raises(
            ValueError,
            match=_exact("Branching node 'branch_by_format' configured branch IDs do not match outgoing edges."),
        ):
            StreamFlowValidator.validate_graph(flow_graph=graph)

    @pytest.mark.parametrize(
        "branches",
        [
            None,
            [],
            {},
            [{"link_name": "route"}, {"link_id": "valid"}],
            [None, {"link_id": "valid"}],
            [{"link_id": 1}, {"link_id": "valid"}],
        ],
    )
    def test_invalid_configured_branches_fail(self, branches):
        """Malformed branch definitions fail with a configuration error before execution."""
        graph = _graph(
            nodes=[
                (NODE_IDS[0], "source", "ingest_source"),
                (NODE_IDS[1], "branch_by_format", "branching", {"branches": branches}),
                (NODE_IDS[2], "sink", "chunker"),
            ],
            edges=[
                Edge(source_id=NODE_IDS[0], target_id=NODE_IDS[1]),
                Edge(source_id=NODE_IDS[1], target_id=NODE_IDS[2], branch_id="branch_1"),
            ],
        )

        with pytest.raises(ValueError, match=r"branch_by_format.*(configured branches|link_id)"):
            StreamFlowValidator.validate_graph(flow_graph=graph)

    @pytest.mark.parametrize(
        "configured_ids, routes, error",
        [
            (["branch_1", "branch_1"], [("branch_1", 2)], "has duplicate configured branch ID 'branch_1'."),
            (["branch_1", "branch_2"], [("unknown", 2)], "configured branch IDs do not match outgoing edges."),
            (["branch_1", "branch_2"], [("branch_1", 2)], "configured branch IDs do not match outgoing edges."),
            (["branch_1", "branch_2"], [], "configured branch IDs do not match outgoing edges."),
            (
                ["branch_1", "branch_2"],
                [("branch_1", 2), ("branch_1", 3)],
                "must connect each branch ID to exactly one output edge.",
            ),
            (
                ["branch_1", "branch_2"],
                [("branch_1", 2), ("branch_2", 2)],
                "must connect each branch to a distinct downstream node.",
            ),
        ],
    )
    def test_branch_routes_must_map_one_to_one(self, *, configured_ids, routes, error):
        """Reject unknown, disconnected, duplicate, or converging branch routes."""
        graph = _graph(
            nodes=[
                (NODE_IDS[0], "source", "ingest_source"),
                (
                    NODE_IDS[1],
                    "branch_by_format",
                    "branching",
                    {
                        "branches": [{"link_id": branch_id} for branch_id in configured_ids],
                    },
                ),
                *[
                    (
                        NODE_IDS[index],
                        f"sink_{index}",
                        "merge" if sum(target == index for _, target in routes) > 1 else "chunker",
                    )
                    for index in sorted({index for _, index in routes})
                ],
            ],
            edges=[
                Edge(source_id=NODE_IDS[0], target_id=NODE_IDS[1]),
                *[Edge(source_id=NODE_IDS[1], target_id=NODE_IDS[index], branch_id=key) for key, index in routes],
            ],
        )

        with pytest.raises(ValueError, match=_exact(f"Branching node 'branch_by_format' {error}")):
            StreamFlowValidator.validate_graph(flow_graph=graph)

    def test_merge_with_multiple_inputs_and_single_input_nodes_pass(self):
        """A merge node takes two inputs matching its input_links while every other node takes at most one."""
        merge_config = {
            "input_links": [
                {"node_id_ref": str(NODE_IDS[2]), "link_name": "ollama_embeddings_1"},
                {"node_id_ref": str(NODE_IDS[3]), "link_name": "ollama_embeddings_2"},
            ]
        }
        graph = _graph(
            nodes=[
                (NODE_IDS[0], "ingest_source_filesystem", "ingest_source"),
                (NODE_IDS[1], "branch_by_format", "branching", BRANCH_CONFIG),
                (NODE_IDS[2], "ollama_embeddings_1", "embeddings"),
                (NODE_IDS[3], "ollama_embeddings_2", "embeddings"),
                (NODE_IDS[4], "merge_branches", "merge", merge_config),
                (NODE_IDS[5], "opensearch_vector_store", "vectordb"),
            ],
            edges=[
                Edge(source_id=NODE_IDS[0], target_id=NODE_IDS[1]),
                Edge(source_id=NODE_IDS[1], target_id=NODE_IDS[2], branch_id="branch_1"),
                Edge(source_id=NODE_IDS[1], target_id=NODE_IDS[3], branch_id="branch_2"),
                Edge(source_id=NODE_IDS[2], target_id=NODE_IDS[4]),
                Edge(source_id=NODE_IDS[3], target_id=NODE_IDS[4]),
                Edge(source_id=NODE_IDS[4], target_id=NODE_IDS[5]),
            ],
        )

        StreamFlowValidator.validate_graph(flow_graph=graph)

    def test_merge_input_links_mismatch_fails(self):
        """A merge node whose input_links do not match its incoming edges is rejected."""
        mismatched_merge_config = {
            "input_links": [
                {"node_id_ref": str(NODE_IDS[2]), "link_name": "ollama_embeddings_1"},
                {"node_id_ref": str(NODE_IDS[5]), "link_name": "unknown_source"},
            ]
        }
        graph = _graph(
            nodes=[
                (NODE_IDS[0], "ingest_source_filesystem", "ingest_source"),
                (NODE_IDS[1], "branch_by_format", "branching", BRANCH_CONFIG),
                (NODE_IDS[2], "ollama_embeddings_1", "embeddings"),
                (NODE_IDS[3], "ollama_embeddings_2", "embeddings"),
                (NODE_IDS[4], "merge_branches", "merge", mismatched_merge_config),
            ],
            edges=[
                Edge(source_id=NODE_IDS[0], target_id=NODE_IDS[1]),
                Edge(source_id=NODE_IDS[1], target_id=NODE_IDS[2], branch_id="branch_1"),
                Edge(source_id=NODE_IDS[1], target_id=NODE_IDS[3], branch_id="branch_2"),
                Edge(source_id=NODE_IDS[2], target_id=NODE_IDS[4]),
                Edge(source_id=NODE_IDS[3], target_id=NODE_IDS[4]),
            ],
        )
        with pytest.raises(
            ValueError, match=_exact("Merge node 'merge_branches' input_links do not match incoming edges.")
        ):
            StreamFlowValidator.validate_graph(flow_graph=graph)

    def test_merge_and_non_merge_input_counts_fail(self):
        """A merge node with one input and a non-merge node with two inputs are both rejected."""
        single_input_merge = _graph(
            nodes=[
                (NODE_IDS[0], "ingest_source_filesystem", "ingest_source"),
                (NODE_IDS[1], "merge_branches", "merge"),
            ],
            edges=[Edge(source_id=NODE_IDS[0], target_id=NODE_IDS[1])],
        )
        with pytest.raises(
            ValueError, match=_exact("Merge node 'merge_branches' requires at least two incoming edges.")
        ):
            StreamFlowValidator.validate_graph(flow_graph=single_input_merge)

        multi_input_non_merge = _graph(
            nodes=[
                (NODE_IDS[0], "ingest_source_filesystem", "ingest_source"),
                (NODE_IDS[1], "branch_by_format", "branching", BRANCH_CONFIG),
                (NODE_IDS[2], "ollama_embeddings_1", "embeddings"),
                (NODE_IDS[3], "ollama_embeddings_2", "embeddings"),
                (NODE_IDS[4], "opensearch_vector_store", "vectordb"),
            ],
            edges=[
                Edge(source_id=NODE_IDS[0], target_id=NODE_IDS[1]),
                Edge(source_id=NODE_IDS[1], target_id=NODE_IDS[2], branch_id="branch_1"),
                Edge(source_id=NODE_IDS[1], target_id=NODE_IDS[3], branch_id="branch_2"),
                Edge(source_id=NODE_IDS[2], target_id=NODE_IDS[4]),
                Edge(source_id=NODE_IDS[3], target_id=NODE_IDS[4]),
            ],
        )
        with pytest.raises(
            ValueError,
            match=_exact("Non-merge node 'opensearch_vector_store' cannot have multiple incoming edges."),
        ):
            StreamFlowValidator.validate_graph(flow_graph=multi_input_non_merge)

    def test_multiple_roots_fail(self):
        # A flow with more than one root node is rejected.
        graph = _graph(
            nodes=[
                (NODE_IDS[0], "ingest_1", "ingest_source"),
                (NODE_IDS[1], "ingest_2", "ingest_source"),
            ],
            edges=[],
        )
        with pytest.raises(ValueError, match=_exact("A flow must have exactly one root node, found 2.")):
            StreamFlowValidator.validate_graph(flow_graph=graph)

    def test_non_ingest_root_fails(self):
        # A flow whose root node is not an ingest operator is rejected.
        graph = _graph(
            nodes=[
                (NODE_IDS[0], "simple_chunker", "chunker"),
            ],
            edges=[],
        )
        with pytest.raises(
            ValueError, match=_exact("Root node 'simple_chunker' must be an ingest operator, found 'chunker'.")
        ):
            StreamFlowValidator.validate_graph(flow_graph=graph)


def test_flow_graph_internal_fields_not_in_init():
    # Internal adjacency indexes are not exposed in FlowGraph init or repr.
    import inspect

    sig = inspect.signature(FlowGraph)
    assert "_in_edges" not in sig.parameters
    assert "_out_edges" not in sig.parameters

    graph = FlowGraph()
    repr_str = repr(graph)
    assert "_in_edges" not in repr_str
    assert "_out_edges" not in repr_str
