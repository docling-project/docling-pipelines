# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

from pathlib import Path
from typing import Any

from docpipe.core.constants import TERMINAL_JOB_STATUSES, TERMINAL_NODE_STATES, DocpipeConstants, ExecutionStatus
from docpipe.core.job_management.domain.ports import JobRunManager, JobStatsService
from docpipe.core.models.session_info import get_session_info
from docpipe.core.operators.operator_utils import OperatorUtils
from docpipe.core.orchestration.abstract_flow_execution_event_handler import AbstractFlowExecutionEventHandler
from docpipe.core.orchestration.batch_manager import BatchInfo
from docpipe.core.orchestration.executor_pool import thread_pool_executor
from docpipe.utils.infrastructure.exception_sanitizer import sanitize_exception
from docpipe.utils.infrastructure.filesystem import get_data_path
from docpipe.utils.infrastructure.flow_execution_reporter import FlowExecutionReporter
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.infrastructure.performance import log_elapsed_time

logger = get_logger()


class FlowExecutionEventHandler(AbstractFlowExecutionEventHandler):
    """
    Event handler for open source flow execution with constructor-based dependency injection.

    This class handles events triggered during flow execution, using the injected
    job stats service for tracking job and node statistics.
    """

    def __init__(
        self,
        job_stats_service: JobStatsService | None = None,
        job_run_manager: JobRunManager | None = None,
        execution_reporter: FlowExecutionReporter | None = None,
    ):
        """
        Initialize event handler with job services.

        Args:
            job_stats_service: Optional job statistics service for tracking
            job_run_manager: Optional framework job run manager for external status updates
            execution_reporter: Optional output formatter for user-friendly console output
        """
        self.job_stats_service = job_stats_service
        self.job_run_manager = job_run_manager
        self.execution_reporter = execution_reporter
        # These will be set during initialize()
        self.flow_id: str | None = None
        self.job_id: str | None = None
        self.job_run_id: str | None = None
        self.job_log_path: str | None = None
        self.common_log_arguments: dict | None = None

    def initialize(self, *, job_id, job_run_id, common_log_arguments):
        """
        Initialize event handler for a specific job run.

        Args:
            job_id: Job identifier
            job_run_id: Job run identifier
            common_log_arguments: Common logging arguments
        """
        self.flow_id = get_session_info().flow_id
        self.job_id = job_id
        self.job_run_id = job_run_id
        self.job_log_path = self._create_log_folders(job_id=self.job_id, type_="job")
        self.common_log_arguments = common_log_arguments

    def before_flow_execution_start(self, *, orchestrator, flow_def: dict | None = None):
        # Print flow header if output formatter is available
        """Before flow execution start."""
        if self.execution_reporter and flow_def:
            flow_name = flow_def.get(DocpipeConstants.NAME, self.flow_id or "Unknown Flow")
            operator_count = len(flow_def.get(DocpipeConstants.DAG, []))
            self.execution_reporter.print_flow_header(flow_name=flow_name, operator_count=operator_count)

        if self.job_stats_service:
            # Check if job is being canceled
            if self.job_stats_service.cancel_job_run_if_cancelling(
                job_run_id=self.job_run_id, job_log_path=self.job_log_path
            ):
                return

            # Start tracking job
            self.job_stats_service.start_tracking_job(
                job_id=self.job_id,
                job_run_id=self.job_run_id,
                flow_id=self.flow_id or "unknown",
                flow_name=flow_def.get(DocpipeConstants.NAME) if flow_def else None,
            )
            self._update_framework_status(status=ExecutionStatus.RUNNING.value)

    def _log_node_stats_debug(self, job_stats):
        """Log node stats for debugging."""
        logger.debug(
            "Node stats count: %s",
            len(job_stats.node_stats) if job_stats.node_stats else 0,
            extra=self.common_log_arguments,
        )
        if job_stats.node_stats:
            for node_id, node_stat in job_stats.node_stats.items():
                node_status_val = (
                    node_stat.node_status
                    if hasattr(node_stat, "node_status")
                    else node_stat.get("node_status", "Unknown")
                )
                logger.debug("Node %s: status=%s", node_id, node_status_val, extra=self.common_log_arguments)
        else:
            logger.warning("No node stats found when determining final job status", extra=self.common_log_arguments)

    def _determine_job_status_from_stats(self, op_flow, global_config=None) -> ExecutionStatus:
        """Determine final job status from job stats."""
        if not self.job_stats_service:
            return ExecutionStatus.FAILED

        job_stats = self.job_stats_service.get_job(job_run_id=self.job_run_id, include_node_stats=True)
        if job_stats and job_stats.node_stats:
            self.job_stats_service.determine_and_update_final_documents_count(job_stats=job_stats, dag_nodes=op_flow)
            self._log_node_stats_debug(job_stats)

            # Check for partial batch failure in continue_on_batch_failure mode
            # Delegate to JobStatsService for batch failure detection logic
            # Use empty dict if global_config is None
            is_partial_batch_failure = self.job_stats_service.detect_partial_batch_failure(
                job_stats=job_stats, global_config=global_config or {}
            )

            if is_partial_batch_failure:
                # Partial batch failure: some batches succeeded, some failed
                # Override status to COMPLETED_WITH_ERRORS regardless of node stats
                job_status = ExecutionStatus.COMPLETED_WITH_ERRORS
                logger.info(
                    "Partial batch failure detected: setting job status to COMPLETED_WITH_ERRORS",
                    extra=self.common_log_arguments,
                )
                return job_status

            # Normal status determination based on node stats
            # Ensure node_stats is not None before passing to determine_final_job_status
            node_stats_for_status = job_stats.node_stats if job_stats.node_stats else {}
            logger.debug(
                "About to determine status. node_stats_for_status type: %s, len: %s",
                type(node_stats_for_status),
                len(node_stats_for_status) if node_stats_for_status else 0,
                extra=self.common_log_arguments,
            )
            return OperatorUtils.determine_final_job_status(node_stats_list=node_stats_for_status)
        logger.warning("Job stats not found when determining final status", extra=self.common_log_arguments)
        return ExecutionStatus.FAILED

    def _determine_final_status(
        self, op_flow, present_job_status: ExecutionStatus, global_config=None
    ) -> ExecutionStatus:
        """Determine final job status based on present status."""
        if present_job_status == ExecutionStatus.CANCELING:
            return ExecutionStatus.CANCELED
        if present_job_status == ExecutionStatus.FAILING:
            return ExecutionStatus.FAILED
        return self._determine_job_status_from_stats(op_flow, global_config)

    def after_flow_execution_complete(self, op_flow, present_job_status: str, message, global_config=None):
        """Finalize internal job stats and push final framework status with complete statistics."""
        if not self.job_stats_service or not self.job_run_id:
            logger.warning("Job stats service or job_run_id not available", extra=self.common_log_arguments)
            return

        job_status = self._determine_final_status(op_flow, present_job_status, global_config)

        self.job_stats_service.end_job(
            job_run_id=self.job_run_id,
            status=job_status.value,
            job_run_stats={"message": message} if message else None,
        )

        job_stats = self.job_stats_service.get_job(
            job_run_id=self.job_run_id, include_node_stats=True, include_batch_stats=True
        )
        if job_stats and self.job_log_path:
            self.job_stats_service.write_job_logs(job_stats=job_stats, job_log_path=self.job_log_path)

        self._update_framework_status(
            status=job_status.value,
            job_run_stats=self._get_complete_job_stats(message=message),
        )

        logger.info("Job status is %s.", job_status.value, extra=self.common_log_arguments)

        # Generate job report in background for all terminal statuses
        if job_stats and job_status in TERMINAL_JOB_STATUSES:
            self._start_background_report_generation(job_stats=job_stats, op_flow=op_flow)

        # Print flow summary if output formatter is available
        if self.execution_reporter and job_stats:
            self.execution_reporter.print_flow_summary(job_stats=job_stats, dag_nodes=op_flow)

    def before_step_execution_start(self, *, node_id, node_name, global_config, job_status, prev_results):
        """Before step execution start."""
        log_extra = {**(self.common_log_arguments or {}), "node_id": node_id, "node_name": node_name}

        # Print operator start if output formatter is available and step is not being skipped
        if (
            self.execution_reporter
            and prev_results is not None
            and job_status not in (ExecutionStatus.CANCELING, ExecutionStatus.FAILING)
        ):
            # Get operator type from global_config if available
            operator_type = global_config.get("operator_type", "unknown") if global_config else "unknown"
            self.execution_reporter.print_operator_start(step_name=node_name, operator_type=operator_type)

        if prev_results is None:
            logger.info("Error detected in previous step - node %s skipped.", node_name, extra=log_extra)

        if job_status == ExecutionStatus.CANCELING:
            logger.info("Cancelling the branch execution at node name: %s", node_name, extra=log_extra)
        elif job_status == ExecutionStatus.FAILING:
            logger.info("Aborting the branch execution at node name: %s", node_name, extra=log_extra)

    def after_step_execution_complete(
        self,
        *,
        node_id,
        node_name,
        operator_category,
        operator,
        global_config,
        is_last_step,
        metadata,
        start_time,
        tables=None,
    ):
        """
        Update internal step statistics and push periodic RUNNING updates to the framework.
        """
        if self.job_stats_service and self.job_run_id:
            self.job_stats_service.update_doc_counts(
                job_run_id=self.job_run_id, metadata=metadata, operator_category=operator_category.value
            )

        self._update_framework_status(
            status=ExecutionStatus.RUNNING.value,
            job_run_stats=self._get_complete_job_stats(),
        )

        log_elapsed_time(start_time=start_time, operator=operator)

        # Print operator summary if output formatter is available
        if self.execution_reporter and self.job_stats_service and self.job_run_id:
            # Get the complete job stats to access node stats
            job_stats = self.job_stats_service.get_job(
                job_run_id=self.job_run_id, include_node_stats=True, include_batch_stats=True
            )
            if job_stats and job_stats.node_stats and node_id in job_stats.node_stats:
                node_stats = job_stats.node_stats[node_id]

                # Check if we should print the summary (handles both batch and non-batch modes)
                should_print = self._should_print_operator_summary(
                    node_id=node_id,
                    node_stats=node_stats,
                    global_config=global_config,
                    job_stats=job_stats,
                )

                if should_print:
                    self.execution_reporter.print_operator_summary(
                        step_name=node_name, node_stats=node_stats, tables=tables
                    )

        if is_last_step:
            log_extra = {**(self.common_log_arguments or {}), "node_id": node_id, "node_name": node_name}
            logger.info(" Branch execution completed at node name: %s", node_name, extra=log_extra)

    def after_node_skipped(
        self,
        *,
        node_id,
        node_name,
        operator_type,
        global_config,
        start_time,
        end_time,
        column_names,
        reason: str | None = None,
    ):
        """
        Record node as SKIPPED.

        Handles both empty-data skips and upstream-failure skips.

        Args:
            node_id: Node identifier
            node_name: Human-readable node name
            operator_type: Operator type
            global_config: Global configuration containing batch context
            start_time: Start timestamp
            end_time: End timestamp
            column_names: Column names from node output
            reason: Reason for skipping (defaults to "Skipped - no input data to process")
        """

        log_extra = {**(self.common_log_arguments or {}), "node_id": node_id, "node_name": node_name}
        logger.info(
            "Skipped execution for Step Name: %s, operator: %s because no input data available for processing.",
            node_name,
            operator_type,
            extra=log_extra,
        )

        if self.job_stats_service and self.job_run_id:
            # Extract batch context from global_config if micro-batching is enabled
            batch_id = None
            batch_num = None
            if global_config.get(DocpipeConstants.ENABLE_MICRO_BATCHING, False):
                batch_id = global_config.get(DocpipeConstants.BATCH_ID)
                batch_num = global_config.get(DocpipeConstants.BATCH_NUM)

            # Use provided reason or default
            skip_reason = reason if reason is not None else "Skipped - no input data to process"

            # Use new terminal API with batch context
            self.job_stats_service.skip_node_execution(
                job_run_id=self.job_run_id,
                node_id=node_id,
                node_name=node_name,
                reason=skip_reason,
                col_names=column_names,
                batch_id=batch_id,
                batch_num=batch_num,
            )

    def after_node_failure(self, *, node_id, node_name, global_config, e):
        """After node failure."""
        if self.job_stats_service and self.job_run_id:
            # Extract batch context from global_config if micro-batching is enabled
            batch_id = None
            batch_num = None
            if global_config.get(DocpipeConstants.ENABLE_MICRO_BATCHING, False):
                batch_id = global_config.get(DocpipeConstants.BATCH_ID)
                batch_num = global_config.get(DocpipeConstants.BATCH_NUM)

            # Use new terminal API with batch context
            self.job_stats_service.fail_node_execution(
                job_run_id=self.job_run_id,
                node_id=node_id,
                node_name=node_name,
                exception=e,
                batch_id=batch_id,
                batch_num=batch_num,
            )

            job_stats = self.job_stats_service.get_job(
                job_run_id=self.job_run_id, include_node_stats=True, include_batch_stats=True
            )
            if job_stats and self.job_log_path:
                self.job_stats_service.write_job_logs(job_stats=job_stats, job_log_path=self.job_log_path)

        self._update_framework_status(
            status=ExecutionStatus.FAILED.value,
            job_run_stats=self._get_complete_job_stats(message=sanitize_exception(exc=e, config_key=node_name)),
        )

        logger.error(
            "Node %s failed: %s",
            node_name,
            sanitize_exception(exc=e, config_key=node_name),
            extra=self.common_log_arguments,
        )

        log_extra = {**(self.common_log_arguments or {}), "node_id": node_id, "node_name": node_name}
        logger.error(
            ">>> Node %s failed and caused aborting the branch execution: %s transaction_ID: %s",
            node_name,
            sanitize_exception(exc=e, config_key=node_name),
            get_session_info().transaction_id,
            extra=log_extra,
        )

    def after_batches_prepared(
        self, *, batches: list[BatchInfo], op_flow: list[dict[str, Any]], global_config: dict[str, Any]
    ) -> None:
        """
        Initialize pending batch node stats after batches are materialized.

        Creates PENDING stats for all batch/node combinations for downstream
        batch-participating nodes (excludes ingest operator).

        Args:
            batches: List of BatchInfo objects with batch_id, batch_num, and table
            op_flow: Operator flow definition (DAG)
            global_config: Global configuration dictionary
        """
        # Only create pending stats if micro-batching is enabled
        if not global_config.get(DocpipeConstants.ENABLE_MICRO_BATCHING, False):
            return

        if not self.job_stats_service or not self.job_run_id:
            logger.warning("Job stats service or job_run_id not available for pending batch stats creation")
            return

        # Extract batch IDs and nums from retained batches
        batch_ids = [batch_info.batch_id for batch_info in batches]
        batch_nums = [batch_info.batch_num for batch_info in batches]

        # Get downstream node IDs and names (exclude ingest operator at index 0)
        from docpipe.core.constants.operator_constants import OperatorConstants

        downstream_node_ids: list[str] = [
            str(op_def.get(OperatorConstants.Columns.ID))
            for op_def in op_flow[1:]
            if op_def.get(OperatorConstants.Columns.ID) is not None
        ]

        downstream_node_names: list[str] = [
            str(op_def.get(OperatorConstants.Columns.NAME, ""))
            for op_def in op_flow[1:]
            if op_def.get(OperatorConstants.Columns.ID) is not None
        ]

        if batch_ids and downstream_node_ids:
            self.job_stats_service.create_pending_batch_node_stats(
                job_run_id=self.job_run_id,
                batch_ids=batch_ids,
                batch_nums=batch_nums,
                downstream_node_ids=downstream_node_ids,
                downstream_node_names=downstream_node_names,
            )
            logger.info(
                "Initialized pending stats for %s batches x %s nodes",
                len(batch_ids),
                len(downstream_node_ids),
                extra=self.common_log_arguments,
            )

    def _get_complete_job_stats(self, *, message: str | None = None) -> dict[str, Any] | None:
        """Return complete job stats including node_stats for framework updates."""
        if not self.job_stats_service or not self.job_run_id:
            return {"message": message} if message else None

        job_stats = self.job_stats_service.get_job(job_run_id=self.job_run_id, include_node_stats=True)
        if not job_stats:
            return {"message": message} if message else None

        job_run_stats = job_stats.model_dump()
        if message:
            job_run_stats["message"] = message
        return job_run_stats

    def _update_framework_status(self, *, status: str, job_run_stats: dict[str, Any] | None = None) -> None:
        """Update external framework status without allowing framework failures to stop the flow."""
        if not self.job_run_manager or not self.job_run_id:
            return

        try:
            self.job_run_manager.update_job_run_status(
                job_run_id=self.job_run_id,
                status=status,
                job_run_stats=job_run_stats,
            )
        except Exception as exc:
            logger.warning(
                "Failed to update external framework status",
                extra={
                    **(self.common_log_arguments or {}),
                    "job_run_id": self.job_run_id,
                    "status": status,
                    "error": str(exc),
                },
            )

    def _set_report_generating_status(self, started_at: int):
        """Set report status to GENERATING with start timestamp."""
        if not self.job_stats_service or not self.job_run_id:
            return

        current_job = self.job_stats_service.get_job(job_run_id=self.job_run_id, include_node_stats=False)
        if not current_job:
            logger.warning("Cannot update report status: job not found", extra=self.common_log_arguments)
            return

        self.job_stats_service.end_job(
            job_run_id=self.job_run_id,
            status=current_job.status.value if hasattr(current_job.status, "value") else current_job.status,
            job_run_stats={"report_status": "GENERATING", "report_generation_started_at": started_at},
        )

    def _mark_report_not_available(self):
        """Mark report status as NOT_AVAILABLE (e.g. parquet files absent for in-memory flows)."""
        if not self.job_stats_service or not self.job_run_id:
            return

        current_job = self.job_stats_service.get_job(job_run_id=self.job_run_id, include_node_stats=False)
        if current_job:
            self.job_stats_service.end_job(
                job_run_id=self.job_run_id,
                status=current_job.status.value if hasattr(current_job.status, "value") else current_job.status,
                job_run_stats={"report_status": "NOT_AVAILABLE"},
            )

    def _mark_report_failed(self, elapsed_time: float, exception: Exception):
        """Mark report generation as failed."""
        from docpipe.utils.core.datetime import get_current_timestamp

        if not self.job_stats_service or not self.job_run_id:
            return

        completed_at = get_current_timestamp()
        current_job = self.job_stats_service.get_job(job_run_id=self.job_run_id, include_node_stats=False)
        if current_job:
            self.job_stats_service.end_job(
                job_run_id=self.job_run_id,
                status=current_job.status.value if hasattr(current_job.status, "value") else current_job.status,
                job_run_stats={"report_status": "FAILED", "report_generation_completed_at": completed_at},
            )

        logger.exception(
            "Report generation failed after %.2fs: %s",
            elapsed_time,
            exception,
            extra=self.common_log_arguments,
        )

    @staticmethod
    def _extract_node_metadata_list_from_job_stats(job_stats) -> list:
        """
        Extract node_metadata_list in-memory from job_stats.node_stats before the background
        thread starts.

        node_stats already has node_metadata populated on each NodeStats object. capturing it here while it still exists
        in memory, before the thread starts, so report generation has detailed failure/skip
        reasons without needing to re-fetch from storage.
        """
        node_metadata_list = []
        for node_stat in (job_stats.node_stats or {}).values():
            node_metadata = (
                node_stat.get("node_metadata")
                if isinstance(node_stat, dict)
                else getattr(node_stat, "node_metadata", None)
            )
            if node_metadata:
                node_metadata_list.append(node_metadata)
        return node_metadata_list

    def _generate_report_async(
        self,
        session_info,
        dag_nodes_ref: list,
        batch_node_stats_ref: dict,
        node_metadata_list_ref: list,
    ):
        """
        Generate report in background thread.

        SessionInfo is passed explicitly and restored at the start of the thread
        because ContextVar values are not inherited by new threads.

        Args:
            session_info: SessionInfo captured from the spawning thread
            dag_nodes_ref: Reference to DAG nodes from flow definition
            batch_node_stats_ref: Reference to batch node statistics (or None for non-batched flows)
            node_metadata_list_ref: Pre-extracted node metadata list for failure/skip reasons
        """
        import time

        from docpipe.core.job_management.application.services.report_generator import JobReportGenerator
        from docpipe.core.job_management.application.services.report_utils import check_parquet_availability
        from docpipe.core.models.session_info import set_session_info
        from docpipe.utils.core.datetime import get_current_timestamp
        from docpipe.utils.infrastructure.performance import reclaim_memory

        # Restore SessionInfo in this thread — ContextVar is not inherited from the spawning thread
        set_session_info(session_info)

        start_time = time.time()
        started_at = get_current_timestamp()

        # Skip report generation when parquet files are not available
        parquet_available, reason = check_parquet_availability()
        if not parquet_available:
            logger.info(
                "Skipping background report generation for job run %s: %s",
                session_info.job_run_id,
                reason,
                extra=self.common_log_arguments,
            )
            self._mark_report_not_available()
            # This thread is the last work the flow does.  The reclaim at flow end
            # ran while this thread was still allocating, so ask again now.
            reclaim_memory(context="report-end")
            return

        try:
            # Set status to GENERATING
            self._set_report_generating_status(started_at)

            # Check if job_stats_service is available
            if not self.job_stats_service:
                logger.warning("Job stats service not available for report generation", extra=self.common_log_arguments)
                elapsed_time = time.time() - start_time
                self._mark_report_failed(elapsed_time, Exception("Job stats service not available"))
                return

            # Fetch fresh job stats
            job_stats_fresh = self.job_stats_service.get_job(
                job_run_id=session_info.job_run_id, include_node_stats=True
            )

            if not job_stats_fresh:
                logger.warning("Could not fetch job stats for report generation", extra=self.common_log_arguments)
                elapsed_time = time.time() - start_time
                self._mark_report_failed(elapsed_time, Exception("Job stats not found"))
                return

            # Restore pre-fetched batch_node_stats
            job_stats_fresh.batch_node_stats = batch_node_stats_ref
            if batch_node_stats_ref:
                logger.info(
                    "Using pre-fetched batch_node_stats with %s node(s)",
                    len(batch_node_stats_ref),
                    extra=self.common_log_arguments,
                )

            if node_metadata_list_ref:
                logger.info(
                    "Using pre-extracted node_metadata with %d entries - detailed failure/skip reasons will be included in report",
                    len(node_metadata_list_ref),
                    extra=self.common_log_arguments,
                )
            else:
                logger.warning(
                    "node_metadata not available - report will use generic failure/skip messages",
                    extra=self.common_log_arguments,
                )

            # Generate report
            generator = JobReportGenerator(
                job_stats=job_stats_fresh, dag_nodes=dag_nodes_ref, node_metadata_list=node_metadata_list_ref
            )
            generator.save_report_to_file()

            # Update status to COMPLETED
            completed_at = get_current_timestamp()
            current_job = self.job_stats_service.get_job(job_run_id=session_info.job_run_id, include_node_stats=False)
            if current_job:
                self.job_stats_service.end_job(
                    job_run_id=session_info.job_run_id,
                    status=current_job.status.value if hasattr(current_job.status, "value") else current_job.status,
                    job_run_stats={"report_status": "COMPLETED", "report_generation_completed_at": completed_at},
                )

            elapsed_time = time.time() - start_time
            logger.info(
                "Job report generated successfully in background for job run %s (took %.2fs)",
                session_info.job_run_id,
                elapsed_time,
                extra=self.common_log_arguments,
            )

        except Exception as e:
            elapsed_time = time.time() - start_time
            self._mark_report_failed(elapsed_time, e)
        finally:
            # This thread is the last work the flow does.  The reclaim at flow end
            # ran while this thread was still allocating, so ask again now.
            reclaim_memory(context="report-end")

    def _start_background_report_generation(self, *, job_stats, op_flow) -> None:
        """
        Start background report generation using the shared thread pool executor.

        Submits report generation to the module-level ThreadPoolExecutor rather than
        spawning a raw daemon thread. This ensures the future is tracked by the executor
        and is not killed by a pod shutdown before it completes (the executor's work queue
        is drained before the process exits).

        Args:
            job_stats: JobStats object with complete statistics
            op_flow: Flow definition DAG nodes
        """
        if not self.job_stats_service or not self.job_run_id:
            logger.warning(
                "Cannot generate report: job_stats_service or job_run_id not available", extra=self.common_log_arguments
            )
            return

        try:
            from docpipe.core.models.session_info import get_session_info

            # Capture all data needed before submitting to the executor.
            # SessionInfo is captured explicitly because ContextVar is not inherited by threads.
            # node_metadata_list must be captured here while it still exists in node_stats
            # (it may not be available after the executor picks up the task if node_stats is cleared).
            session_info_ref = get_session_info()
            dag_nodes_ref = op_flow
            batch_node_stats_ref = job_stats.batch_node_stats
            node_metadata_list_ref = self._extract_node_metadata_list_from_job_stats(job_stats)

            logger.info(
                "Pre-extracted %d node_metadata entries for background report",
                len(node_metadata_list_ref),
                extra=self.common_log_arguments,
            )

            thread_pool_executor.submit(
                self._generate_report_async,
                session_info_ref,
                dag_nodes_ref,
                batch_node_stats_ref,
                node_metadata_list_ref,
            )
            logger.info("Job report generation submitted to thread pool executor", extra=self.common_log_arguments)
        except Exception as e:
            logger.warning(
                "Failed to submit background report generation: %s",
                str(e),
                extra=self.common_log_arguments,
                exc_info=True,
            )

    @staticmethod
    def _should_print_operator_summary(
        *,
        node_id: str,
        node_stats,
        global_config: dict[str, Any] | None,
        job_stats,
    ) -> bool:
        """
        Determine if operator summary should be printed.

        For micro-batching mode: only print when ALL batches complete.
        For non-batch mode: always print.

        Args:
            node_id: Node identifier
            node_stats: Aggregated node statistics
            global_config: Global configuration containing batch_id if in batch mode
            job_stats: Complete job statistics including batch_node_stats

        Returns:
            True if summary should be printed, False otherwise
        """
        # Check if we're in a batch context
        batch_id = global_config.get(DocpipeConstants.BATCH_ID) if global_config else None

        if batch_id is None:
            # Non-batch mode: always print
            return True

        # Micro-batching mode: only print when ALL batches complete
        # Get batch records for this node to check completion status
        batch_records = []
        if job_stats.batch_node_stats and node_id in job_stats.batch_node_stats:
            batch_records = list(job_stats.batch_node_stats[node_id].values())

        if not batch_records:
            # No batch records found, don't print (safe default)
            return False

        # Import aggregator functions to calculate batch completion
        from docpipe.core.job_management.application.aggregation.batch_aggregator import (
            calculate_finished_batches,
            count_batches_by_status,
        )

        # Calculate batch completion status
        status_counts = count_batches_by_status(batch_records=batch_records)
        finished_batches = calculate_finished_batches(status_counts=status_counts)
        total_batches = len(batch_records)
        has_pending = (
            status_counts.get(ExecutionStatus.PENDING.value, 0) + status_counts.get(ExecutionStatus.QUEUED.value, 0)
        ) > 0

        # Print only when all batches done AND node in terminal state
        # finished_batches > 0 ensures aggregation has run at least once
        terminal_states_values = frozenset(state.value for state in TERMINAL_NODE_STATES)
        return (
            finished_batches > 0
            and finished_batches == total_batches
            and not has_pending
            and node_stats.node_status in terminal_states_values
        )

    def _create_log_folders(self, *, job_id, type_):
        """
        Created folders for logs: <job_id>/<job_run_id>/docpipe_logs. The log for that job will be stored there
        """
        log_location_path = get_data_path()
        log_app_location = DocpipeConstants.DOCPIPE_LOGS

        log_job_location = Path(log_location_path) / job_id / str(self.job_run_id) / log_app_location
        log_job_location.mkdir(parents=True, exist_ok=True)
        if type_ == "flow":
            log_job_run_file_name = "flow_execute.log"
        elif type_ == "job":
            log_job_run_file_name = "job_stats.json"

        return str(log_job_location / log_job_run_file_name)
