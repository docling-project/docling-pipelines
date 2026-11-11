# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Parser converting a compiled runtime flow into a FlowGraph."""

from graphlib import CycleError, TopologicalSorter
from typing import Any
from uuid import UUID

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.orchestration.streaming.graph.flow_model import Edge, FlowGraph, Node
from docpipe.core.orchestration.streaming.graph.flow_validator import FlowValidator


class FlowBuilder:
    """Build a FlowGraph from a compiled runtime flow and runtime parameters."""

    def __init__(self, *, flow: dict[str, Any], params: dict[str, Any]) -> None:
        self.flow: dict[str, Any] = flow
        self.params: dict[str, Any] = params

    def build_graph(self) -> FlowGraph:
        """Parse runtime operators and connections, then validate the graph.

        Configuration is merged with precedence:
        flow[global_config] < operator[config] < runtime params.
        """
        flow_dag: list[dict] = self.flow[DocpipeConstants.DAG]

        flow_graph: FlowGraph = FlowGraph()
        for operator in flow_dag:
            config: dict = {
                **(self.flow.get(OperatorConstants.Config.GLOBAL_CONFIG) or {}),
                **(operator.get(OperatorConstants.Config.CONFIG) or {}),
                **self.params,
                DocpipeConstants.NODE_ID: operator[OperatorConstants.Misc.ID],
                DocpipeConstants.NODE_NAME: operator[OperatorConstants.Misc.NAME],
            }

            node: Node = Node(
                id=UUID(operator[OperatorConstants.Misc.ID]),
                name=operator[OperatorConstants.Misc.NAME],
                operator_name=operator[OperatorConstants.Misc.OPERATOR],
                operator_config=config,
            )
            flow_graph.add_node(node=node)

        for operator in flow_dag:
            for output_edge in operator[DocpipeConstants.OUTPUT_EDGES]:
                edge = Edge(
                    source_id=UUID(operator[OperatorConstants.Misc.ID]),
                    target_id=UUID(output_edge[DocpipeConstants.NODE_ID_REF]),
                    branch_id=output_edge.get(DocpipeConstants.LINK_NAME, None),
                )
                flow_graph.add_edge(edge=edge)

        FlowValidator.validate(flow_graph=flow_graph, flow=self.flow)
        return flow_graph

    @staticmethod
    def sort_graph(*, flow_graph: FlowGraph) -> list[UUID]:
        """Order nodes by their dependencies and reject cycles before execution."""
        dependencies = {
            node_id: [edge.source_id for edge in flow_graph.get_input_edges(node_id)] for node_id in flow_graph.nodes
        }
        try:
            return list(TopologicalSorter(graph=dependencies).static_order())
        except CycleError as err:
            cycle_nodes = [flow_graph.nodes[node_id].name for node_id in err.args[1]]
            raise ValueError(f"Cycle detected in flow graph: {' -> '.join(cycle_nodes)}.") from err
