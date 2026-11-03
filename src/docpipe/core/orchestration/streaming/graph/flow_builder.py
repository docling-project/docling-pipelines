# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Parser converting a compiled runtime flow into a FlowGraph."""

from copy import deepcopy
from graphlib import TopologicalSorter
from uuid import UUID

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.orchestration.flow_validator import FlowValidator as FlowFeatureValidator
from docpipe.core.orchestration.python.python_orchestrator import PythonOrchestrator
from docpipe.core.orchestration.streaming.graph.flow_model import Edge, FlowGraph, Node
from docpipe.core.orchestration.streaming.graph.flow_validator import FlowValidator
from docpipe.integrations.secrets.secret_provider import resolve_value


class FlowBuilder:
    """Enrich a compiled runtime flow and build its FlowGraph."""

    def __init__(self, *, flow: dict, params: dict):
        self.flow: dict = flow
        self.params: dict = params

    def build_graph(self) -> FlowGraph:
        """Parse runtime operators and connections, then validate the graph."""
        enriched_flow = self._flow_enrich()
        flow_dag: list[dict] = enriched_flow[DocpipeConstants.DAG]

        flow_graph: FlowGraph = FlowGraph()
        branch_ids = {operator["id"]: operator.get(OperatorConstants.Misc.LINK_ID) for operator in flow_dag}
        for operator in flow_dag:
            node: Node = Node(
                id=UUID(operator["id"]),
                name=operator["name"],
                operator_name=operator["operator"],
                operator_config=operator["config"],
            )
            flow_graph.add_node(node=node)

            for output_edge in operator["output_edges"]:
                edge = Edge(
                    source_id=node.id,
                    target_id=UUID(output_edge["node_id_ref"]),
                    branch_id=branch_ids[output_edge["node_id_ref"]],
                )
                flow_graph.add_edge(edge=edge)

        FlowValidator.validate(flow_graph=flow_graph)
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
                DocpipeConstants.NODE_ID: operator["id"],
                DocpipeConstants.NODE_NAME: operator["name"],
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
            snapshot = propagated_node_features.get(operator["id"], {})
            available_features = snapshot.get("available_features", {})
            if available_features:
                operator_config = operator[OperatorConstants.Config.CONFIG]
                operator_config[OperatorConstants.Config.AVAILABLE_FEATURES] = available_features

        return enriched_flow

    @staticmethod
    def sort_graph(flow_graph: FlowGraph) -> list[UUID]:
        """Order nodes by their dependencies and reject cycles before execution."""
        dependencies = {
            node_id: [edge.source_id for edge in flow_graph.get_input_edges(node_id)] for node_id in flow_graph.nodes
        }
        return list(TopologicalSorter(graph=dependencies).static_order())
