"""Abstract base class for all docpipe flow orchestrators."""

import threading
from abc import ABC, abstractmethod
from operator import itemgetter
from queue import Queue
from typing import Any, ParamSpec, TypeVar

import pyarrow as pa
from data_processing.data_access import DataAccess, DataAccessFactory

from docpipe.core.constants.constants import (
    TERMINAL_JOB_STATUSES,
    DocpipeConstants,
    ExecutionStatus,
    LineageConstants,
    Metrics,
)
from docpipe.core.constants.operator_constants import OperatorConstants
from docpipe.core.incremental_metadata import get_incremental_update_service
from docpipe.core.job_management.domain.ports import JobRunManager, JobStatsService
from docpipe.core.lineage.domain.ports.execution_lifecycle_observer import ExecutionLifecycleObserverPort
from docpipe.core.models.session_info import SessionInfo, get_session_info, set_session_info
from docpipe.core.operators.abstract_operator import OperatorCategory
from docpipe.core.operators.operator_utils import OperatorUtils
from docpipe.core.orchestration.abstract_operator_executor import AbstractOperatorExecutor
from docpipe.core.orchestration.batch_manager import BatchManager
from docpipe.core.orchestration.flow_execution_event_handler import FlowExecutionEventHandler
from docpipe.core.orchestration.models.execution_event_context import NodeTableSummary, SinkDatasetInfo
from docpipe.core.orchestration.ports.flow_engine import ExecuteStepResults, FlowEnginePort
from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException
from docpipe.utils.core.datetime import get_current_timestamp
from docpipe.utils.data.pyarrow_handler import BaseParquetTableHandler, get_parquet_table_handler
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.orchestration.deleted_rows_tracker import (
    combine_cumulative_deleted_rows,
)
from docpipe.utils.orchestration.flow_utils import construct_deleted_rows_table_path
from docpipe.utils.orchestration.prefect_config import (
    clean_up_prefect_home,
)

logger = get_logger()

R = TypeVar("R")  # The return type of the user's function
P = ParamSpec("P")


class AbstractOrchestrator(ABC):
    """Base class defining the orchestration contract for executing flow DAGs.

    Subclasses implement ``create_executor_impl`` and ``_create_flow_engine``
    to provide engine-specific execution behaviour (Python, Prefect, etc.)."""

    def __init__(
        self,
        *,
        job_stats_service: JobStatsService | None = None,
        job_run_manager: JobRunManager | None = None,
        enable_custom_operators: bool = True,
        custom_operator_packages: list[str] | None = None,
        execution_reporter=None,
        observer: ExecutionLifecycleObserverPort | None = None,
    ) -> None:
        """
        Initialize orchestrator with optional job services.

        Args:
            job_stats_service: Optional job statistics service for tracking job execution
            job_run_manager: Optional framework job run manager for external status updates
            enable_custom_operators: Whether to enable custom operators (passed to operator factory)
            custom_operator_packages: List of custom operator packages (passed to operator factory)
            execution_reporter: Optional output formatter for user-friendly console output
            observer: Optional lifecycle observer for lineage emission
        """
        self.enable_custom_operators = enable_custom_operators
        self.custom_operator_packages = custom_operator_packages
        self.job_status = ExecutionStatus.RUNNING
        self.job_run_id: str | None = None
        self.job_id: str | None = None
        self.context_id: str | None = None
        self.jobs_client = None
        self.logger = get_logger()
        self.message: str | None = ""
        self.flow_id = None
        self.deleted_rows_list: Queue[pa.Table] = Queue()
        # Per-batch store: dict[batch_id, list[pa.Table]].
        # Keyed by batch_id so concurrent batches never clobber each other's tables.
        # Non-batched flows use None as the key (same behaviour as before).
        self._non_recoverable_docs_tables: dict[str | None, list[pa.Table]] = {}
        self.job_stats_service = job_stats_service
        self.job_run_manager = job_run_manager
        self.flow_execution_event_handler = FlowExecutionEventHandler(
            job_stats_service=job_stats_service,
            job_run_manager=job_run_manager,
            execution_reporter=execution_reporter,
        )
        self.batch_manager = BatchManager()
        self.flow_engine: FlowEnginePort | None = None
        self.common_log_arguments: dict[Any, str] | None = None
        self._observer = observer
        # Batch numbers that hit a node failure. Keyed by batch so continue mode can
        # tell "this batch failed" from "some other batch failed" — job_status cannot,
        # because one orchestrator is shared by every batch thread in the ThreadPool
        # path and setting it to FAILING would short-circuit the batches still running.
        self._failed_batch_nums: set[Any] = set()
        self._failed_batch_lock = threading.Lock()
        # External sink datasets written by this flow, keyed by (namespace, name). Batches share this
        # orchestrator, so a sink that runs once per batch is aggregated into a single entry.
        self.sink_datasets: dict[tuple[str, str], SinkDatasetInfo] = {}
        self._sink_datasets_lock = threading.Lock()

    @property
    def non_recoverable_docs_tables(self) -> list[pa.Table]:
        """Backward-compatible view of the None-keyed (non-batched) bucket.

        Tests and non-batched callers that read or set this attribute directly
        continue to work without changes.
        """
        return self._non_recoverable_docs_tables.setdefault(None, [])

    @non_recoverable_docs_tables.setter
    def non_recoverable_docs_tables(self, value: list[pa.Table]) -> None:
        self._non_recoverable_docs_tables[None] = value

    def _notify_observer(self, method_name: str, **kwargs: Any) -> None:
        """Route a lifecycle event to the observer after the existing handler has run.

        Exceptions from the observer are swallowed in best-effort mode (default) and
        re-raised only when DOCPIPE_LINEAGE_STRICT=true.

        Args:
            method_name: Name of the ExecutionLifecycleObserverPort method to call.
            **kwargs: Keyword arguments forwarded to the observer method.
        """
        if self._observer is None:
            return
        try:
            getattr(self._observer, method_name)(**kwargs)
        except Exception as exc:
            if LineageConstants.DEFAULT_STRICT.lower() == "true":
                raise
            logger.warning("Lineage observer error in %s (best-effort, swallowing): %s", method_name, exc)

    def initialize(self, *, job_id: str, job_run_id: str):
        """
        Initialize orchestrator for a specific job run.

        Args:
            job_id: Job identifier
            job_run_id: Job run identifier
        """
        # Skip if already initialized for this job_run_id
        if self.flow_engine is not None and self.job_run_id == job_run_id:
            return

        self.flow_id = get_session_info().flow_id
        self.job_id = job_id
        self.job_run_id = job_run_id
        self.common_log_arguments = {
            DocpipeConstants.JOB_ID: self.job_id,
            DocpipeConstants.JOB_RUN_ID: self.job_run_id,
        }

        # Initialize event handler for this job run
        self.flow_execution_event_handler.initialize(
            job_id=job_id, job_run_id=job_run_id, common_log_arguments=self.common_log_arguments
        )

        # Create flow engine via factory method (dependency injection)
        self.flow_engine = self._create_flow_engine(
            job_id=job_id,
            job_run_id=job_run_id,
            job_log_path=self.flow_execution_event_handler.job_log_path,
        )

    @abstractmethod
    def _create_flow_engine(self, *, job_id: str, job_run_id: str, job_log_path: str) -> FlowEnginePort:
        """
        Factory method for creating the flow engine.

        Subclasses must implement this to provide their specific flow engine implementation.
        This enables dependency injection and allows different orchestrators to use
        different execution engines (Prefect, Airflow, pure Python, etc.).

        Args:
            job_id: Job identifier
            job_run_id: Job run identifier
            job_log_path: Path for job logs

        Returns:
            FlowEnginePort: The flow engine implementation
        """
        ...

    def execute(self, *, flow_def: dict, params: dict):
        """
        Executes the given flow
        """
        job_id, job_run_id = itemgetter(DocpipeConstants.JOB_ID, DocpipeConstants.JOB_RUN_ID)(params)

        # Initialize the orchestrator with job_id and job_run_id
        self.initialize(job_id=job_id, job_run_id=job_run_id)

        flow_global_config = flow_def.get(OperatorConstants.Config.GLOBAL_CONFIG, {})
        global_config = flow_global_config | params | {DocpipeConstants.FLOW_DEFINITION: flow_def}

        if DocpipeConstants.DAG not in flow_def:
            raise FlowExecutionFailedException("Invalid flow: 'dag' not found in the flow definition")

        op_flow = flow_def.get(DocpipeConstants.DAG, [])

        # Store flow name for use in all subsequent lifecycle events
        self.flow_name = flow_def.get(DocpipeConstants.NAME, self.flow_id or "")

        self.flow_execution_event_handler.before_flow_execution_start(orchestrator=self, flow_def=flow_def)
        from docpipe.core.orchestration.models.execution_event_context import FlowStartContext

        operator_names = [
            node.get(OperatorConstants.Misc.OPERATOR, node.get(OperatorConstants.Columns.NAME, ""))
            for node in flow_def.get(DocpipeConstants.DAG, [])
        ]
        self._notify_observer(
            "on_flow_start",
            context=FlowStartContext(
                flow_id=self.flow_id or "",
                flow_name=self.flow_name,
                job_run_id=job_run_id,
                flow_def=flow_def,
                operator_names=operator_names,
            ),
        )
        self.context_id = params.get(DocpipeConstants.CONTEXT_ID, self.job_id)
        try:
            self.execute_flow(op_flow=op_flow, global_config=global_config)
        finally:
            self._check_and_upload_deleted_rows()
            self._cleanup_memmap_files()

    def _get_ingest_summary_message(self, *, output_table, deleted_docs_count: int, operator: dict) -> str | None:
        """Process and log ingest step results."""
        if output_table.num_rows == 0 and operator[OperatorConstants.Misc.OPERATOR] != OperatorConstants.Operators.NOOP:
            message = "No documents are ingested."
            if deleted_docs_count > 0:
                message += f" But {deleted_docs_count} document{'s' if deleted_docs_count != 1 else ''} {'were' if deleted_docs_count != 1 else 'was'} removed."
            self.logger.info(message, extra=self.common_log_arguments)
            return message
        return None

    def _handle_node_failure(self, *, e, op_def, global_config, start=None):
        # Check if continue_on_batch_failure is enabled
        """Handle a node-level failure, updating job status and notifying the event handler.

        Args:
            e: The exception that caused the failure.
            op_def: The operator definition dict.
            global_config: Current global configuration.
            start: Optional start timestamp captured before execution began."""
        is_batching_enabled = global_config.get(DocpipeConstants.ENABLE_MICRO_BATCHING, False)
        continue_on_batch_failure = global_config.get(
            DocpipeConstants.CONTINUE_ON_BATCH_FAILURE,
            DocpipeConstants.CONTINUE_ON_BATCH_FAILURE_DEFAULT,
        )

        # Record the failure against this batch before applying any policy. In
        # continue_on_batch_failure mode job_status stays RUNNING so the remaining
        # batches keep going, which leaves the submitter with no other way to learn
        # that this batch failed.
        self._record_batch_failure(global_config=global_config)

        # Only set job_status to FAILING if not in continue_on_batch_failure mode
        # In continue_on_batch_failure mode, status will be determined by after_flow_execution_complete
        if not (is_batching_enabled and continue_on_batch_failure):
            self.job_status = ExecutionStatus.FAILING
            # Capture error message for job-level message field
            self.message = str(e)

        self.flow_execution_event_handler.after_node_failure(
            node_id=op_def[OperatorConstants.Columns.ID],
            node_name=op_def[OperatorConstants.Columns.NAME],
            global_config=global_config,
            e=e,
        )
        from docpipe.core.orchestration.models.execution_event_context import NodeFailContext

        self._notify_observer(
            "on_node_fail",
            context=NodeFailContext(
                flow_id=self.flow_id or "",
                flow_name=getattr(self, "flow_name", self.flow_id or ""),
                job_run_id=self.job_run_id or "",
                node_id=op_def[OperatorConstants.Columns.ID],
                node_name=op_def[OperatorConstants.Columns.NAME],
                operator_type=op_def.get(OperatorConstants.Misc.OPERATOR, ""),
                error_message=str(e),
                exception=e,
                start_time=start,
                end_time=get_current_timestamp(),
            ),
        )

    def _record_batch_failure(self, *, global_config) -> None:
        """Mark the batch in global_config as having had a node failure.

        Args:
            global_config: Current global configuration; carries BATCH_NUM."""
        batch_num = global_config.get(DocpipeConstants.BATCH_NUM)
        if batch_num is None:
            return
        with self._failed_batch_lock:
            self._failed_batch_nums.add(batch_num)

    def has_batch_failed(self, *, batch_num) -> bool:
        """Whether the given batch hit a node failure.

        Args:
            batch_num: Batch number to check.

        Returns:
            True if a node in that batch failed."""
        with self._failed_batch_lock:
            return batch_num in self._failed_batch_nums

    def _handle_active_execution(
        self,
        *,
        op_def,
        executor: AbstractOperatorExecutor,
        prev_data_access: dict[str, DataAccess | None] | DataAccess | None,
        batch_id: str | None = None,
    ):
        """Execute an active operator and collect its outputs and metadata.

        Args:
            op_def: Operator definition dict.
            executor: The executor instance wrapping the operator.
            prev_data_access: Data access(es) from the previous step.
            batch_id: Current batch identifier (None for non-batched flows).

        Returns:
            Tuple of (data_accesses, tables, metadata, internal_metadata)."""
        if executor.get_operator().short_name == OperatorConstants.Operators.DESIGN_FLOW_OUTPUT_OPERATOR:
            # save the deleted rows as this is needed for DESIGN_FLOW_OUTPUT_OPERATOR
            self._check_and_upload_deleted_rows()

        # LATER: based on some config, pass None to deleted_rows_list to skip tracking deleted rows
        data_accesses, metadata = executor.execute(
            data_access=prev_data_access, deleted_rows_list=self.deleted_rows_list
        )

        # Removing the internal metrics from the operator metadata if any to another dict
        internal_metadata = OperatorUtils.remove_internal_metrics_from_metadata(metadata=metadata)

        # Collect non-recoverable docs table from this operator's internal metadata
        self._collect_non_recoverable_docs(
            internal_metadata=internal_metadata,
            op_def=op_def,
            common_log_arguments=self.common_log_arguments or {},
            batch_id=batch_id,
        )

        operator = executor.get_operator()
        retain_deleted = operator.config.get(
            DocpipeConstants.RETAIN_DELETED_DOCS,
            DocpipeConstants.RETAIN_DELETED_DOCS_DEFAULT,
        )
        force_ingest = operator.config.get(DocpipeConstants.FORCE_INGEST, False)

        if operator.category == OperatorCategory.Ingest and not force_ingest:
            if not retain_deleted:
                metadata[Metrics.Internal.DELETED_FROM_LAST_RUN] = internal_metadata.get(
                    Metrics.Internal.DELETED_FROM_LAST_RUN, 0
                )
            else:
                metadata[Metrics.Internal.DELETED_FROM_LAST_RUN] = "N/A"

        tables = self.__get_tables_from_data_accesses(executor=executor, data_accesses=data_accesses)

        return data_accesses, tables, metadata, internal_metadata

    def _handle_skipped_execution(
        self,
        *,
        op_def,
        executor: AbstractOperatorExecutor,
        prev_results: ExecuteStepResults | dict[str, ExecuteStepResults],
        global_config,
        start,
    ):
        """Handle a skipped operator step, propagating previous results.

        Args:
            op_def: Operator definition dict.
            executor: The executor wrapping the skipped operator.
            prev_results: Results from the previous step.
            global_config: Current global configuration.
            start: Step start timestamp.

        Returns:
            Tuple of (data_accesses, tables)."""
        tables = (
            prev_results.tables
            if isinstance(prev_results, ExecuteStepResults)
            else [res.tables[0] for res in prev_results.values()]
        )
        data_accesses = executor.create_data_accesses(tables)
        end_time = get_current_timestamp()

        column_names = (
            prev_results.tables[0].column_names
            if isinstance(prev_results, ExecuteStepResults) and len(prev_results.tables) == 1
            else []
        )

        self.flow_execution_event_handler.after_node_skipped(
            node_id=op_def.get(OperatorConstants.Columns.ID),
            node_name=op_def.get(OperatorConstants.Columns.NAME),
            operator_type=op_def.get(OperatorConstants.Misc.OPERATOR),
            global_config=global_config,
            start_time=start,
            end_time=end_time,
            column_names=column_names,
        )
        from docpipe.core.orchestration.models.execution_event_context import NodeSkipContext

        self._notify_observer(
            "on_node_skip",
            context=NodeSkipContext(
                flow_id=self.flow_id or "",
                flow_name=getattr(self, "flow_name", self.flow_id or ""),
                job_run_id=self.job_run_id or "",
                node_id=op_def.get(OperatorConstants.Columns.ID, ""),
                node_name=op_def.get(OperatorConstants.Columns.NAME, ""),
                operator_type=op_def.get(OperatorConstants.Misc.OPERATOR, ""),
                reason="Skipped - no input data to process",
                start_time=start,
                end_time=end_time,
            ),
        )

        return data_accesses, tables

    def _unpack_prev_results(
        self, *, prev_results: ExecuteStepResults | dict[str, ExecuteStepResults]
    ) -> tuple[Any, Any]:
        """Unpack prev_results into (prev_data_access, prev_table) regardless of shape."""
        if isinstance(prev_results, ExecuteStepResults):
            return (
                prev_results.data_accesses[0] if prev_results.data_accesses else None,
                prev_results.tables[0] if prev_results.tables else None,
            )
        # prev_results is a dict of [str, ExecuteStepResults]
        prev_data_access = {
            link_name: res.data_accesses[0] if res.data_accesses else None for link_name, res in prev_results.items()
        }
        prev_table = [res.tables[0] if res.tables else None for res in prev_results.values()]
        return prev_data_access, prev_table

    def _refresh_job_status(self) -> None:
        """Pull the latest job status from the job stats service and update self.job_status."""
        if self.job_stats_service and self.job_run_id:
            job_stats = self.job_stats_service.get_job(job_run_id=self.job_run_id, include_node_stats=False)
            if job_stats:
                self.job_status = ExecutionStatus(job_stats.status)

    def _resolve_predecessor_names(self, *, op_def: dict) -> list[str]:
        """Return the human-readable names of upstream nodes for a given op_def.

        Reads ``input_edges[*].node_id_ref`` and resolves each ID to its name
        using the ``_node_id_to_name`` map built at the start of ``execute_flow``.
        Falls back to the raw ID when the map is absent (e.g. batch subflows).
        """
        lookup: dict[str, str] = getattr(self, "_node_id_to_name", {})
        return [
            lookup.get(edge[DocpipeConstants.NODE_ID_REF], edge[DocpipeConstants.NODE_ID_REF])
            for edge in op_def.get(DocpipeConstants.INPUT_EDGES, [])
            if DocpipeConstants.NODE_ID_REF in edge
        ]

    def _execute_step(
        self,
        *,
        op_def,
        global_config,
        prev_results: ExecuteStepResults | dict[str, ExecuteStepResults],
        deleted_docs_count,
    ):
        """Execute or skip a single DAG step and return its results.

        Args:
            op_def: Operator definition dict.
            global_config: Current global configuration.
            prev_results: Results from the previous step.
            deleted_docs_count: Number of deleted documents from the ingest step.

        Returns:
            ExecuteStepResults for the current step."""
        start = get_current_timestamp()

        # CRITICAL FIX: Check job_status BEFORE creating executor to prevent downstream
        # operators from executing when an upstream operator fails in fail-fast mode.
        # This prevents resource waste and potential side effects.
        if self.job_status in (ExecutionStatus.FAILING, ExecutionStatus.CANCELING):
            self.logger.info(
                "Skipping operator %s - job is in %s state",
                op_def[OperatorConstants.Columns.NAME],
                self.job_status.value,
                extra=self.common_log_arguments,
            )
            # Return empty result to signal skip to downstream operators
            return ExecuteStepResults([], [], {})

        executor = self.create_executor(op_def=op_def, global_config=global_config)
        try:
            return self._run_node(
                op_def=op_def,
                executor=executor,
                prev_results=prev_results,
                global_config=global_config,
                deleted_docs_count=deleted_docs_count,
                start=start,
            )
        finally:
            # Release operator-held resources (e.g. the FastText model reference)
            # once we are done with this executor.  Covers both the executed and
            # the skipped path -- a skipped operator has still been constructed by
            # get_operator() and may hold a reference.  Never raises.
            executor.release()

    def _run_node(self, *, op_def, executor, prev_results, global_config, deleted_docs_count, start):
        """Body of a single node execution.  See _execute_step."""
        from docpipe.core.orchestration.models.execution_event_context import NodeTableSummary

        prev_data_access, prev_table = self._unpack_prev_results(prev_results=prev_results)
        skip = self.evaluate_execution_skip(executor=executor, tables=prev_table, deleted_docs_count=deleted_docs_count)
        metadata = {}
        internal_metadata = {}
        if skip:
            data_accesses, tables = self._handle_skipped_execution(
                op_def=op_def, executor=executor, prev_results=prev_results, global_config=global_config, start=start
            )
        else:
            data_accesses, tables, metadata, internal_metadata = self._handle_active_execution(
                op_def=op_def,
                executor=executor,
                prev_data_access=prev_data_access,
                batch_id=global_config.get(DocpipeConstants.BATCH_ID),
            )

        processed_docs_count = OperatorUtils.find_doc_count_from_tables(tables=tables)
        if Metrics.External.PROCESSED_DOCS not in metadata:
            metadata[Metrics.External.PROCESSED_DOCS] = processed_docs_count
        if internal_metadata.get(Metrics.Internal.DELETED_FROM_LAST_RUN):
            metadata[Metrics.External.DELETED_DOC_COUNT] = internal_metadata.get(Metrics.Internal.DELETED_FROM_LAST_RUN)

        self.flow_execution_event_handler.after_step_execution_complete(
            node_id=op_def[OperatorConstants.Columns.ID],
            node_name=op_def[OperatorConstants.Columns.NAME],
            operator_category=executor.get_operator().category,
            operator=op_def[OperatorConstants.Misc.OPERATOR],
            global_config=global_config,
            is_last_step=not op_def.get(DocpipeConstants.OUTPUT_EDGES),
            metadata=metadata,
            start_time=start,
            tables=tables,
        )

        if not skip:
            from docpipe.core.lineage.utils import LineageUtils
            from docpipe.core.orchestration.models.execution_event_context import NodeCompleteContext

            # Track the last output table for flow-level COMPLETE lineage event
            if tables:
                self.last_output_table = tables[0]

            sink_info = LineageUtils.derive_dataset_info_from_sink(operator_def=op_def)
            sink_ns, sink_name = (sink_info[0], sink_info[1]) if sink_info else (None, None)
            if sink_info:
                self._record_sink_dataset(namespace=sink_info[0], name=sink_info[1], tables=tables)

            end_time = get_current_timestamp()
            predecessor_node_ids = self._resolve_predecessor_names(op_def=op_def)
            self._notify_observer(
                "on_node_complete",
                context=NodeCompleteContext(
                    flow_id=self.flow_id or "",
                    flow_name=getattr(self, "flow_name", self.flow_id or ""),
                    job_run_id=self.job_run_id or "",
                    node_id=op_def[OperatorConstants.Columns.ID],
                    node_name=op_def[OperatorConstants.Columns.NAME],
                    operator_type=op_def.get(OperatorConstants.Misc.OPERATOR, ""),
                    operator_category=str(executor.get_operator().category.value),
                    output_summaries=[NodeTableSummary.from_table(t) for t in tables if t is not None],
                    metadata=metadata,
                    start_time=start,
                    end_time=end_time,
                    predecessor_node_ids=predecessor_node_ids,
                    sink_dataset_namespace=sink_ns,
                    sink_dataset_name=sink_name,
                    has_downstream=bool(op_def.get(DocpipeConstants.OUTPUT_EDGES)),
                ),
            )

        # Update job status from job stats service
        self._refresh_job_status()

        return ExecuteStepResults(data_accesses, tables, internal_metadata)

    def _record_sink_dataset(self, *, namespace: str, name: str, tables: list[pa.Table | None]) -> None:
        """Record what a sink wrote, aggregating row counts when the sink runs once per micro-batch."""
        table = next((t for t in tables if t is not None), None)
        if table is None:
            return
        summary = NodeTableSummary.from_table(table)
        with self._sink_datasets_lock:
            existing = self.sink_datasets.get((namespace, name))
            if existing is None:
                self.sink_datasets[(namespace, name)] = SinkDatasetInfo(namespace=namespace, name=name, summary=summary)
            else:
                existing.summary.row_count += summary.row_count

    def __get_tables_from_data_accesses(self, *, executor, data_accesses):
        """Read tables from the data accesses produced by an operator.

        Args:
            executor: The operator executor.
            data_accesses: List of DataAccess objects.

        Returns:
            List of PyArrow tables.

        Raises:
            FlowExecutionFailedException: If a table cannot be read."""
        tables = []
        for data_access in data_accesses:
            output_file_path = executor.get_output_file_path(data_access=data_access)
            table, _ = data_access.get_table(output_file_path)
            if table is None:
                raise FlowExecutionFailedException(f"Failed while reading data from file: {output_file_path}")
            tables.append(table)
        return tables

    def evaluate_execution_skip(
        self,
        *,
        executor: AbstractOperatorExecutor,
        tables: pa.Table | list[pa.Table] | None,
        deleted_docs_count,
    ):
        """Determine whether a step should be skipped based on operator category and table state.

        Args:
            executor: The operator executor.
            tables: Current input table(s).
            deleted_docs_count: Number of deleted documents.

        Returns:
            True if the step should be skipped."""

        def all_tables_are_empty():
            if tables is None:
                return True
            if isinstance(tables, list):
                return all(table.num_rows == 0 for table in tables)
            return tables.num_rows == 0

        if executor.get_operator().category != OperatorCategory.Ingest:
            # Special case to delete the data from vector store when input documents are deleted,
            # and no new documents are added for this flow execution
            if executor.get_operator().category == OperatorCategory.VectorDB and deleted_docs_count > 0:
                return False
            if all_tables_are_empty():
                return True
        return False

    def _check_and_upload_deleted_rows(self):
        """Persist accumulated deleted-row tables to the parquet store."""
        if not self.deleted_rows_list.empty():
            if not self.job_id or not self.job_run_id:
                self.logger.warning("job id or job run id must be needed to save unprocessed docs")
                return
            try:
                cumulative_deleted_rows = combine_cumulative_deleted_rows(self.deleted_rows_list)
                deleted_rows_table_path = self.get_deleted_rows_table_path_impl(
                    job_id=self.job_id, job_run_id=self.job_run_id
                )
                # This will be replaced by TableStoragePort once the storage abstraction refactor is complete
                parquet_table_handler: BaseParquetTableHandler = self.get_parquet_table_handler_impl()
                # delete table if exists already
                parquet_table_handler.delete_file(path=deleted_rows_table_path)
                parquet_table_handler.save_table(path=deleted_rows_table_path, table=cumulative_deleted_rows)
                self.logger.info("Successfully captured %d deleted documents.", cumulative_deleted_rows.num_rows)
            except Exception as e:
                self.logger.warning("Failed to save unprocessed docs table — skipping it. Error: %s", e)

    def get_parquet_table_handler_impl(self) -> BaseParquetTableHandler:
        """Return the parquet table handler implementation.

        Returns:
            A BaseParquetTableHandler instance."""
        return get_parquet_table_handler()

    def get_deleted_rows_table_path_impl(self, *, job_id: str, job_run_id: str) -> str:
        """Return the file path for the deleted-rows parquet table.

        Args:
            job_id: Job identifier.
            job_run_id: Job run identifier.

        Returns:
            Filesystem path string."""
        return construct_deleted_rows_table_path(job_id=job_id, job_run_id=job_run_id)

    def _mark_pending_batches_as_skipped(self) -> None:
        """
        Mark all PENDING/QUEUED batch node stats as SKIPPED when flow fails in fail-fast mode.

        This ensures proper status aggregation - without this, pending batches cause
        operators to show as "Running" instead of their actual terminal status.
        """
        if not self.job_stats_service or not self.job_run_id:
            return

        try:
            self.job_stats_service.mark_pending_batches_as_skipped(
                job_run_id=self.job_run_id, reason="Skipped - flow failed in fail-fast mode before batch execution"
            )
            self.logger.info(
                "Marked pending batches as skipped due to fail-fast mode failure", extra=self.common_log_arguments
            )
        except Exception as e:
            self.logger.warning("Failed to mark pending batches as skipped: %s", e, extra=self.common_log_arguments)

    def _cleanup_memmap_files(self):
        """Clean up temporary memmap files after flow execution if memmap storage was used."""
        if not self.job_id or not self.job_run_id:
            return

        # Only cleanup if memmap storage was enabled
        # Check if any operator in the flow used memmap storage
        try:
            from docpipe.utils.core.memmap_file_utils import cleanup_memmap_files

            cleanup_memmap_files(job_id=self.job_id, job_run_id=self.job_run_id)
        except Exception as e:
            self.logger.warning("Failed to cleanup memmap files: %s", e)

    def _collect_non_recoverable_docs(
        self,
        internal_metadata: dict,
        op_def: dict,
        common_log_arguments: dict,
        batch_id: str | None = None,
    ) -> None:
        """
        Collect non-recoverable docs table from operator internal metadata.

        Uses per-batch storage keyed by batch_id so concurrent batches each
        append to their own isolated list and never clobber one another.

        Args:
            internal_metadata: Internal metadata dict (not shown in UI)
            op_def: Operator definition
            common_log_arguments: Common logging arguments
            batch_id: Current batch identifier (None for non-batched flows)
        """
        if internal_metadata and Metrics.Internal.NON_RECOVERABLE_DOCS_TABLE in internal_metadata:
            non_rec_table = internal_metadata[Metrics.Internal.NON_RECOVERABLE_DOCS_TABLE]
            if non_rec_table and isinstance(non_rec_table, pa.Table) and non_rec_table.num_rows > 0:
                bucket = self._non_recoverable_docs_tables.setdefault(batch_id, [])
                bucket.append(non_rec_table)
                self.logger.info(
                    "Collected %d non-recoverable docs from operator '%s' (batch_id=%s). Tables in bucket: %d",
                    non_rec_table.num_rows,
                    op_def.get("name", "unknown"),
                    batch_id,
                    len(bucket),
                    extra=common_log_arguments,
                )

    def _merge_non_recoverable_docs(self, global_config: dict, common_log_arguments: dict) -> pa.Table | None:
        """
        Merge accumulated non-recoverable docs tables for the current batch into a single table.

        Args:
            global_config: Global configuration
            common_log_arguments: Common logging arguments

        Returns:
            Merged PyArrow table or None if no tables to merge
        """
        batch_id: str | None = global_config.get(DocpipeConstants.BATCH_ID)
        tables = self._non_recoverable_docs_tables.get(batch_id, [])

        if not tables:
            return None

        try:
            merged_table = pa.concat_tables(tables)

            batch_num = global_config.get(DocpipeConstants.BATCH_NUM)
            if batch_num is not None:
                self.logger.info(
                    "Batch %s: Merged %d tables with %d total non-recoverable docs",
                    batch_num,
                    len(tables),
                    merged_table.num_rows,
                    extra=common_log_arguments,
                )
            else:
                self.logger.info(
                    "Merged %d tables with %d total non-recoverable docs",
                    len(tables),
                    merged_table.num_rows,
                    extra=common_log_arguments,
                )
            return merged_table
        except Exception as e:
            self.logger.error(
                "Failed to merge non-recoverable docs tables: %s. Proceeding without non-recoverable docs tracking.",
                e,
                extra=common_log_arguments,
            )
            return None

    def _reset_non_recoverable_docs_for_batch(self, global_config: dict, common_log_arguments: dict) -> None:
        """
        Drop the non-recoverable docs bucket for the current batch.

        Each batch starts fresh. The dict entry is deleted (not just cleared)
        so the tables are freed immediately rather than holding an empty list.

        Args:
            global_config: Global configuration
            common_log_arguments: Common logging arguments
        """
        batch_num = global_config.get(DocpipeConstants.BATCH_NUM)
        if batch_num is not None:
            batch_id: str | None = global_config.get(DocpipeConstants.BATCH_ID)
            self.logger.debug(
                "Batch %s: Dropping non_recoverable_docs bucket (batch_id=%s)",
                batch_num,
                batch_id,
                extra=common_log_arguments,
            )
            self._non_recoverable_docs_tables.pop(batch_id, None)

    def _sync_cancellation_status(self) -> None:
        """Sync in-memory job status with persistent store if cancellation was requested."""
        if not self.job_stats_service or not self.job_run_id:
            return
        if self.job_status == ExecutionStatus.CANCELING or self.job_status in TERMINAL_JOB_STATUSES:
            return
        try:
            job_stats = self.job_stats_service.get_job_run_stats(job_run_id=self.job_run_id)
            if job_stats and job_stats.status == ExecutionStatus.CANCELING:
                self.job_status = ExecutionStatus.CANCELING
        except Exception:
            self.logger.warning("Failed to sync cancellation status from job stats service", exc_info=True)

    def cancel(self):
        """
        Request for cancelling a running job
        """
        self.job_status = ExecutionStatus.CANCELING

    def pause(self):
        """
        Request for pausing a running job
        """

    def resume(self):
        """
        Request for resuming a paused job
        """

    def get_type(self):
        """
        Returns the type of the orchestrator.
        """

    def create_executor(self, *, op_def: dict, global_config: dict) -> AbstractOperatorExecutor:
        # note: In the union of 2 dictionaries below, if an element exists in both global config and local config (
        # op_def['config']), the value from global_config will be overwritten by the local config
        """Build an operator executor from an operator definition and global config.

        Args:
            op_def: Operator definition dict from the flow DAG.
            global_config: Merged global and local config.

        Returns:
            An AbstractOperatorExecutor instance."""
        global_config = {} if global_config is None else global_config
        operator_name = op_def.get(OperatorConstants.Columns.NAME, "unknown")
        self.logger.debug(
            "create_executor for '%s': ingest_source in global_config=%s",
            operator_name,
            OperatorConstants.Config.INGEST_SOURCE in global_config,
            extra=self.common_log_arguments,
        )
        operator_config = op_def.get(OperatorConstants.Config.CONFIG, {})
        operator_config_params = global_config.get(
            op_def[OperatorConstants.Columns.NAME],
            global_config.get(
                op_def[OperatorConstants.Columns.ID],
                global_config.get(op_def[OperatorConstants.Misc.OPERATOR], {}),
            ),
        )

        operator_name = op_def[OperatorConstants.Columns.NAME]
        operator_id = op_def[OperatorConstants.Columns.ID]
        # 1. Configuration defined for the operator takes precedence over the global configuration in the flow.
        # 2. The operator configuration passed through parameters would override the operator config defined in the flow
        config = (
            {OperatorConstants.Columns.NAME: operator_name}
            | {OperatorConstants.Columns.ID: operator_id}
            | {DocpipeConstants.NODE_ID: operator_id}
            | {DocpipeConstants.NODE_NAME: operator_name}
            | global_config
            | {"common_log_arguments": self.common_log_arguments}
            | operator_config
            | operator_config_params
        )

        return self.create_executor_impl(
            name=operator_name,
            operator=op_def[OperatorConstants.Misc.OPERATOR],
            params=config,
            job_stats_service=self.job_stats_service,
        )

    @abstractmethod
    def create_executor_impl(
        self,
        *,
        name: str,
        operator: str,
        params: dict,
        job_stats_service: JobStatsService | None = None,
    ) -> AbstractOperatorExecutor:
        """The concrete subclasses needs to implement this method"""
        ...

    def _resolve_link_results(
        self,
        *,
        link_id: str,
        prev_results: ExecuteStepResults,
    ) -> ExecuteStepResults:
        """Resolve branch-specific output table and metadata for a given link_id."""
        if not isinstance(prev_results.internal_metadata, dict):
            return prev_results

        branches = prev_results.internal_metadata.get(Metrics.Internal.BRANCHES)
        if branches is None or not isinstance(branches, dict):
            raise FlowExecutionFailedException("Expected branches metadata as a dict but found None or wrong type")

        if len(prev_results.tables) != len(branches):
            raise FlowExecutionFailedException(
                f"Number of tables ({len(prev_results.tables)}) in previous operator output "
                f"do not match branches ({len(branches)}) created."
            )

        branch_info = branches.get(link_id, {})
        result_index = branch_info.get("result_index")
        if result_index is None:
            raise FlowExecutionFailedException(f"Result index not found for link_id {link_id}")

        table = prev_results.tables[result_index]
        data_access = prev_results.data_accesses[result_index]
        return ExecuteStepResults([data_access], [table], branch_info)

    def _handle_skipped_task(
        self,
        *,
        op_def: dict,
        global_config: dict,
    ) -> None:
        """Record node skip event with appropriate reason when execution cannot proceed."""
        if self.job_status == ExecutionStatus.CANCELING:
            skip_reason = "Skipped - job cancellation requested by user"
        elif self.job_status == ExecutionStatus.FAILING:
            skip_reason = "Skipped - cannot proceed due to failure in pipeline"
        else:
            skip_reason = "Skipped - no data received from previous step"

        now = get_current_timestamp()
        self.flow_execution_event_handler.after_node_skipped(
            node_id=op_def[OperatorConstants.Columns.ID],
            node_name=op_def[OperatorConstants.Columns.NAME],
            operator_type=op_def[OperatorConstants.Misc.OPERATOR],
            global_config=global_config,
            start_time=now,
            end_time=now,
            column_names=[],
            reason=skip_reason,
        )
        from docpipe.core.orchestration.models.execution_event_context import NodeSkipContext

        self._notify_observer(
            "on_node_skip",
            context=NodeSkipContext(
                flow_id=self.flow_id or "",
                flow_name=getattr(self, "flow_name", self.flow_id or ""),
                job_run_id=self.job_run_id or "",
                node_id=op_def[OperatorConstants.Columns.ID],
                node_name=op_def[OperatorConstants.Columns.NAME],
                operator_type=op_def.get(OperatorConstants.Misc.OPERATOR, ""),
                reason=skip_reason,
                start_time=now,
                end_time=now,
            ),
        )

    def _inner_task(
        self,
        op_def,
        global_config,
        prev_results: ExecuteStepResults | dict[str, ExecuteStepResults],
        session_info: SessionInfo,
        deleted_docs_count,
        link_id=None,
    ) -> ExecuteStepResults | None:
        """Execute or skip a single DAG node within a thread or task context.

        Args:
            op_def: Operator definition dict.
            global_config: Current global configuration.
            prev_results: Results from the previous step.
            session_info: Thread-local session information.
            deleted_docs_count: Deleted-document count from ingest.
            link_id: Optional branch link identifier.

        Returns:
            ExecuteStepResults or None if the step was skipped or failed."""
        self.flow_execution_event_handler.before_step_execution_start(
            node_id=op_def[OperatorConstants.Columns.ID],
            node_name=op_def[OperatorConstants.Columns.NAME],
            global_config=global_config,
            job_status=self.job_status,
            prev_results=prev_results,
        )
        from docpipe.core.orchestration.models.execution_event_context import NodeStartContext, NodeTableSummary

        node_start_time = get_current_timestamp()

        # Always emit on_node_start regardless of job status — symmetry with on_node_skip/fail.
        # Build input summary without holding the full table beyond this point.
        if prev_results is not None:
            _, prev_table = self._unpack_prev_results(prev_results=prev_results)
            raw_table = prev_table[0] if isinstance(prev_table, list) and prev_table else prev_table
            input_summary = NodeTableSummary.from_table(raw_table) if isinstance(raw_table, pa.Table) else None
            predecessor_node_ids = self._resolve_predecessor_names(op_def=op_def)
            self._notify_observer(
                "on_node_start",
                context=NodeStartContext(
                    flow_id=self.flow_id or "",
                    flow_name=getattr(self, "flow_name", self.flow_id or ""),
                    job_run_id=self.job_run_id or "",
                    node_id=op_def[OperatorConstants.Columns.ID],
                    node_name=op_def[OperatorConstants.Columns.NAME],
                    operator_type=op_def.get(OperatorConstants.Misc.OPERATOR, ""),
                    input_summary=input_summary,
                    predecessor_node_ids=predecessor_node_ids,
                    parent_run_id=self.job_run_id or "",
                    start_time=node_start_time,
                ),
            )

        self._sync_cancellation_status()

        # Record skipped node when upstream failure or cancellation prevents execution
        if prev_results is None or self.job_status in (ExecutionStatus.FAILING, ExecutionStatus.CANCELING):
            self._handle_skipped_task(op_def=op_def, global_config=global_config)
            return None

        set_session_info(session_info)

        try:
            if link_id and isinstance(prev_results, ExecuteStepResults):
                prev_results = self._resolve_link_results(link_id=link_id, prev_results=prev_results)

            return self._execute_step(
                op_def=op_def,
                global_config=global_config,
                prev_results=prev_results,
                deleted_docs_count=deleted_docs_count,
            )

        except Exception as e:
            self._handle_node_failure(e=e, op_def=op_def, global_config=global_config, start=node_start_time)
            # steps in output edges will exit early
            return None

    def _finalize_dag_flow(self, *, op_flow, global_config=None):
        """Notify the event handler that the full DAG has completed.

        Args:
            op_flow: The DAG operator list.
            global_config: Current global configuration."""
        self.flow_execution_event_handler.after_flow_execution_complete(
            op_flow=op_flow, present_job_status=self.job_status, message=self.message, global_config=global_config
        )
        from docpipe.core.lineage.application.lineage_service import LineageService
        from docpipe.core.orchestration.models.execution_event_context import (
            FlowAbortContext,
            FlowCompleteContext,
            FlowFailContext,
        )

        job_run_id = self.job_run_id or ""
        flow_id = self.flow_id or ""
        if self.job_status in (ExecutionStatus.CANCELING, ExecutionStatus.CANCELED):
            self._notify_observer(
                "on_flow_abort",
                context=FlowAbortContext(
                    flow_id=flow_id,
                    flow_name=getattr(self, "flow_name", flow_id),
                    job_run_id=job_run_id,
                    reason=self.message,
                ),
            )
        elif self.job_status in (ExecutionStatus.FAILING, ExecutionStatus.FAILED):
            self._notify_observer(
                "on_flow_fail",
                context=FlowFailContext(
                    flow_id=flow_id,
                    flow_name=getattr(self, "flow_name", flow_id),
                    job_run_id=job_run_id,
                    error_message=self.message or "",
                ),
            )
        else:
            event_type = LineageService.resolve_status(status=self.job_status)
            from docpipe.core.lineage.domain.models.event_type import LineageEventType

            if event_type != LineageEventType.FAIL and event_type != LineageEventType.ABORT:
                # Read final doc counts from job stats service
                _completed, _failed, _skipped, _total = 0, 0, 0, 0
                if self.job_stats_service and job_run_id:
                    try:
                        _job = self.job_stats_service.get_job(job_run_id=job_run_id, include_node_stats=False)
                        if _job:
                            _completed = _job.completed_docs or 0
                            _failed = _job.failed_docs or 0
                            _skipped = _job.skipped_docs or 0
                            _total = _job.total_docs or 0
                    except Exception as exc:
                        logger.debug("Could not read doc counts for lineage COMPLETE event: %s", exc)
                self._notify_observer(
                    "on_flow_complete",
                    context=FlowCompleteContext(
                        flow_id=flow_id,
                        flow_name=getattr(self, "flow_name", flow_id),
                        job_run_id=job_run_id,
                        flow_def=op_flow,
                        status=self.job_status.value,
                        output_tables=[getattr(self, "last_output_table", None)]
                        if getattr(self, "last_output_table", None) is not None
                        else [],
                        ingest_dataset_name=getattr(self, "ingest_dataset_name", None),
                        sink_datasets=list(self.sink_datasets.values()),
                        completed_docs=_completed,
                        failed_docs=_failed,
                        skipped_docs=_skipped,
                        total_docs=_total,
                    ),
                )

    @staticmethod
    def _derive_ingest_dataset_info(*, ingest_operator: dict) -> tuple[str, str]:
        """Derive standard OpenLineage (namespace, name) tuple from the ingest operator config."""
        from docpipe.core.lineage.utils import LineageUtils

        return LineageUtils.derive_dataset_info_from_ingest(ingest_operator=ingest_operator)

    def _derive_ingest_dataset_name(self, *, ingest_operator: dict) -> str:
        """Derive a human-readable dataset name from the ingest operator config.

        Delegates to LineageUtils.derive_ingest_dataset_name.
        """
        from docpipe.core.lineage.utils import LineageUtils

        return LineageUtils.derive_ingest_dataset_name(ingest_operator=ingest_operator)

    def _populate_ingest_source_config(self, *, ingest_operator, global_config):
        """
        Populate global_config with ingest_source params for lazy binary loading.

        Args:
            ingest_operator: The ingest operator definition
            global_config: Global configuration dictionary to be modified in place
        """
        operator_type = ingest_operator.get(OperatorConstants.Misc.OPERATOR, "")
        self.logger.info(
            "Checking if operator is ingest_source: operator_type='%s'",
            operator_type,
            extra=self.common_log_arguments,
        )
        if "ingest_source" in operator_type.lower() or "IngestSourceOperator" in operator_type:
            operator_config = ingest_operator.get(OperatorConstants.Config.CONFIG, {})
            provider_config = operator_config.get(OperatorConstants.Config.PROVIDER_CONFIG, {})

            global_config[OperatorConstants.Config.INGEST_SOURCE] = {
                OperatorConstants.Config.PROVIDER: operator_config.get(OperatorConstants.Config.PROVIDER),
                OperatorConstants.Config.PROVIDER_CONFIG: provider_config,
            }
            self.logger.info(
                "Populated global_config with ingest_source params for provider: %s",
                operator_config.get(OperatorConstants.Config.PROVIDER),
                extra=self.common_log_arguments,
            )
            self.logger.debug(
                "global_config after population: ingest_source keys=%s, provider_config keys=%s",
                list(global_config.get(OperatorConstants.Config.INGEST_SOURCE, {}).keys()),
                list(provider_config.keys()),
                extra=self.common_log_arguments,
            )
        else:
            self.logger.info(
                "Operator is NOT ingest_source, skipping global_config population",
                extra=self.common_log_arguments,
            )

    # ??? insert some of the parameters to self.
    def execute_flow(self, *, op_flow, global_config):
        """
        Execute DAG flow with unified batching approach.
        Supports both batch mode (multiple batches) and non-batch mode (single table).

        Batch Creation Rules:
        - Batches are created ONLY when ALL conditions are met:
          1. ENABLE_MICRO_BATCHING is True (batching feature enabled)
        - When batching is enabled, MICRO_BATCH_SIZE is read (defaults to DEFAULT_MICRO_BATCH_SIZE)
        - Otherwise, entire ingested table is treated as single "batch" for unified execution

        """

        # Sinks are collected per flow execution; a reused orchestrator must not carry them over.
        with self._sink_datasets_lock:
            self.sink_datasets = {}

        # Configure prefect server logging
        _ = get_logger(name="prefect")

        self.logger.info(">>> Starting flow execution with unified batching approach", extra=self.common_log_arguments)

        # Execute ingest operator to get initial table
        ingest_operator = op_flow[0]

        # Build id → name lookup once so predecessor names are human-readable in lineage events.
        self._node_id_to_name: dict[str, str] = {
            node[OperatorConstants.Columns.ID]: node[OperatorConstants.Columns.NAME]
            for node in op_flow
            if OperatorConstants.Columns.ID in node and OperatorConstants.Columns.NAME in node
        }

        # Derive the ingest source name and namespace early — it is available from config alone,
        # before execution, and is needed for the ingest node's input dataset label.
        ingest_ns, ingest_name = self._derive_ingest_dataset_info(ingest_operator=ingest_operator)
        self.ingest_dataset_namespace = ingest_ns
        self.ingest_dataset_name = ingest_name

        # Emit node START for ingest before execution — ingest bypasses _inner_task
        # so on_node_start must be fired manually here.  The input dataset is the
        # ingest source itself (e.g. file / ./tests/fixtures/customer_support_docs).
        from docpipe.core.orchestration.models.execution_event_context import NodeStartContext as _NodeStartContext
        from docpipe.core.orchestration.models.execution_event_context import NodeTableSummary as _NodeTableSummary

        ingest_start_time = get_current_timestamp()
        self._notify_observer(
            "on_node_start",
            context=_NodeStartContext(
                flow_id=self.flow_id or "",
                flow_name=getattr(self, "flow_name", self.flow_id or ""),
                job_run_id=self.job_run_id or "",
                node_id=ingest_operator[OperatorConstants.Columns.ID],
                node_name=ingest_operator[OperatorConstants.Columns.NAME],
                operator_type=ingest_operator.get(OperatorConstants.Misc.OPERATOR, ""),
                # Use ingest source path as the input dataset so Marquez shows
                # where data originates (e.g. file / ./tests/fixtures/...).
                # No table exists yet so we pass a zero-row placeholder summary.
                input_summary=_NodeTableSummary(schema_fields=[], row_count=0),
                ingest_source_dataset_namespace=self.ingest_dataset_namespace,
                ingest_source_dataset_name=self.ingest_dataset_name,
                parent_run_id=self.job_run_id or "",
                start_time=ingest_start_time,
            ),
        )

        initial_result = self._create_empty_result()
        try:
            ingest_results = self._execute_step(
                op_def=ingest_operator, global_config=global_config, prev_results=initial_result, deleted_docs_count=0
            )
        except Exception as e:
            self._handle_node_failure(e=e, op_def=ingest_operator, global_config=global_config, start=ingest_start_time)
            raise

        # Populate global_config with ingest_source params for lazy binary loading
        self._populate_ingest_source_config(ingest_operator=ingest_operator, global_config=global_config)

        deleted_docs_count = ingest_results.internal_metadata.get(Metrics.Internal.DELETED_FROM_LAST_RUN, 0)
        self.message = self._get_ingest_summary_message(
            output_table=ingest_results.tables[0], deleted_docs_count=deleted_docs_count, operator=ingest_operator
        )

        incremental_service = get_incremental_update_service()
        doc_ids = ingest_results.internal_metadata.get(Metrics.Internal.ALL_DOC_IDS, [])
        incremental_service.process_ingested_docs(config=global_config, job_id=self.job_id, doc_ids=doc_ids)

        # Get the ingested table
        ingested_table = ingest_results.tables[0]

        # Notify observer that ingest is complete and active processing begins
        from docpipe.core.orchestration.models.execution_event_context import FlowRunningContext

        self._notify_observer(
            "on_flow_running",
            context=FlowRunningContext(
                flow_id=self.flow_id or "",
                flow_name=getattr(self, "flow_name", self.flow_id or ""),
                job_run_id=self.job_run_id or "",
                ingested_table=ingested_table,
                ingest_node_id=op_flow[0].get(OperatorConstants.Columns.ID) if op_flow else None,
                ingest_source_namespace=self.ingest_dataset_namespace,
                ingest_source_name=self.ingest_dataset_name,
            ),
        )

        # Check if table is empty
        if ingested_table.num_rows == 0:
            self.logger.info(
                ">>> No documents ingested — marking downstream nodes as skipped and exiting early",
                extra=self.common_log_arguments,
            )
            downstream_nodes = op_flow[1:] if len(op_flow) > 1 else []
            for downstream_node in downstream_nodes:
                try:
                    self.flow_execution_event_handler.after_node_skipped(
                        node_id=downstream_node.get(OperatorConstants.Columns.ID),
                        node_name=downstream_node.get(OperatorConstants.Columns.NAME),
                        operator_type=downstream_node.get(OperatorConstants.Misc.OPERATOR),
                        global_config=global_config,
                        start_time=get_current_timestamp(),
                        end_time=get_current_timestamp(),
                        column_names=[],
                        reason="Skipped - no documents ingested in previous step",
                    )
                except Exception as e:
                    self.logger.warning(
                        "Failed to record skipped status for node %s: %s",
                        downstream_node.get(OperatorConstants.Columns.NAME, "unknown"),
                        e,
                        extra=self.common_log_arguments,
                    )
            clean_up_prefect_home()
            self._finalize_dag_flow(op_flow=op_flow, global_config=global_config)
            return

        # Prepare batches using batch manager
        self.logger.debug(
            "Before prepare_batches: ingest_source in global_config=%s",
            OperatorConstants.Config.INGEST_SOURCE in global_config,
            extra=self.common_log_arguments,
        )
        batches, global_config = self.batch_manager.prepare_batches(
            ingested_table=ingested_table, global_config=global_config, common_log_arguments=self.common_log_arguments
        )
        self.logger.debug(
            "After prepare_batches: ingest_source in global_config=%s",
            OperatorConstants.Config.INGEST_SOURCE in global_config,
            extra=self.common_log_arguments,
        )

        # Store ingest node ID for batch processing (needed to handle references to excluded ingest operator)
        ingest_node_id = op_flow[0].get(OperatorConstants.Columns.ID) if op_flow else None
        global_config[DocpipeConstants.INGEST_NODE_ID] = ingest_node_id

        # Initialize pending batch node stats after batches are materialized
        self.flow_execution_event_handler.after_batches_prepared(
            batches=batches, op_flow=op_flow, global_config=global_config
        )

        # Build and execute batch flow (works for both single and multiple batches)
        # Batch failures are handled in _wait_for_sub_flows() in prefect_engine.py
        batch_execution_failed = False
        try:
            if self.flow_engine:
                self.flow_engine.execute_batch_flow(op_flow=op_flow, batches=batches, global_config=global_config)
        except Exception:
            # Mark that batch execution failed so we can clean up pending batches
            batch_execution_failed = True
            raise
        finally:
            # Mark any remaining PENDING/QUEUED batch node stats as SKIPPED when batch execution fails
            # This ensures proper status aggregation in fail-fast mode
            # Check both job_status and batch_execution_failed because in fail-fast mode,
            # the exception may be raised before job_status is updated to FAILING
            is_fail_fast = not global_config.get(
                DocpipeConstants.CONTINUE_ON_BATCH_FAILURE, DocpipeConstants.CONTINUE_ON_BATCH_FAILURE_DEFAULT
            )
            if (
                (batch_execution_failed or self.job_status == ExecutionStatus.FAILING)
                and global_config.get(DocpipeConstants.ENABLE_MICRO_BATCHING, False)
                and is_fail_fast
            ):
                self._mark_pending_batches_as_skipped()

            # Always finalize flow execution to ensure proper status reporting and cleanup
            # This ensures operator summary is printed even when batches fail in fail-fast mode
            clean_up_prefect_home()
            self._finalize_dag_flow(op_flow=op_flow, global_config=global_config)

    def _create_empty_result(self):
        """Create an empty ExecuteStepResults for use as the initial ingest input.

        Returns:
            ExecuteStepResults wrapping an empty in-memory table."""
        data_access_factory = DataAccessFactory()
        config = {"data_config": {"da_class": "data_processing.data_access.DataAccessMemory"}}
        data_access_factory.apply_input_params(config)
        data_access = data_access_factory.create_data_access()
        data_access.save_table(path="", table=pa.Table.from_arrays([], names=[]))
        return ExecuteStepResults([data_access], [pa.Table.from_arrays(arrays=[], names=[])], None)
