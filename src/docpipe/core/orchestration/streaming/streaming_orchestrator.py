# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Coordinate graph construction and execution for a streaming flow."""

from docpipe.core.orchestration.streaming.graph.execution_engine import GraphExecutionEngine
from docpipe.core.orchestration.streaming.graph.flow_builder import FlowBuilder
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger(__name__)


class StreamingOrchestrator:
    """Build and execute a compiled runtime flow using in-memory graph state."""

    @staticmethod
    def execute(*, flow: dict, params: dict) -> None:
        """Build the flow graph and run its operators in dependency order.

        Args:
            flow: Flow definition dictionary containing nodes and edges.
            params: Flow parameters dictionary.

        Raises:
            ValueError: If the flow definition is invalid, contains cycles, or references unknown operators.
        """
        logger.info("Starting streaming flow execution.")
        builder = FlowBuilder(flow=flow, params=params)
        flow_graph = builder.build_graph()
        ordered_operator_ids = FlowBuilder.sort_graph(flow_graph=flow_graph)
        engine = GraphExecutionEngine(flow_graph=flow_graph, ordered_operator_ids=ordered_operator_ids)
        engine.execute()
        logger.info("Finished streaming flow execution.")
