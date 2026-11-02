# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Execution engine running streaming flow operators in dependency order."""

from uuid import UUID

import pyarrow as pa

from docpipe.core.constants.constants import DocpipeConstants, ExecutionStatus, Metrics, OrchestratorType
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.operators.abstract_operator import AbstractOperator
from docpipe.core.operators.functional.merge import MergeOperator
from docpipe.core.operators.operator_utils import OperatorUtils
from docpipe.core.orchestration.operator_factory import OperatorFactory, OperatorFactoryProvider
from docpipe.core.orchestration.streaming.graph.flow_model import FlowGraph, Node
from docpipe.core.orchestration.streaming.graph.output_buffer import OperatorOutput, OutputBuffer
from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class GraphExecutionEngine:
    """Executes a dependency-ordered operator graph and returns terminal outputs."""

    def __init__(self, *, flow_graph: FlowGraph, ordered_operator_ids: list[UUID]) -> None:
        self.flow_graph = flow_graph
        self.ordered_operator_ids = ordered_operator_ids
        self.operator_factory: OperatorFactory = OperatorFactoryProvider.get_operator_factory(
            orchestrator=OrchestratorType.PYTHON
        )
        self.output_buffer = OutputBuffer()

    def execute(self) -> dict[UUID, OperatorOutput]:
        """Run operators and return each terminal operator's output table."""
        try:
            for node_id in self.ordered_operator_ids:
                node = self.flow_graph.nodes[node_id]
                if node.operator_name == OperatorConstants.Operators.BRANCHING:
                    input_edges = self.flow_graph.get_input_edges(node.id)
                    edge = input_edges[0]
                    input_table = self._get_input_table(source_id=edge.source_id, branch_id=edge.branch_id)
                    operator_output = self._execute_branching_node(node=node, input_table=input_table)
                elif node.operator_name == OperatorConstants.Operators.MERGE:
                    input_tables = self._get_merge_tables(node=node)
                    operator_output = self._execute_merging_node(node=node, input_tables=input_tables)
                else:
                    input_edges = self.flow_graph.get_input_edges(node.id)
                    if input_edges:
                        edge = input_edges[0]
                        input_table = self._get_input_table(source_id=edge.source_id, branch_id=edge.branch_id)
                    else:
                        input_table = None
                    operator_output = self._execute_simple_node(node=node, input_table=input_table)
                self._raise_if_node_failed(node=node, metadata=operator_output.metadata)
                self.output_buffer.put_output(node_id=node_id, output=operator_output)

            terminal_ids = [
                node_id for node_id in self.ordered_operator_ids if not self.flow_graph.get_output_edges(node_id)
            ]
            return {node_id: self.output_buffer.get_output(node_id) for node_id in terminal_ids}
        finally:
            self.output_buffer.clear()

    def _get_input_table(self, *, source_id: UUID, branch_id: str | None = None) -> pa.Table:
        """Read a source output, selecting the connected branch when applicable."""
        source_node = self.flow_graph.nodes[source_id]
        output = self.output_buffer.get_output(source_id)
        result_index = 0
        if source_node.operator_name == OperatorConstants.Operators.BRANCHING:
            branches = output.metadata.get(OperatorConstants.Misc.BRANCHES, {})
            if branch_id not in branches:
                raise ValueError(f"Branch '{branch_id}' not found in branching node '{source_node.name}'.")
            branch_info = branches[branch_id]
            if not isinstance(branch_info, dict) or OperatorConstants.Misc.RESULT_INDEX not in branch_info:
                raise ValueError(
                    f"Result index missing for branch '{branch_id}' in branching node '{source_node.name}'."
                )
            result_index = branch_info[OperatorConstants.Misc.RESULT_INDEX]
            if type(result_index) is not int or not 0 <= result_index < len(output.tables):
                raise ValueError(
                    f"Invalid result index {result_index!r} for branch '{branch_id}' in branching node "
                    f"'{source_node.name}': expected an integer in [0, {len(output.tables)})."
                )
        else:
            assert len(output.tables) == 1, (
                f"Expected single table from non-branching node '{source_node.name}', got {len(output.tables)}"
            )
        return output.tables[result_index]

    def _get_merge_tables(self, *, node: Node) -> dict[str, pa.Table]:
        """Resolve merge input tables under their configured input names."""
        input_tables: dict[str, pa.Table] = {}
        for input_link in node.operator_config[OperatorConstants.Merge.INPUT_LINKS]:
            source_id = UUID(input_link[DocpipeConstants.NODE_ID_REF])
            input_name = input_link[DocpipeConstants.LINK_NAME]
            input_tables[input_name] = self._get_input_table(source_id=source_id, branch_id=input_name)
        return input_tables

    def _execute_branching_node(self, *, node: Node, input_table: pa.Table | None) -> OperatorOutput:
        """Run a branching node or resolve its empty input into empty branch outputs."""
        if input_table is not None and input_table.num_rows == 0:
            logger.info("Skipping operator '%s' (%s) because its input is empty", node.name, node.operator_name)
            metadata = AbstractOperator.create_base_metadata(
                total_docs_count=0, node_status=ExecutionStatus.COMPLETED.value
            )
            branches = {
                edge.branch_id: {OperatorConstants.Misc.RESULT_INDEX: 0}
                for edge in self.flow_graph.get_output_edges(node.id)
            }
            metadata[OperatorConstants.Misc.BRANCHES] = branches
            return OperatorOutput(tables=[input_table], metadata=metadata)
        return self._execute_node(node=node, input_table=input_table)

    @staticmethod
    def _execute_merging_node(*, node: Node, input_tables: dict[str, pa.Table]) -> OperatorOutput:
        """Run the merge operator with its resolved input tables."""
        operator = MergeOperator(config=node.operator_config)
        output_tables, metadata = operator.transform(table=pa.table({}), tables=input_tables)
        return GraphExecutionEngine._prepare_output(operator=operator, tables=output_tables, metadata=metadata)

    def _execute_simple_node(self, *, node: Node, input_table: pa.Table | None) -> OperatorOutput:
        """Run a linear node or pass its empty input through."""
        if input_table is not None and input_table.num_rows == 0:
            logger.info("Skipping operator '%s' (%s) because its input is empty", node.name, node.operator_name)
            metadata = AbstractOperator.create_base_metadata(
                total_docs_count=0, node_status=ExecutionStatus.COMPLETED.value
            )
            return OperatorOutput(tables=[input_table], metadata=metadata)
        return self._execute_node(node=node, input_table=input_table)

    def _execute_node(self, *, node: Node, input_table: pa.Table | None) -> OperatorOutput:
        """Run one operator and prepare its output tables and execution metadata."""
        operator_class: type[AbstractOperator] | None = self.operator_factory.get_operator(
            operator_name=node.operator_name
        )
        if not operator_class:
            raise ValueError(f"Operator:{node.operator_name} not found.")
        operator: AbstractOperator = operator_class(config=node.operator_config)
        output_tables, metadata = operator.transform(table=input_table)
        return self._prepare_output(operator=operator, tables=output_tables, metadata=metadata)

    @staticmethod
    def _prepare_output(*, operator: AbstractOperator, tables: list[pa.Table], metadata: dict) -> OperatorOutput:
        """Apply configured column drops and then renames to every output table."""
        for index, table in enumerate(tables):
            if operator.output_features_to_drop:
                table = OperatorUtils.drop_features_from_table(operator.output_features_to_drop, table)
            if operator.updated_features and table.num_columns:
                if table.num_rows:
                    table = OperatorUtils.rename_features_and_save_original(
                        updated_features=operator.updated_features, input_features=table
                    )
                else:
                    # Preserve empty branch tables while renaming their column schemas.
                    renames = {
                        feature[OperatorConstants.Misc.OLD_FEATURE]: feature[OperatorConstants.Misc.NEW_FEATURE]
                        for feature in operator.updated_features
                    }
                    table = table.rename_columns([renames.get(name, name) for name in table.column_names])
            tables[index] = table
        return OperatorOutput(tables=tables, metadata=metadata)

    @staticmethod
    def _raise_if_node_failed(*, node: Node, metadata: dict) -> None:
        """Raise when an operator reports failure so event dispatch cannot report success."""
        if metadata.get(Metrics.External.NODE_STATUS) == ExecutionStatus.FAILED.value:
            raise FlowExecutionFailedException(
                f"Operator '{node.name}' ({node.operator_name}) reported a failed execution."
            )
