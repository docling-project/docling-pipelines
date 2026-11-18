"""OpenLineageExecutionObserver — concrete ExecutionLifecycleObserverPort."""

from __future__ import annotations

from docpipe.core.constants.constants import LineageConstants
from docpipe.core.lineage.application.lineage_service import LineageService
from docpipe.core.lineage.domain.ports.execution_lifecycle_observer import ExecutionLifecycleObserverPort
from docpipe.core.orchestration.models.execution_event_context import (
    FlowAbortContext,
    FlowCompleteContext,
    FlowFailContext,
    FlowRunningContext,
    FlowStartContext,
    NodeCompleteContext,
    NodeFailContext,
    NodeSkipContext,
    NodeStartContext,
)
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class OpenLineageExecutionObserver(ExecutionLifecycleObserverPort):
    """Concrete lifecycle observer that emits OpenLineage events via LineageService.

    Mode behaviour:
    - ``flow`` mode  — emits only flow-level events (on_flow_*); node events are no-ops.
    - ``operator`` mode — emits flow-level events AND a child Run per DAG node.
      In operator mode the flow-level RUNNING and COMPLETE events are emitted without
      input/output dataset edges — those are already captured by the individual node
      events and attaching them again to the flow job would create phantom extra JOB
      nodes in the Marquez lineage graph.
    """

    def __init__(self, *, lineage_service: LineageService, mode: str = LineageConstants.MODE_FLOW) -> None:
        self._service = lineage_service
        self._mode = mode

    @property
    def _is_operator_mode(self) -> bool:
        return self._mode == LineageConstants.MODE_OPERATOR

    # ------------------------------------------------------------------
    # Flow-level events
    # ------------------------------------------------------------------

    def on_flow_start(self, *, context: FlowStartContext) -> None:
        """Emit START event when flow execution begins."""
        self._service.emit_flow_start(context=context)

    def on_flow_running(self, *, context: FlowRunningContext) -> None:
        """Emit RUNNING event after ingest completes.

        Both modes pass the full context — the flow job always carries the ingest
        source as its input dataset so Marquez can display it in the lineage graph.
        In operator mode this means the flow job and the ingest node job both reference
        the same source dataset, which is correct: the flow is a summary edge.
        """
        self._service.emit_flow_running(context=context)

    def on_flow_complete(self, *, context: FlowCompleteContext) -> None:
        """Emit COMPLETE event when flow execution finishes successfully.

        Both modes pass the full context — the flow job always carries the terminal
        output dataset so Marquez shows the full input→flow→output summary edge.
        In operator mode this coexists with the operator-level chain: the flow job
        is the high-level summary while operator jobs show per-node detail.
        """
        self._service.emit_flow_complete(context=context)

    def on_flow_fail(self, *, context: FlowFailContext) -> None:
        """Emit FAIL event when flow execution fails."""
        self._service.emit_flow_fail(context=context)

    def on_flow_abort(self, *, context: FlowAbortContext) -> None:
        """Emit ABORT event when flow execution is cancelled."""
        self._service.emit_flow_abort(context=context)

    # ------------------------------------------------------------------
    # Node-level events (no-ops in flow mode)
    # ------------------------------------------------------------------

    def on_node_start(self, *, context: NodeStartContext) -> None:
        """Emit START event for a DAG node."""
        if self._mode != LineageConstants.MODE_OPERATOR:
            return
        self._service.emit_node_start(context=context)

    def on_node_complete(self, *, context: NodeCompleteContext) -> None:
        """Emit COMPLETE event for a DAG node."""
        if self._mode != LineageConstants.MODE_OPERATOR:
            return
        self._service.emit_node_complete(context=context)

    def on_node_fail(self, *, context: NodeFailContext) -> None:
        """Emit FAIL event for a DAG node."""
        if self._mode != LineageConstants.MODE_OPERATOR:
            return
        self._service.emit_node_fail(context=context)

    def on_node_skip(self, *, context: NodeSkipContext) -> None:
        """Emit OTHER event for a skipped DAG node."""
        if self._mode != LineageConstants.MODE_OPERATOR:
            return
        self._service.emit_node_skip(context=context)
