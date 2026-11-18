"""Compiler service for converting authoring model to runtime DAG format.

This application service transforms the user-friendly authoring format into
the runtime DAG format expected by the orchestrator. It handles:
- UUID generation for nodes
- Edge construction from dependencies
- Branch output handling
- Merge operator input aggregation
- Global configuration propagation

Architecture:
This is an application service that coordinates domain models and provides
transformation logic. It sits in the application layer of hexagonal architecture.
"""

from typing import Any
from uuid import uuid4

from docpipe.core.assets.flows.domain.models.authoring_flow import AuthoringFlow, AuthoringOperator
from docpipe.core.constants.constants import DocpipeConstants
from docpipe.core.constants.operator_constants import OperatorConstants


class AuthoringCompiler:
    """Compiles authoring model to runtime DAG format.

    Transforms the simplified authoring format into the runtime DAG format
    expected by the orchestrator. Handles dependency resolution, edge creation,
    and branch output management.

    The output format matches sample_flows/*.json structure and is directly
    accepted by AbstractOrchestrator.execute().

    Example:
        compiler = AuthoringCompiler()
        runtime_flow = compiler.compile(authoring_flow=authoring_flow)
        # runtime_flow is ready for execution
    """

    def compile(self, *, authoring_flow: AuthoringFlow) -> dict[str, Any]:
        """Compile authoring flow to runtime DAG format.

        Args:
            authoring_flow: Validated authoring flow model

        Returns:
            Runtime DAG format dict with structure:

        Raises:
            FlowInvalidDataException: If compilation fails due to invalid structure
        """
        # Validate before compilation
        authoring_flow.validate()

        # Generate UUIDs for all operators
        operator_ids = self._generate_operator_ids(operators=authoring_flow.flow)

        # Build dependency graph for edge construction
        dependency_graph = self._build_dependency_graph(operators=authoring_flow.flow)

        # Compile each operator to runtime node format
        dag_nodes: list[dict[str, Any]] = []
        for operator in authoring_flow.flow:
            node = self._compile_operator(
                operator=operator, operator_ids=operator_ids, dependency_graph=dependency_graph
            )
            dag_nodes.append(node)

        # Construct runtime flow
        runtime_flow: dict[str, Any] = {
            DocpipeConstants.NAME: authoring_flow.flow_name,
            DocpipeConstants.FLOW_ID: authoring_flow.flow_id or str(uuid4()),
            DocpipeConstants.DESCRIPTION: authoring_flow.description or "",
            DocpipeConstants.STORAGE: DocpipeConstants.STORAGE_IN_MEMORY,
            DocpipeConstants.EXECUTE_TYPE: DocpipeConstants.LOCAL,
            DocpipeConstants.FLOW_SOURCE: authoring_flow.flow_source,
            OperatorConstants.Config.GLOBAL_CONFIG: authoring_flow.global_config or {},
            DocpipeConstants.DAG: dag_nodes,
        }

        return runtime_flow

    @staticmethod
    def _generate_operator_ids(*, operators: list[AuthoringOperator]) -> dict[str, str]:
        """Generate UUID for each operator.

        Args:
            operators: List of authoring operators

        Returns:
            Dict mapping operator name to UUID
        """
        return {op.name: str(uuid4()) for op in operators if op.name is not None}

    @staticmethod
    def _build_dependency_graph(*, operators: list[AuthoringOperator]) -> dict[str, list[tuple[str, str | None]]]:
        """Build reverse dependency graph (who depends on whom).

        Creates a mapping from operator name to list of (dependent_name, link_name) tuples.
        This is used to construct output_edges for each node.

        Args:
            operators: List of authoring operators

        Returns:
            Dict mapping operator name to list of (dependent_name, link_name) tuples
            where link_name is the branch name if dependency is a branch reference
        """
        graph: dict[str, list[tuple[str, str | None]]] = {op.name: [] for op in operators if op.name is not None}

        for operator in operators:
            if not operator.depends_on or operator.name is None:
                continue

            for dependency in operator.depends_on:
                # Parse dependency: could be "operator_name" or "operator_name.branch"
                if OperatorConstants.Misc.BRANCH_SEPARATOR in dependency:
                    source_name, branch_name = dependency.split(OperatorConstants.Misc.BRANCH_SEPARATOR, 1)
                    graph[source_name].append((operator.name, branch_name))
                else:
                    graph[dependency].append((operator.name, None))

        return graph

    def _compile_operator(
        self,
        *,
        operator: AuthoringOperator,
        operator_ids: dict[str, str],
        dependency_graph: dict[str, list[tuple[str, str | None]]],
    ) -> dict[str, Any]:
        """Compile single operator to runtime node format.

        Args:
            operator: Authoring operator to compile
            operator_ids: Mapping of operator names to UUIDs
            dependency_graph: Reverse dependency graph for output edge construction

        Returns:
            Runtime node dict with id, name, operator, config, input_edges, output_edges
        """
        # All operators must have names (enforced by validation)
        if operator.name is None:
            msg = "Operator name cannot be None"
            raise ValueError(msg)

        node_id = operator_ids[operator.name]

        # Build input edges from dependencies and extract link_id if present
        input_edges, link_id = self._build_input_edges(operator=operator, operator_ids=operator_ids)

        # Build output edges from dependency graph
        output_edges = self._build_output_edges(
            operator_name=operator.name, dependency_graph=dependency_graph, operator_ids=operator_ids
        )

        config = dict(operator.config or {})

        # Transform config for specific operators
        config = self._transform_operator_config(operator=operator)

        # Always rebuild input_links for merge operators to ensure proper link_names
        if operator.type == OperatorConstants.Operators.MERGE:
            config[OperatorConstants.Merge.INPUT_LINKS] = self._build_merge_input_links(input_edges=input_edges)

        node_dict = {
            OperatorConstants.Columns.ID: node_id,
            OperatorConstants.Columns.NAME: operator.name,
            OperatorConstants.Misc.OPERATOR: operator.type,
            OperatorConstants.Config.CONFIG: config,
            DocpipeConstants.INPUT_EDGES: input_edges,
            DocpipeConstants.OUTPUT_EDGES: output_edges,
        }

        # Add link_id to operator definition if it depends on a specific branch
        if link_id:
            node_dict[OperatorConstants.Misc.LINK_ID] = link_id

        return node_dict

    @staticmethod
    def _build_input_edges(
        *, operator: AuthoringOperator, operator_ids: dict[str, str]
    ) -> tuple[list[dict[str, str]], str | None]:
        """Build input edges for an operator.

        Args:
            operator: Authoring operator
            operator_ids: Mapping of operator names to UUIDs

        Returns:
            Tuple of (input edges list, link_id if operator depends on a single branch)
        """
        if not operator.depends_on:
            return [], None

        input_edges: list[dict[str, str]] = []
        link_id: str | None = None

        for dependency in operator.depends_on:
            # Parse dependency: could be "operator_name" or "operator_name.branch"
            if OperatorConstants.Misc.BRANCH_SEPARATOR in dependency:
                source_name, branch_name = dependency.split(OperatorConstants.Misc.BRANCH_SEPARATOR, 1)
                input_edges.append({"node_id_ref": operator_ids[source_name], DocpipeConstants.LINK_NAME: branch_name})
                # If operator has single branch dependency, store link_id for runtime
                if len(operator.depends_on) == 1:
                    link_id = branch_name
            else:
                # Use operator name as link_name for non-branch dependencies
                # This ensures merge operators can distinguish between multiple inputs
                input_edges.append({"node_id_ref": operator_ids[dependency], DocpipeConstants.LINK_NAME: dependency})

        return input_edges, link_id

    @staticmethod
    def _build_output_edges(
        *,
        operator_name: str,
        dependency_graph: dict[str, list[tuple[str, str | None]]],
        operator_ids: dict[str, str],
    ) -> list[dict[str, str]]:
        """Build output edges for an operator.

        Args:
            operator_name: Name of the operator
            dependency_graph: Reverse dependency graph
            operator_ids: Mapping of operator names to UUIDs

        Returns:
            List of output edge dicts with node_id_ref and optional link_name
        """
        dependents = dependency_graph.get(operator_name, [])

        output_edges: list[dict[str, str]] = []
        for dependent_name, link_name in dependents:
            edge: dict[str, str] = {"node_id_ref": operator_ids[dependent_name]}
            if link_name:
                edge[DocpipeConstants.LINK_NAME] = link_name
            output_edges.append(edge)

        return output_edges

    @staticmethod
    def _transform_operator_config(*, operator: AuthoringOperator) -> dict[str, Any]:
        """Transform operator config from authoring format to runtime format.

        Handles format conversions between the user-friendly authoring format
        and the runtime format expected by operators.

        Args:
            operator: Authoring operator

        Returns:
            Transformed config dict ready for runtime execution
        """
        config = operator.config.copy() if operator.config else {}

        # Transform branching operator: dict of branches -> list of branches
        # Authoring format uses dict for better readability and validation
        # Runtime operator expects list format
        if operator.type == OperatorConstants.Operators.BRANCHING:
            branches = config.get(OperatorConstants.Misc.BRANCHES)
            if isinstance(branches, dict):
                # Convert dict format to list format expected by runtime operator
                branch_list = []
                for branch_name, branch_config in branches.items():
                    branch_item = {
                        OperatorConstants.Misc.LINK_ID: branch_name,
                        OperatorConstants.Misc.LINK_NAME: branch_name,  # Add link_name for validation
                        **branch_config,
                    }
                    branch_list.append(branch_item)
                config[OperatorConstants.Misc.BRANCHES] = branch_list

        return config

    @staticmethod
    def _build_merge_input_links(*, input_edges: list[dict[str, str]]) -> list[dict[str, str]]:
        """Build merge input_links config from compiled input edges."""
        return [
            {
                OperatorConstants.Misc.LINK_NAME: input_edge.get(
                    DocpipeConstants.LINK_NAME,
                    f"input_{index + 1}",
                ),
                "node_id_ref": input_edge["node_id_ref"],
            }
            for index, input_edge in enumerate(input_edges)
        ]
