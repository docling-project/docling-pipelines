# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Parser converting a compiled runtime flow into a FlowGraph."""

from graphlib import TopologicalSorter
from typing import Any
from uuid import UUID

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.orchestration.streaming.graph.flow_model import Edge, FlowGraph, Node
from docpipe.core.orchestration.streaming.graph.flow_validator import FlowValidator


class FlowBuilder:
    """Build a FlowGraph from a compiled runtime flow and runtime parameters."""

    def __init__(self, *, flow: dict[str, Any], params: dict[str, Any]) -> None:
        self.flow: dict[str, Any] = flow
        self.params: dict[str, Any] = params

    def build_graph(self) -> FlowGraph:
        """Parse runtime operators and connections, then validate the graph."""
        flow_dag: list[dict] = self.flow[DocpipeConstants.DAG]

        flow_graph: FlowGraph = FlowGraph()
        for operator in flow_dag:
            config: dict = {
                **(self.flow.get("global_config") or {}),
                **(operator.get("config") or {}),
                **self.params,
                DocpipeConstants.NODE_ID: operator["id"],
                DocpipeConstants.NODE_NAME: operator["name"],
            }

            node: Node = Node(
                id=UUID(operator["id"]),
                name=operator["name"],
                operator_name=operator["operator"],
                operator_config=config,
            )
            flow_graph.add_node(node=node)

        for operator in flow_dag:
            for output_edge in operator["output_edges"]:
                edge = Edge(
                    source_id=UUID(operator["id"]),
                    target_id=UUID(output_edge["node_id_ref"]),
                    branch_id=output_edge.get(DocpipeConstants.LINK_NAME, None),
                )
                flow_graph.add_edge(edge=edge)

        FlowValidator.validate(flow_graph=flow_graph)
        return flow_graph

    @staticmethod
    def sort_graph(flow_graph: FlowGraph) -> list[UUID]:
        """Order nodes by their dependencies and reject cycles before execution."""
        dependencies = {
            node_id: [edge.source_id for edge in flow_graph.get_input_edges(node_id)] for node_id in flow_graph.nodes
        }
        return list(TopologicalSorter(graph=dependencies).static_order())
