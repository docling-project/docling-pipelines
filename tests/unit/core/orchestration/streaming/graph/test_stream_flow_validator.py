# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""StreamFlowValidator coverage."""

import re
from uuid import UUID

import pytest

from docpipe.core.orchestration.streaming.graph.flow_model import Edge, FlowGraph, Node
from docpipe.core.orchestration.streaming.graph.stream_flow_validator import StreamFlowValidator

NODE_IDS = [UUID(f"00000000-0000-0000-0000-{index:012d}") for index in range(1, 10)]


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


class TestStreamFlowValidator:
    """Each validation block has a passing test followed by its failing test."""

    def test_graph_with_nodes_passes(self):
        """A graph with at least one node is accepted."""
        graph = _graph(nodes=[(NODE_IDS[0], "ingest_source_filesystem", "ingest_source")], edges=[])

        StreamFlowValidator.validate(flow_graph=graph)

    def test_graph_without_nodes_fails(self):
        """A graph with no nodes is rejected."""
        graph = _graph(nodes=[], edges=[])

        with pytest.raises(ValueError, match=_exact("A flow must contain at least one node.")):
            StreamFlowValidator.validate(flow_graph=graph)

    def test_edges_between_known_nodes_pass(self):
        """Edges whose source and target are both in the graph are accepted."""
        graph = _graph(
            nodes=[
                (NODE_IDS[0], "ingest_source_filesystem", "ingest_source"),
                (NODE_IDS[1], "extract_with_docling", "extract_operator"),
            ],
            edges=[Edge(source_id=NODE_IDS[0], target_id=NODE_IDS[1])],
        )

        StreamFlowValidator.validate(flow_graph=graph)

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
            StreamFlowValidator.validate(flow_graph=graph)

    def test_branching_edges_with_branch_ids_pass(self):
        """Every output edge of a branching node carries a branch ID."""
        graph = _graph(
            nodes=[
                (NODE_IDS[0], "ingest_source_filesystem", "ingest_source"),
                (NODE_IDS[1], "branch_by_format", "branching"),
                (NODE_IDS[2], "simple_chunker_1", "chunker"),
                (NODE_IDS[3], "simple_chunker_2", "chunker"),
            ],
            edges=[
                Edge(source_id=NODE_IDS[0], target_id=NODE_IDS[1]),
                Edge(source_id=NODE_IDS[1], target_id=NODE_IDS[2], branch_id="branch_1"),
                Edge(source_id=NODE_IDS[1], target_id=NODE_IDS[3], branch_id="branch_2"),
            ],
        )

        StreamFlowValidator.validate(flow_graph=graph)

    def test_branching_edge_without_branch_id_fails(self):
        """An output edge of a branching node without a branch ID is rejected."""
        graph = _graph(
            nodes=[
                (NODE_IDS[0], "ingest_source_filesystem", "ingest_source"),
                (NODE_IDS[1], "branch_by_format", "branching"),
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
            ValueError, match=_exact("Output edge from branching node 'branch_by_format' requires a branch ID.")
        ):
            StreamFlowValidator.validate(flow_graph=graph)

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
                (NODE_IDS[1], "branch_by_format", "branching"),
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

        StreamFlowValidator.validate(flow_graph=graph)

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
                (NODE_IDS[1], "branch_by_format", "branching"),
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
            StreamFlowValidator.validate(flow_graph=graph)

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
            StreamFlowValidator.validate(flow_graph=single_input_merge)

        multi_input_non_merge = _graph(
            nodes=[
                (NODE_IDS[0], "ingest_source_filesystem", "ingest_source"),
                (NODE_IDS[1], "branch_by_format", "branching"),
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
            StreamFlowValidator.validate(flow_graph=multi_input_non_merge)

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
            StreamFlowValidator.validate(flow_graph=graph)

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
            StreamFlowValidator.validate(flow_graph=graph)

    def test_duplicate_node_ids_in_flow_fail(self):
        # A flow containing duplicate node IDs is rejected.
        graph = _graph(
            nodes=[
                (NODE_IDS[0], "node_1", "ingest_source"),
            ],
            edges=[],
        )
        flow = {
            "dag": [
                {"id": str(NODE_IDS[0]), "name": "node_1", "operator": "ingest_source"},
                {"id": str(NODE_IDS[0]), "name": "node_2", "operator": "ingest_source"},
            ]
        }
        with pytest.raises(ValueError, match=_exact(f"Duplicate node id: '{NODE_IDS[0]}'.")):
            StreamFlowValidator.validate(flow_graph=graph, flow=flow)


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
