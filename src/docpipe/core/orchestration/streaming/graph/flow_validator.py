# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Validation for flow graphs."""

from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.orchestration.streaming.graph.flow_model import FlowGraph


class FlowValidator:
    """Validate graph structure."""

    @staticmethod
    def validate(*, flow_graph: FlowGraph) -> None:
        """Validate the completed graph's nodes and edge endpoints."""
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
            input_count = len(flow_graph.get_input_edges(node.id))
            if node.operator_name == OperatorConstants.Operators.MERGE:
                if input_count < 2:
                    raise ValueError(f"Merge node '{node.name}' requires at least two incoming edges.")
            elif input_count > 1:
                raise ValueError(f"Non-merge node '{node.name}' cannot have multiple incoming edges.")
