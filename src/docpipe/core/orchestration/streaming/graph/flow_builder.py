# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Parser converting a compiled runtime flow into a FlowGraph."""

from copy import deepcopy
from graphlib import CycleError, TopologicalSorter
from typing import Any
from uuid import UUID

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.orchestration.flow_validator import FlowValidator as FlowFeatureValidator
from docpipe.core.orchestration.python.python_orchestrator import PythonOrchestrator
from docpipe.core.orchestration.streaming.graph.flow_model import Edge, FlowGraph, Node
from docpipe.core.orchestration.streaming.graph.stream_flow_validator import StreamFlowValidator
from docpipe.integrations.secrets.secret_provider import resolve_value


class FlowBuilder:
    """Enrich a compiled runtime flow and build its FlowGraph."""

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
        branch_ids = {operator["id"]: operator.get(OperatorConstants.Misc.LINK_ID) for operator in flow_dag}
        for operator in flow_dag:
            node: Node = Node(
                id=UUID(operator[OperatorConstants.Misc.ID]),
                name=operator[OperatorConstants.Misc.NAME],
                operator_name=operator[OperatorConstants.Misc.OPERATOR],
                operator_config=operator.get(OperatorConstants.Config.CONFIG) or {},
            )
            flow_graph.add_node(node=node)

        for operator in flow_dag:
            for output_edge in operator[DocpipeConstants.OUTPUT_EDGES]:
                edge = Edge(
                    source_id=UUID(operator[OperatorConstants.Misc.ID]),
                    target_id=UUID(output_edge[DocpipeConstants.NODE_ID_REF]),
                    branch_id=branch_ids.get(output_edge[DocpipeConstants.NODE_ID_REF])
                    or output_edge.get(DocpipeConstants.LINK_NAME, None),
                )
                flow_graph.add_edge(edge=edge)

        StreamFlowValidator.validate(flow_graph=flow_graph, flow=self.flow)
        FlowBuilder.sort_graph(flow_graph=flow_graph)

        enriched_flow = self._flow_enrich()
        for operator in enriched_flow[DocpipeConstants.DAG]:
            node_id = UUID(operator[OperatorConstants.Misc.ID])
            flow_graph.nodes[node_id].operator_config = operator[OperatorConstants.Config.CONFIG]

        return flow_graph

    def _flow_enrich(self) -> dict:
        """Return an isolated flow with effective configuration, credentials, and feature metadata."""
        # Merge global, node, and runtime configuration without modifying the supplied flow.
        enriched_flow = deepcopy(self.flow)
        flow_dag = enriched_flow[DocpipeConstants.DAG]
        global_config = enriched_flow.get(OperatorConstants.Config.GLOBAL_CONFIG) or {}
        for operator in flow_dag:
            operator[OperatorConstants.Config.CONFIG] = {
                **global_config,
                **(operator.get(OperatorConstants.Config.CONFIG) or {}),
                **self.params,
                DocpipeConstants.NODE_ID: operator[OperatorConstants.Misc.ID],
                DocpipeConstants.NODE_NAME: operator[OperatorConstants.Misc.NAME],
                DocpipeConstants.FORCE_INGEST: True,
            }

        # Resolve Vault references in the effective configuration before feature propagation.
        for operator in flow_dag:
            operator[OperatorConstants.Config.CONFIG] = resolve_value(operator[OperatorConstants.Config.CONFIG])

        # Propagate features and populate the metadata required by downstream operators.
        propagated_node_features = FlowFeatureValidator(orchestrator=PythonOrchestrator()).propagate_features_per_node(
            flow_def=enriched_flow, global_config=global_config
        )
        for operator in flow_dag:
            snapshot = propagated_node_features.get(operator[OperatorConstants.Misc.ID], {})
            available_features = snapshot.get("available_features", {})
            if available_features:
                operator_config = operator[OperatorConstants.Config.CONFIG]
                operator_config[OperatorConstants.Config.AVAILABLE_FEATURES] = available_features

        return enriched_flow

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
