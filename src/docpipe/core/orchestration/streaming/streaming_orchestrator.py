# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Coordinate graph construction and execution for a streaming flow."""

from uuid import UUID

from docpipe.core.orchestration.streaming.graph.execution_engine import GraphExecutionEngine
from docpipe.core.orchestration.streaming.graph.flow_builder import FlowBuilder
from docpipe.core.orchestration.streaming.graph.output_buffer import OperatorOutput


class StreamingOrchestrator:
    """Build and execute a compiled runtime flow using in-memory graph state."""

    def execute(self, *, flow: dict, params: dict) -> dict[UUID, OperatorOutput]:
        """Build the flow graph and run its operators in dependency order."""
        builder = FlowBuilder(flow=flow, params=params)
        flow_graph = builder.build_graph()
        ordered_operator_ids = FlowBuilder.sort_graph(flow_graph=flow_graph)
        engine = GraphExecutionEngine(flow_graph=flow_graph, ordered_operator_ids=ordered_operator_ids)
        return engine.execute()
