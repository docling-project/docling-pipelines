# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Coordinate graph construction and execution for a streaming flow."""

from docpipe.core.orchestration.streaming.graph.execution_engine import GraphExecutionEngine
from docpipe.core.orchestration.streaming.graph.flow_builder import FlowBuilder


class StreamingOrchestrator:
    """Build and execute a compiled runtime flow using in-memory graph state."""

    @staticmethod
    def execute(*, flow: dict, params: dict) -> None:
        """Build the graph and complete execution and cleanup, or propagate failure."""
        from docpipe.core.event_streaming.kafka_producer import KafkaProducer

        event_id = params["input_event"]["event_id"]
        KafkaProducer.notify(event_id=event_id, operation="flow", status="Started")
        builder = FlowBuilder(flow=flow, params=params)
        flow_graph = builder.build_graph()
        ordered_operator_ids = FlowBuilder.sort_graph(flow_graph=flow_graph)
        engine = GraphExecutionEngine(flow_graph=flow_graph, ordered_operator_ids=ordered_operator_ids)
        engine.execute()
        KafkaProducer.notify(event_id=event_id, operation="flow", status="Completed")
