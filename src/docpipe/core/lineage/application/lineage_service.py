"""Application service that bridges execution context to OpenLineage events."""

import traceback
from datetime import datetime
from typing import Any

from docpipe.core.constants.constants import ExecutionStatus, LineageConstants
from docpipe.core.lineage.domain.models.dataset import LineageDataset
from docpipe.core.lineage.domain.models.event_type import LineageEventType
from docpipe.core.lineage.domain.models.job import LineageJob
from docpipe.core.lineage.domain.models.run import LineageRun
from docpipe.core.lineage.domain.ports.lineage_publisher import LineagePublisherPort
from docpipe.core.lineage.utils import _CREDENTIALS_KEYS, LineageUtils
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
    NodeTableSummary,
)
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()

# Internal keys produced by the orchestrator — never surface in lineage events.
_INTERNAL_LINEAGE_KEYS = frozenset(
    {
        "deleted_from_last_run",
        "all_doc_ids",
        "branches",
        "non_recoverable_docs_table",
    }
)

_STATUS_MAP: dict[str, LineageEventType] = {
    ExecutionStatus.RUNNING.value: LineageEventType.RUNNING,
    ExecutionStatus.COMPLETED.value: LineageEventType.COMPLETE,
    ExecutionStatus.COMPLETED_WITH_ERRORS.value: LineageEventType.COMPLETE,
    ExecutionStatus.COMPLETED_WITH_WARNINGS.value: LineageEventType.COMPLETE,
    ExecutionStatus.FAILED.value: LineageEventType.FAIL,
    ExecutionStatus.FAILING.value: LineageEventType.FAIL,
    ExecutionStatus.CANCELED.value: LineageEventType.ABORT,
    ExecutionStatus.CANCELING.value: LineageEventType.ABORT,
    ExecutionStatus.ABORTED.value: LineageEventType.ABORT,
}


class LineageService:
    """Application service that translates execution context objects into lineage events.

    Receives a pre-injected publisher and is responsible for building the
    neutral domain models (LineageRun, LineageJob, LineageDataset) from each
    context object before delegating to the publisher.
    """

    def __init__(self, *, publisher: LineagePublisherPort, namespace: str, producer: str) -> None:
        self._publisher = publisher
        self._namespace = namespace
        self._producer = producer

    # ------------------------------------------------------------------
    # Flow-level events
    # ------------------------------------------------------------------

    def emit_flow_start(self, *, context: FlowStartContext) -> None:
        """Emit a START event for flow execution beginning."""
        job = self._build_flow_job(flow_id=context.flow_id, flow_name=context.flow_name, flow_def=context.flow_def)
        if context.operator_names:
            job.facets["docpipeOperators"] = {
                "_producer": self._producer,
                "operators": context.operator_names,
                "count": len(context.operator_names),
            }
        run = LineageRun(
            run_id=context.job_run_id,
            start_time=context.start_time or LineageUtils.now(),
            facets=self._build_nominal_time_facet(start_time=context.start_time),
        )
        self._publish(event_type=LineageEventType.START, run=run, job=job)

    def emit_flow_running(self, *, context: FlowRunningContext) -> None:
        """Emit a RUNNING event after ingest completes."""
        job = self._build_flow_job(flow_id=context.flow_id, flow_name=context.flow_name)
        run = LineageRun(run_id=context.job_run_id)
        inputs = []
        if context.ingested_table is not None:
            dataset_name = context.ingest_source_name or context.ingest_node_id or "ingest"
            namespace = context.ingest_source_namespace or self._namespace
            inputs = [
                self._build_dataset_from_summary(
                    summary=NodeTableSummary.from_table(context.ingested_table),
                    name=dataset_name,
                    namespace=namespace,
                )
            ]
        self._publish(event_type=LineageEventType.RUNNING, run=run, job=job, inputs=inputs)

    def emit_flow_complete(self, *, context: FlowCompleteContext) -> None:
        """Emit a COMPLETE event for successful flow execution."""
        job = self._build_flow_job(flow_id=context.flow_id, flow_name=context.flow_name, flow_def=context.flow_def)
        run_facets: dict[str, Any] = {}
        if context.total_docs > 0 or context.completed_docs > 0:
            run_facets["docpipeStats"] = {
                "_producer": self._producer,
                "_schemaURL": LineageConstants.DOCPIPE_NODE_STATS_FACET_URL,
                "completedDocs": context.completed_docs,
                "failedDocs": context.failed_docs,
                "skippedDocs": context.skipped_docs,
                "totalDocs": context.total_docs,
            }
        run = LineageRun(
            run_id=context.job_run_id,
            start_time=context.start_time,
            end_time=context.end_time or LineageUtils.now(),
            status=context.status,
            facets=run_facets,
        )
        outputs = []
        if context.sink_datasets:
            # Each sink carries the summary of its own output, so branching flows with
            # different sink schemas report the right facets for every sink.
            outputs = [
                self._build_dataset_from_summary(summary=sink.summary, name=sink.name, namespace=sink.namespace)
                for sink in context.sink_datasets
            ]
        else:
            base_name = context.flow_name or "output"
            outputs = [
                self._build_dataset_from_summary(
                    summary=NodeTableSummary.from_table(t),
                    name=f"{base_name}/output_{i}" if len(context.output_tables) > 1 else f"{base_name}/output",
                    namespace=LineageConstants.NAMESPACE_INMEMORY,
                )
                for i, t in enumerate(context.output_tables)
                if t is not None
            ]
        self._publish(event_type=LineageEventType.COMPLETE, run=run, job=job, outputs=outputs)

    def emit_flow_fail(self, *, context: FlowFailContext) -> None:
        """Emit a FAIL event for failed flow execution."""
        job = self._build_flow_job(flow_id=context.flow_id, flow_name=context.flow_name, flow_def=context.flow_def)
        run = LineageRun(
            run_id=context.job_run_id,
            start_time=context.start_time,
            end_time=context.end_time or LineageUtils.now(),
            status=context.status,
            facets=self._build_error_facet(message=context.error_message, exception=context.exception),
        )
        self._publish(event_type=LineageEventType.FAIL, run=run, job=job)

    def emit_flow_abort(self, *, context: FlowAbortContext) -> None:
        """Emit an ABORT event for cancelled flow execution."""
        job = self._build_flow_job(flow_id=context.flow_id, flow_name=context.flow_name, flow_def=context.flow_def)
        run = LineageRun(
            run_id=context.job_run_id,
            start_time=context.start_time,
            end_time=context.end_time or LineageUtils.now(),
            status=context.status,
        )
        self._publish(event_type=LineageEventType.ABORT, run=run, job=job)

    # ------------------------------------------------------------------
    # Node-level events
    # ------------------------------------------------------------------

    def emit_node_start(self, *, context: NodeStartContext) -> None:
        """Emit a START event for a DAG node beginning execution."""
        job = self._build_node_job(context=context)
        run = LineageRun(
            run_id=self._node_run_id(job_run_id=context.job_run_id, node_id=context.node_id),
            start_time=context.start_time or LineageUtils.now(),
            facets=self._build_parent_run_facet(
                flow_name=context.flow_name,
                job_run_id=context.job_run_id,
            ),
        )
        inputs = []
        if context.input_summary is not None:
            if context.ingest_source_dataset_name:
                input_name = context.ingest_source_dataset_name
                namespace = context.ingest_source_dataset_namespace or self._namespace
            else:
                input_name = self._build_node_input_dataset_name(
                    flow_name=context.flow_name,
                    predecessor_node_ids=context.predecessor_node_ids,
                    node_name=context.node_name,
                )
                namespace = LineageConstants.NAMESPACE_INMEMORY
            inputs = [
                self._build_dataset_from_summary(
                    summary=context.input_summary,
                    name=input_name,
                    namespace=namespace,
                )
            ]
        self._publish(event_type=LineageEventType.START, run=run, job=job, inputs=inputs)

    def emit_node_complete(self, *, context: NodeCompleteContext) -> None:
        """Emit a COMPLETE event for a DAG node finishing execution."""
        job = self._build_node_job(context=context)
        run = LineageRun(
            run_id=self._node_run_id(job_run_id=context.job_run_id, node_id=context.node_id),
            start_time=context.start_time,
            end_time=context.end_time or LineageUtils.now(),
            facets={
                **self._build_parent_run_facet(
                    flow_name=context.flow_name,
                    job_run_id=context.job_run_id,
                ),
                **self._build_node_stats_facet(metadata=context.metadata),
            },
        )
        outputs = []
        if context.sink_dataset_name:
            sink_ns = context.sink_dataset_namespace or self._namespace
            for i, s in enumerate(context.output_summaries):
                name = context.sink_dataset_name if i == 0 else f"{context.sink_dataset_name}_{i}"
                outputs.append(
                    self._build_dataset_from_summary(
                        summary=s,
                        name=name,
                        namespace=sink_ns,
                    )
                )
        # A sink with downstream operators passes its table onward. The downstream node's START input is
        # the in-memory dataset named after this node, so it must also be emitted here or the edge is lost.
        if not context.sink_dataset_name or context.has_downstream:
            outputs.extend(
                self._build_dataset_from_summary(
                    summary=s,
                    name=self._build_node_output_dataset_name(
                        flow_name=context.flow_name,
                        node_name=context.node_name,
                        index=i,
                    ),
                    namespace=LineageConstants.NAMESPACE_INMEMORY,
                )
                for i, s in enumerate(context.output_summaries)
            )
        self._publish(event_type=LineageEventType.COMPLETE, run=run, job=job, outputs=outputs)

    def emit_node_fail(self, *, context: NodeFailContext) -> None:
        """Emit a FAIL event for a DAG node execution failure."""
        job = self._build_node_job(context=context)
        run = LineageRun(
            run_id=self._node_run_id(job_run_id=context.job_run_id, node_id=context.node_id),
            start_time=context.start_time,
            end_time=context.end_time or LineageUtils.now(),
            facets={
                **self._build_parent_run_facet(
                    flow_name=context.flow_name,
                    job_run_id=context.job_run_id,
                ),
                **self._build_error_facet(
                    message=context.error_message,
                    exception=context.exception,
                ),
            },
        )
        inputs = []
        if context.input_summary is not None:
            input_name = self._build_node_input_dataset_name(
                flow_name=context.flow_name,
                predecessor_node_ids=context.predecessor_node_ids,
                node_name=context.node_name,
            )
            inputs = [
                self._build_dataset_from_summary(
                    summary=context.input_summary,
                    name=input_name,
                    namespace=LineageConstants.NAMESPACE_INMEMORY,
                )
            ]
        self._publish(event_type=LineageEventType.FAIL, run=run, job=job, inputs=inputs)

    def emit_node_skip(self, *, context: NodeSkipContext) -> None:
        """Emit an OTHER event for a DAG node being skipped."""
        job = self._build_node_job(context=context)
        run = LineageRun(
            run_id=self._node_run_id(job_run_id=context.job_run_id, node_id=context.node_id),
            start_time=context.start_time,
            end_time=context.end_time or LineageUtils.now(),
            facets={
                **self._build_parent_run_facet(
                    flow_name=context.flow_name,
                    job_run_id=context.job_run_id,
                ),
                "docpipeSkip": {
                    "_producer": self._producer,
                    "reason": context.reason,
                },
            },
        )
        self._publish(event_type=LineageEventType.OTHER, run=run, job=job)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _publish(
        self,
        *,
        event_type: LineageEventType,
        run: LineageRun,
        job: LineageJob,
        inputs: list[LineageDataset] | None = None,
        outputs: list[LineageDataset] | None = None,
    ) -> None:
        self._publisher.publish(event_type=event_type, run=run, job=job, inputs=inputs, outputs=outputs)

    def _build_flow_job(
        self,
        *,
        flow_id: str,
        flow_name: str,
        flow_def: dict[str, Any] | None = None,
    ) -> LineageJob:
        facets: dict[str, Any] = {
            "jobType": {
                "_producer": self._producer,
                "_schemaURL": LineageConstants.JOB_TYPE_SCHEMA_URL,
                "processingType": LineageConstants.PROCESSING_TYPE_BATCH,
                "integration": LineageConstants.INTEGRATION_NAME,
                "jobType": LineageConstants.JOB_TYPE_FLOW,
            },
            "documentation": {
                "_producer": self._producer,
                "_schemaURL": LineageConstants.DOCUMENTATION_JOB_FACET_URL,
                "description": f"Docling-pipelines flow: {flow_name}",
            },
        }
        if flow_def:
            facets["docpipeFlowId"] = {
                "_producer": self._producer,
                "flowId": self._resolve_flow_id(flow_id=flow_id, flow_def=flow_def),
            }
        return LineageJob(namespace=self._namespace, name=flow_name, facets=facets)

    def _build_node_job(self, *, context: Any) -> LineageJob:
        """Build a LineageJob for a DAG node (operator mode).

        Job name is ``{flow_name}/{node_name}`` — stable across START/COMPLETE/FAIL
        so Marquez can correlate all events for the same operator under one job entry.
        """
        flow_name = getattr(context, "flow_name", "") or getattr(context, "flow_id", "") or ""
        node_name = getattr(context, "node_name", "") or getattr(context, "node_id", "") or ""
        job_name = f"{flow_name}/{node_name}"

        job_type_facet: dict[str, Any] = {
            "_producer": self._producer,
            "_schemaURL": LineageConstants.JOB_TYPE_SCHEMA_URL,
            "processingType": LineageConstants.PROCESSING_TYPE_BATCH,
            "integration": LineageConstants.INTEGRATION_NAME,
            "jobType": LineageConstants.JOB_TYPE_OPERATOR,
        }
        # Surface the operator's short_name and category so consumers can
        # tell what kind of action this job performs without opening the run.
        operator_type = getattr(context, "operator_type", None)
        operator_category = getattr(context, "operator_category", None)
        if operator_type:
            job_type_facet["operator"] = operator_type
        if operator_category:
            job_type_facet["operatorCategory"] = operator_category

        return LineageJob(
            namespace=self._namespace,
            name=job_name,
            facets={"jobType": job_type_facet},
        )

    def _build_node_input_dataset_name(self, *, flow_name: str, predecessor_node_ids: list[str], node_name: str) -> str:
        """Derive the input dataset name for a node.

        When predecessors exist the input dataset name matches the predecessor's
        output dataset name — this is what makes Marquez draw an edge between them.
        Falls back to the node's own name when there are no predecessors (ingest).
        """
        if predecessor_node_ids:
            return f"{flow_name}/{predecessor_node_ids[0]}/output"
        return f"{flow_name}/{node_name}/input"

    def _build_node_output_dataset_name(self, *, flow_name: str, node_name: str, index: int = 0) -> str:
        """Derive the output dataset name for a node.

        Must match ``_build_node_input_dataset_name`` of the downstream node so
        Marquez stitches the two jobs together with a shared dataset edge.
        """
        if index == 0:
            return f"{flow_name}/{node_name}/output"
        return f"{flow_name}/{node_name}/output_{index}"

    def _build_dataset_from_summary(
        self,
        *,
        summary: NodeTableSummary,
        name: str,
        namespace: str | None = None,
    ) -> LineageDataset:
        """Build a dataset from a lightweight NodeTableSummary (no live Arrow data required)."""
        return LineageDataset(
            namespace=namespace or self._namespace,
            name=name,
            facets={
                "schema": {
                    "_producer": self._producer,
                    "_schemaURL": LineageConstants.SCHEMA_DATASET_FACET_URL,
                    "fields": [{"name": col, "type": typ} for col, typ in summary.schema_fields],
                },
                "outputStatistics": {
                    "_producer": self._producer,
                    "_schemaURL": LineageConstants.OUTPUT_STATISTICS_FACET_URL,
                    "rowCount": summary.row_count,
                },
            },
        )

    def _build_parent_run_facet(self, *, flow_name: str, job_run_id: str) -> dict[str, Any]:
        """Build the standard OpenLineage ``parent`` run facet.

        Links a node-level run back to its parent flow run so Marquez can
        display operator runs nested inside their flow run rather than as
        independent peer jobs in the Jobs list.

        The ``parent.job.name`` must exactly match the flow-level job name
        already registered in Marquez — using ``flow_name`` (the human-readable
        name from the flow definition) guarantees this.
        """
        return {
            "parent": {
                "_producer": self._producer,
                "_schemaURL": LineageConstants.PARENT_RUN_FACET_URL,
                "job": {
                    "namespace": self._namespace,
                    "name": flow_name,
                },
                "run": {
                    "runId": job_run_id,
                },
            }
        }

    def _build_node_stats_facet(self, *, metadata: dict[str, Any]) -> dict[str, Any]:
        """Build a ``docpipeStats`` run facet from an operator's output metadata dict.

        Includes all scalar (int, float, str, bool) values from the metadata that
        are not internal-only keys, mapped to camelCase names.  This surfaces
        both universal metrics (processedDocs, nodeStatus) and operator-specific
        ones (totalChunks, docsBeforeFilter, chunksIndexedSuccessfully, etc.)
        without any operator needing to know lineage exists.
        """
        if not metadata:
            return {}

        stats: dict[str, Any] = {}
        for key, value in metadata.items():
            if key in _INTERNAL_LINEAGE_KEYS:
                continue
            # Skip credential keys — operator metadata must not leak secrets.
            if key.lower() in _CREDENTIALS_KEYS:
                continue
            # Only include scalar values — skip tables, lists, nested dicts.
            if not isinstance(value, (int, float, str, bool)):
                continue
            # Convert snake_case → camelCase for idiomatic facet field names.
            camel = LineageUtils.to_camel_case(key)
            stats[camel] = value

        if not stats:
            return {}

        return {
            "docpipeStats": {
                "_producer": self._producer,
                "_schemaURL": LineageConstants.DOCPIPE_NODE_STATS_FACET_URL,
                **stats,
            }
        }

    def _build_error_facet(self, *, message: str, exception: Exception | None = None) -> dict[str, Any]:
        facet: dict[str, Any] = {
            "errorMessage": {
                "_producer": self._producer,
                "_schemaURL": LineageConstants.ERROR_MESSAGE_FACET_URL,
                "message": message,
                "programmingLanguage": "Python",
            }
        }
        if exception is not None:
            facet["errorMessage"]["stackTrace"] = "".join(
                traceback.format_exception(type(exception), exception, exception.__traceback__)
            )
        return facet

    def _build_nominal_time_facet(self, *, start_time: datetime | str | None) -> dict[str, Any]:
        if start_time is None:
            return {}
        return {
            "nominalTime": {
                "_producer": self._producer,
                "_schemaURL": LineageConstants.NOMINAL_TIME_FACET_URL,
                "nominalStartTime": str(start_time),
            }
        }

    @staticmethod
    def _resolve_flow_id(*, flow_id: str, flow_def: dict[str, Any]) -> str:
        """Use flow_id directly; fall back to SHA-256 of credentials-stripped flow_def."""
        return LineageUtils.resolve_flow_id(flow_id=flow_id, flow_def=flow_def)

    @staticmethod
    def _strip_credentials(flow_def: dict[str, Any]) -> dict[str, Any]:
        """Recursively remove credential keys from a flow definition dict."""
        return LineageUtils.strip_credentials(flow_def)

    @staticmethod
    def _node_run_id(*, job_run_id: str, node_id: str) -> str:
        """Derive a deterministic UUID for a node run from the job run ID and node ID."""
        return LineageUtils.node_run_id(job_run_id=job_run_id, node_id=node_id)

    @staticmethod
    def resolve_status(*, status: str | ExecutionStatus) -> LineageEventType:
        """Map an ExecutionStatus value to a LineageEventType."""
        value = status.value if isinstance(status, ExecutionStatus) else status
        return _STATUS_MAP.get(value, LineageEventType.OTHER)
