# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Validation for flow graphs."""

from typing import Any
from uuid import UUID

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.orchestration.streaming.graph.flow_model import FlowGraph


class StreamFlowValidator:
    """Validate graph structure."""

    @staticmethod
    def validate(*, flow_graph: FlowGraph, flow: dict[str, Any] | None = None) -> None:
        """Validate the completed graph's nodes and edge endpoints."""

        # Ensure flow definition contains no duplicate node IDs.
        if flow is not None:
            flow_dag: list[dict[str, Any]] = flow.get(DocpipeConstants.DAG, [])
            if len(flow_dag) != len(flow_graph.nodes):
                seen_ids: set[str] = set()
                for operator in flow_dag:
                    node_id = str(operator.get(OperatorConstants.Misc.ID))
                    if node_id in seen_ids:
                        raise ValueError(f"Duplicate node id: '{node_id}'.")
                    seen_ids.add(node_id)

        # Ensure the parsed graph contains at least one node.
        if not flow_graph.nodes:
            raise ValueError("A flow must contain at least one node.")

        # Ensure every graph edge points to nodes present in the graph.
        for edge in flow_graph.edges:
            if edge.source_id not in flow_graph.nodes or edge.target_id not in flow_graph.nodes:
                raise ValueError(f"Connection references an unknown node: '{edge.source_id}' -> '{edge.target_id}'.")

        # Ensure every output edge from a branching operator has a branch ID.
        for node in flow_graph.nodes.values():
            if node.operator_name == OperatorConstants.Operators.BRANCHING:
                for edge in flow_graph.get_output_edges(node.id):
                    if not edge.branch_id:
                        raise ValueError(f"Output edge from branching node '{node.name}' requires a branch ID.")

        # Merge nodes require multiple inputs; other nodes accept at most one.
        for node in flow_graph.nodes.values():
            input_edges = flow_graph.get_input_edges(node.id)
            input_count = len(input_edges)
            if node.operator_name == OperatorConstants.Operators.MERGE:
                if input_count < 2:
                    raise ValueError(f"Merge node '{node.name}' requires at least two incoming edges.")

                # Ensure merge input links in operator config exactly match the incoming graph edges.
                input_links = node.operator_config.get(OperatorConstants.Merge.INPUT_LINKS, [])
                incoming_source_ids = {edge.source_id for edge in input_edges}
                configured_source_ids = {
                    UUID(link[DocpipeConstants.NODE_ID_REF])
                    for link in input_links
                    if DocpipeConstants.NODE_ID_REF in link
                }
                if incoming_source_ids != configured_source_ids:
                    raise ValueError(f"Merge node '{node.name}' input_links do not match incoming edges.")
            elif input_count > 1:
                raise ValueError(f"Non-merge node '{node.name}' cannot have multiple incoming edges.")
