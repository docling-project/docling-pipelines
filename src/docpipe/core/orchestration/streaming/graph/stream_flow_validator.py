# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Validation of compiled streaming flow definitions and executable graphs."""

from typing import Any
from uuid import UUID

from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.orchestration.streaming.graph.flow_model import FlowGraph


class StreamFlowValidator:
    """Validate input definitions before construction and graph relationships afterward."""

    @staticmethod
    def validate_json(*, flow: dict[str, Any]) -> None:
        """Validate a compiled runtime flow before graph construction can discard or parse its data."""
        StreamFlowValidator._validate_nonempty_dag(flow=flow)
        flow_dag = flow[DocpipeConstants.DAG]
        StreamFlowValidator._validate_node_fields(flow_dag=flow_dag)
        StreamFlowValidator._validate_unique_node_ids(flow_dag=flow_dag)
        StreamFlowValidator._validate_edge_fields(flow_dag=flow_dag)
        StreamFlowValidator._validate_config_shapes(flow=flow, flow_dag=flow_dag)

    @staticmethod
    def _validate_nonempty_dag(*, flow: dict[str, Any]) -> None:
        """Require a flow object with a nonempty list of node objects."""
        if not isinstance(flow, dict):
            raise ValueError("A flow must be a JSON object.")
        flow_dag = flow.get(DocpipeConstants.DAG)
        if not isinstance(flow_dag, list) or not flow_dag:
            raise ValueError("A flow must contain at least one node in a DAG list.")
        if any(not isinstance(node, dict) for node in flow_dag):
            raise ValueError("Each flow DAG entry must be a node object.")

    @staticmethod
    def _validate_node_fields(*, flow_dag: list[dict[str, Any]]) -> None:
        """Require node identity, display name, and operator name with a valid UUID identity."""
        for index, node in enumerate(flow_dag):
            for key in (OperatorConstants.Misc.ID, OperatorConstants.Misc.NAME, OperatorConstants.Misc.OPERATOR):
                value = node.get(key)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"Node at index {index} requires a nonempty string '{key}'.")
            try:
                UUID(node[OperatorConstants.Misc.ID])
            except ValueError as exc:
                raise ValueError(
                    f"Node at index {index} has an invalid UUID: '{node[OperatorConstants.Misc.ID]}'."
                ) from exc

    @staticmethod
    def _validate_unique_node_ids(*, flow_dag: list[dict[str, Any]]) -> None:
        """Reject duplicate node identities before graph construction can overwrite them."""
        seen_ids: set[UUID] = set()
        for node in flow_dag:
            node_id = UUID(node[OperatorConstants.Misc.ID])
            if node_id in seen_ids:
                raise ValueError(f"Duplicate node id: '{node_id}'.")
            seen_ids.add(node_id)

    @staticmethod
    def _validate_edge_fields(*, flow_dag: list[dict[str, Any]]) -> None:
        """Require output edge lists containing syntactically valid target references."""
        for node in flow_dag:
            node_name = node[OperatorConstants.Misc.NAME]
            edges = node.get(DocpipeConstants.OUTPUT_EDGES)
            if not isinstance(edges, list):
                raise ValueError(f"Node '{node_name}' requires an output_edges list.")
            for edge in edges:
                reference = edge.get(DocpipeConstants.NODE_ID_REF) if isinstance(edge, dict) else None
                if not isinstance(reference, str):
                    raise ValueError(f"Output edge from node '{node_name}' requires a string node_id_ref.")
                link_name = edge.get(DocpipeConstants.LINK_NAME)
                if link_name is not None and not isinstance(link_name, str):
                    raise ValueError(f"Output edge from node '{node_name}' requires a string link_name when provided.")
                try:
                    UUID(reference)
                except ValueError as exc:
                    raise ValueError(
                        f"Output edge from node '{node_name}' has an invalid node_id_ref: '{reference}'."
                    ) from exc

    @staticmethod
    def _validate_config_shapes(*, flow: dict[str, Any], flow_dag: list[dict[str, Any]]) -> None:
        """Accept absent configuration and require supplied configuration to be an object."""
        global_config = flow.get(OperatorConstants.Config.GLOBAL_CONFIG)
        if global_config is not None and not isinstance(global_config, dict):
            raise ValueError("Flow global_config must be an object when provided.")
        for node in flow_dag:
            config = node.get(OperatorConstants.Config.CONFIG)
            if config is not None and not isinstance(config, dict):
                raise ValueError(f"Configuration for node '{node[OperatorConstants.Misc.NAME]}' must be an object.")

    @staticmethod
    def validate_graph(*, flow_graph: FlowGraph) -> None:
        """Validate graph relationships using each node's effective configuration."""
        StreamFlowValidator._validate_edge_endpoints(flow_graph=flow_graph)
        StreamFlowValidator._validate_root(flow_graph=flow_graph)
        StreamFlowValidator._validate_connection_counts(flow_graph=flow_graph)
        StreamFlowValidator._validate_branch_definitions(flow_graph=flow_graph)
        StreamFlowValidator._validate_branch_mappings(flow_graph=flow_graph)
        StreamFlowValidator._validate_merge_input_counts(flow_graph=flow_graph)
        StreamFlowValidator._validate_merge_input_names(flow_graph=flow_graph)
        StreamFlowValidator._validate_merge_mappings(flow_graph=flow_graph)

    @staticmethod
    def _validate_edge_endpoints(*, flow_graph: FlowGraph) -> None:
        """Reject connections to nodes absent from the graph."""
        for edge in flow_graph.edges:
            if edge.source_id not in flow_graph.nodes or edge.target_id not in flow_graph.nodes:
                raise ValueError(f"Connection references an unknown node: '{edge.source_id}' -> '{edge.target_id}'.")

    @staticmethod
    def _validate_root(*, flow_graph: FlowGraph) -> None:
        """Require exactly one root and require that root to ingest documents."""
        root_nodes = [node for node in flow_graph.nodes.values() if not flow_graph.get_input_edges(node.id)]
        if len(root_nodes) != 1:
            raise ValueError(f"A flow must have exactly one root node, found {len(root_nodes)}.")
        root = root_nodes[0]
        if root.operator_name != OperatorConstants.Operators.INGEST_SOURCE:
            raise ValueError(f"Root node '{root.name}' must be an ingest operator, found '{root.operator_name}'.")

    @staticmethod
    def _validate_connection_counts(*, flow_graph: FlowGraph) -> None:
        """Limit non-merge inputs and non-branching outputs to one, allowing terminal nodes no outputs."""
        for node in flow_graph.nodes.values():
            if node.operator_name != OperatorConstants.Operators.MERGE and len(flow_graph.get_input_edges(node.id)) > 1:
                raise ValueError(f"Non-merge node '{node.name}' cannot have multiple incoming edges.")
            if (
                node.operator_name != OperatorConstants.Operators.BRANCHING
                and len(flow_graph.get_output_edges(node.id)) > 1
            ):
                raise ValueError(f"Non-branching node '{node.name}' cannot have multiple outgoing edges.")

    @staticmethod
    def _validate_branch_definitions(*, flow_graph: FlowGraph) -> None:
        """Require at least two branch objects with unique string link IDs."""
        for node in flow_graph.nodes.values():
            if node.operator_name != OperatorConstants.Operators.BRANCHING:
                continue
            branches = node.operator_config.get(OperatorConstants.Misc.BRANCHES)
            if not isinstance(branches, list) or len(branches) < 2:
                raise ValueError(f"Branching node '{node.name}' requires at least two configured branches.")

            configured_ids: set[str] = set()
            for index, branch in enumerate(branches):
                branch_id = branch.get(OperatorConstants.Misc.LINK_ID) if isinstance(branch, dict) else None
                if not isinstance(branch_id, str) or not branch_id:
                    raise ValueError(
                        f"Configured branch at index {index} in branching node '{node.name}' requires a link_id."
                    )
                if branch_id in configured_ids:
                    raise ValueError(f"Branching node '{node.name}' has duplicate configured branch ID '{branch_id}'.")
                configured_ids.add(branch_id)

    @staticmethod
    def _validate_branch_mappings(*, flow_graph: FlowGraph) -> None:
        """Require one outgoing edge and distinct target for every configured branch."""
        for node in flow_graph.nodes.values():
            if node.operator_name != OperatorConstants.Operators.BRANCHING:
                continue
            output_edges = flow_graph.get_output_edges(node.id)
            configured_ids = {
                branch[OperatorConstants.Misc.LINK_ID]
                for branch in node.operator_config[OperatorConstants.Misc.BRANCHES]
            }
            outgoing_ids = [edge.branch_id for edge in output_edges]
            if len(outgoing_ids) != len(set(outgoing_ids)):
                raise ValueError(
                    f"Branching node '{node.name}' must connect each branch ID to exactly one output edge."
                )
            outgoing_id_set = set(outgoing_ids)
            if configured_ids != outgoing_id_set:
                missing = sorted(configured_ids - outgoing_id_set)
                unexpected = sorted(outgoing_id_set - configured_ids, key=str)
                raise ValueError(
                    f"Branching node '{node.name}' configured branch IDs do not match outgoing edges. "
                    f"Missing branch IDs: {missing}; unexpected branch IDs: {unexpected}."
                )
            if len({edge.target_id for edge in output_edges}) != len(output_edges):
                raise ValueError(
                    f"Branching node '{node.name}' must connect each branch to a distinct downstream node."
                )

    @staticmethod
    def _validate_merge_input_counts(*, flow_graph: FlowGraph) -> None:
        """Require at least two incoming edges for each merge node."""
        for node in flow_graph.nodes.values():
            if node.operator_name == OperatorConstants.Operators.MERGE and len(flow_graph.get_input_edges(node.id)) < 2:
                raise ValueError(f"Merge node '{node.name}' requires at least two incoming edges.")

    @staticmethod
    def _validate_merge_input_names(*, flow_graph: FlowGraph) -> None:
        """Require nonempty, unique merge input names so named table inputs cannot overwrite each other."""
        for node in flow_graph.nodes.values():
            if node.operator_name != OperatorConstants.Operators.MERGE:
                continue
            input_links = node.operator_config.get(OperatorConstants.Merge.INPUT_LINKS, [])
            if not isinstance(input_links, list):
                raise ValueError(f"Merge node '{node.name}' requires an input_links list.")
            input_names: set[str] = set()
            for index, link in enumerate(input_links):
                input_name = link.get(DocpipeConstants.LINK_NAME) if isinstance(link, dict) else None
                if not isinstance(input_name, str) or not input_name.strip():
                    raise ValueError(
                        f"Merge node '{node.name}' input_links entry {index} requires a nonempty string link_name."
                    )
                if input_name in input_names:
                    raise ValueError(
                        f"Merge node '{node.name}' has duplicate input name '{input_name}' at entry {index}."
                    )
                input_names.add(input_name)

    @staticmethod
    def _validate_merge_mappings(*, flow_graph: FlowGraph) -> None:
        """Match configured merge source identities to incoming graph edges."""
        for node in flow_graph.nodes.values():
            if node.operator_name != OperatorConstants.Operators.MERGE:
                continue
            input_links = node.operator_config.get(OperatorConstants.Merge.INPUT_LINKS, [])
            configured_source_ids: set[UUID] = set()
            for index, link in enumerate(input_links):
                reference = link.get(DocpipeConstants.NODE_ID_REF)
                try:
                    if not isinstance(reference, str):
                        raise ValueError("Source reference must be a string.")
                    configured_source_ids.add(UUID(reference))
                except ValueError as exc:
                    raise ValueError(
                        f"Merge node '{node.name}' input_links entry {index} has an invalid source reference: {reference!r}."
                    ) from exc
            incoming_source_ids = {edge.source_id for edge in flow_graph.get_input_edges(node.id)}
            if incoming_source_ids != configured_source_ids:
                missing = sorted(str(source_id) for source_id in incoming_source_ids - configured_source_ids)
                unexpected = sorted(str(source_id) for source_id in configured_source_ids - incoming_source_ids)
                raise ValueError(
                    f"Merge node '{node.name}' input_links do not match incoming edges. "
                    f"Missing source IDs: {missing}; unexpected source IDs: {unexpected}."
                )
