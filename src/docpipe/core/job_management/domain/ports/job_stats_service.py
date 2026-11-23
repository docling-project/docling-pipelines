"""
JobStatsService Port - Interface for job statistics service operations

This is the PRIMARY PORT used by the orchestrator for all job stats operations.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from docpipe.core.constants import ExecutionStatus

if TYPE_CHECKING:
    from docpipe.core.job_management.domain.models import JobStats, NodeStats


class JobStatsService(ABC):
    """
    Port interface for job statistics service operations.

    This abstraction allows the orchestrator to depend on an interface
    rather than concrete implementations.

    Implementations:
    - JobTrackerService: Wraps the legacy JobTracker singleton (default)
    - MockJobStatsService: For testing
    - RemoteJobStatsService: For distributed systems

    Key Responsibilities:
    - Create and manage job runs
    - Update job run status and statistics
    - Update node-level statistics
    - Retrieve job and node statistics
    - Support cancellation and deletion operations
    """

    @abstractmethod
    def start_tracking_job(
        self,
        *,
        job_id: str,
        job_run_id: str,
        flow_id: str,
        flow_name: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        initial_status: ExecutionStatus = ExecutionStatus.RUNNING,
    ) -> "JobStats":
        """
        Start tracking a new job run with initial statistics.

        Called by orchestrator when job execution begins.

        Args:
            job_id: Unique job identifier
            job_run_id: Unique job run identifier
            flow_id: Stable flow identifier — asset UUID for API-originated runs,
                job_id slug for CLI/Library runs.
            flow_name: Human-readable name of the flow at run creation time.
                Snapshotted here; historical runs preserve the name even if the
                flow is later renamed. None is acceptable (e.g. CLI/Library runs
                where the flow has no registered name).
            user_id: Optional user identifier
            metadata: Optional metadata dictionary
            initial_status: Initial status for the job stats record.
                Defaults to ExecutionStatus.RUNNING for backward compatibility.
                Pass ExecutionStatus.QUEUED when called from the HTTP thread
                before the background thread has started.

        Returns:
            JobStats with the given initial_status

        Raises:
            JobRunAlreadyExistsException: If job_run_id already exists
        """
        ...

    @abstractmethod
    def get_job_run_stats(self, *, job_run_id: str) -> "JobStats | None":
        """
        Retrieve job-level statistics WITHOUT node_stats aggregation (lightweight).

        Performance-optimized method that returns only job metadata.
        The returned JobStats will have empty node_stats and batch_node_stats.

        Args:
            job_run_id: Job run identifier

        Returns:
            JobStats if found, None otherwise
        """
        ...

    @abstractmethod
    def get_job(
        self, *, job_run_id: str, include_node_stats: bool = True, include_batch_stats: bool = False
    ) -> "JobStats | None":
        """
        Retrieve complete job statistics with optional aggregation.

        This method provides full job details with control over expensive aggregation.

        Args:
            job_run_id: Job run identifier
            include_node_stats: Whether to aggregate and include node statistics
            include_batch_stats: Whether to include batch-level node statistics

        Returns:
            JobStats with requested statistics if found, None otherwise
        """
        ...

    @abstractmethod
    def end_job(self, *, job_run_id: str, status: str, job_run_stats: dict[str, Any] | None = None) -> None:
        """
        End job tracking and update final status.

        Called by orchestrator when job execution completes (success or failure).

        Args:
            job_run_id: Job run identifier
            status: Final status (COMPLETED, FAILED, CANCELED)
            job_run_stats: Optional final statistics

        Raises:
            JobRunNotFoundException: If job_run_id not found
        """
        ...

    @abstractmethod
    def start_node_execution(
        self,
        *,
        job_run_id: str,
        node_id: str,
        node_name: str,
        total_docs: list[str],
        batch_id: str | None = None,
        batch_num: int | None = None,
    ) -> None:
        """
        Initialize node execution with starting statistics.

        Sets node status to RUNNING and records start time and total documents.

        Args:
            job_run_id: Job run identifier
            node_id: Node identifier
            node_name: Human-readable node name
            total_docs: List of document IDs to be processed
            batch_id: Optional batch identifier for micro-batch execution
            batch_num: Optional batch number for micro-batch execution

        Raises:
            JobRunNotFoundException: If job_run_id not found
        """
        ...

    @abstractmethod
    def complete_node_execution(
        self,
        *,
        job_run_id: str,
        node_id: str,
        node_name: str,
        docs_completed: list[str],
        failed_docs: list[str],
        skipped_docs: list[str],
        col_names: list[str],
        node_status: str,
        node_metadata: dict[str, Any] | None = None,
        batch_id: str | None = None,
        batch_num: int | None = None,
    ) -> None:
        """
        Finalize node execution with completion statistics.

        Merges completion facts with the previously stored start state for the
        same node execution and calculates derived fields such as end_time,
        time_taken, and counts.

        Args:
            job_run_id: Job run identifier
            node_id: Node identifier
            node_name: Human-readable node name
            docs_completed: List of successfully completed document IDs
            failed_docs: List of failed document IDs
            skipped_docs: List of skipped document IDs
            col_names: Column names from node output
            node_status: Final node status (COMPLETED, FAILED, etc.)
            node_metadata: Optional operator-specific metadata
            batch_id: Optional batch identifier for micro-batch execution
            batch_num: Optional batch number for micro-batch execution

        Raises:
            JobRunNotFoundException: If job_run_id not found
        """
        ...

    @abstractmethod
    def fail_node_execution(
        self,
        *,
        job_run_id: str,
        node_id: str,
        node_name: str,
        exception: Exception | None = None,
        error: str | None = None,
        batch_id: str | None = None,
        batch_num: int | None = None,
    ) -> None:
        """
        Mark node execution as FAILED with error details.

        Either exception or error must be provided (not both None).
        If exception is provided, extracts meaningful error message from it
        and ignores the error parameter (no stack traces stored).
        Updates batch-scoped node stats when batch_id is provided.

        Args:
            job_run_id: Job run identifier
            node_id: Node identifier
            node_name: Human-readable node name
            exception: Optional exception that caused the failure
            error: Optional error message (ignored if exception provided)
            batch_id: Optional batch identifier for micro-batch execution
            batch_num: Optional batch number for micro-batch execution

        Raises:
            JobRunNotFoundException: If job_run_id not found
        """
        ...

    @abstractmethod
    def cancel_node_execution(
        self,
        *,
        job_run_id: str,
        node_id: str,
        node_name: str,
        batch_id: str | None = None,
        batch_num: int | None = None,
    ) -> None:
        """
        Mark node execution as CANCELED.

        Updates batch-scoped node stats when batch_id is provided.

        Args:
            job_run_id: Job run identifier
            node_id: Node identifier
            node_name: Human-readable node name
            batch_id: Optional batch identifier for micro-batch execution
            batch_num: Optional batch number for micro-batch execution

        Raises:
            JobRunNotFoundException: If job_run_id not found
        """
        ...

    @abstractmethod
    def abort_node_execution(
        self,
        *,
        job_run_id: str,
        node_id: str,
        node_name: str,
        reason: str,
        batch_id: str | None = None,
        batch_num: int | None = None,
    ) -> None:
        """
        Mark node execution as ABORTED.

        Used for batch termination scenarios where execution is stopped
        externally or preempted by another batch failure. Distinct from
        CANCELED which is user-initiated.

        Args:
            job_run_id: Job run identifier
            node_id: Node identifier
            node_name: Human-readable node name
            reason: Reason for abort (e.g., "Aborted due to batch 3 failure")
            batch_id: Optional batch identifier for micro-batch execution
            batch_num: Optional batch number for micro-batch execution

        Raises:
            JobRunNotFoundException: If job_run_id not found
        """
        ...

    @abstractmethod
    def skip_node_execution(
        self,
        *,
        job_run_id: str,
        node_id: str,
        node_name: str,
        reason: str,
        col_names: list[str],
        batch_id: str | None = None,
        batch_num: int | None = None,
    ) -> None:
        """
        Mark node execution as SKIPPED.

        Updates batch-scoped node stats when batch_id is provided.

        Args:
            job_run_id: Job run identifier
            node_id: Node identifier
            node_name: Human-readable node name
            reason: Reason why the node was skipped
            col_names: Column names from node output
            batch_id: Optional batch identifier for micro-batch execution
            batch_num: Optional batch number for micro-batch execution

        Raises:
            JobRunNotFoundException: If job_run_id not found
        """
        ...

    @abstractmethod
    def update_node_stats(
        self, *, job_run_id: str, node_id: str, node_stats: "NodeStats", batch_id: str | None = None
    ) -> None:
        """
        Update node-level statistics.

        Fetches existing node stats, merges incoming values with existing state,
        and persists the merged result.

        Args:
            job_run_id: Job run identifier
            node_id: Node identifier
            node_stats: Node statistics to update (NodeStats or dict)
            batch_id: Optional batch identifier for micro-batch execution

        Raises:
            JobRunNotFoundException: If job_run_id not found
        """
        ...

    @abstractmethod
    def get_node_stats(self, *, job_id: str, job_run_id: str) -> dict[str, Any]:
        """
        Retrieve aggregated node statistics.

        Returns aggregated statistics for all nodes in the job run.

        Args:
            job_id: Job identifier
            job_run_id: Job run identifier

        Returns:
            Dictionary mapping node_id to aggregated NodeStats

        Raises:
            JobRunNotFoundException: If job_run_id not found
        """
        ...

    @abstractmethod
    def update_doc_counts(self, *, job_run_id: str, metadata: dict[str, Any], operator_category: str) -> None:
        """
        Update document counts based on operator execution metadata.

        Called by orchestrator after each operator execution.

        Args:
            job_run_id: Job run identifier
            metadata: Operator execution metadata containing document counts
            operator_category: Category of operator (ingest, extract, etc.)

        Raises:
            JobRunNotFoundException: If job_run_id not found
        """
        ...

    @abstractmethod
    def bulk_store_node_stats(self, *, job_id: str, job_run_id: str, node_stats_list: list[Any]) -> None:
        """
        Bulk store multiple node statistics (micro-batching).

        Handles both insert and update operations.

        Args:
            job_id: Job identifier
            job_run_id: Job run identifier
            node_stats_list: List of NodeStats objects to store/update

        Raises:
            JobRunNotFoundException: If job_run_id not found
            JobStatsStoreWriteException: If bulk operation fails
        """
        ...

    @abstractmethod
    def store_job_stats(self, *, job_stats: "JobStats") -> None:
        """
        Store or update job-level statistics.

        Args:
            job_stats: Job statistics to store (JobStats)

        Raises:
            JobStatsStoreWriteException: If storage operation fails
        """
        ...

    @abstractmethod
    def request_cancel_job(self, *, job_run_id: str) -> None:
        """
        Initiate cancellation process for a running job.

        Sets job status to CANCELING.

        Args:
            job_run_id: Job run identifier

        Returns:
            Updated JobStats with status=CANCELING

        Raises:
            JobRunNotFoundException: If job_run_id not found
        """
        ...

    @abstractmethod
    def cancel_job_run_if_cancelling(self, *, job_run_id: str, job_log_path: str | None = None) -> bool:
        """
        Check if job is in CANCELING state and finalize as CANCELED.

        Args:
            job_run_id: Job run identifier
            job_log_path: Optional path to write job logs

        Returns:
            True if job was canceled, False otherwise
        """
        ...

    @abstractmethod
    def request_delete_job_run(self, *, job_run_id: str) -> str:
        """
        Delete job run data including logs and statistics.

        Args:
            job_run_id: Job run identifier

        Returns:
            Confirmation message

        Raises:
            JobRunNotFoundException: If job_run_id not found
        """
        ...

    @abstractmethod
    def delete_job_runs_by_job_id(self, *, job_id: str) -> int:
        """
        Delete all job runs associated with a given job_id (flow UUID).

        Used for cascade-deletion when a flow is deleted.  Fetches all
        job_run_ids whose job_id matches the given value, then deletes
        each one from the store.  Failures for individual runs are logged
        as warnings and do not abort the operation.

        Args:
            job_id: The flow UUID whose job runs should be deleted.

        Returns:
            Number of job runs successfully deleted.
        """
        ...

    @abstractmethod
    def is_job_run_complete(self, *, job_run_id: str) -> bool:
        """
        Check if job run has reached terminal state.

        Args:
            job_run_id: Job run identifier

        Returns:
            True if job is in terminal state, False otherwise
        """
        ...

    @abstractmethod
    def determine_and_update_final_documents_count(
        self, *, job_stats: "JobStats", dag_nodes: list[dict[str, Any]]
    ) -> None:
        """
        Determine final status of each document and update job statistics.

        Args:
            job_stats: Job statistics object to update (JobStats)
            dag_nodes: List of DAG nodes with input/output edges
        """
        ...

    @abstractmethod
    def write_job_logs(self, *, job_stats: "JobStats", job_log_path: str) -> None:
        """
        Write job statistics to log file.

        Args:
            job_stats: Job statistics to write (JobStats)
            job_log_path: Path to write log file

        Raises:
            JobStatsStoreWriteException: If file write fails
        """
        ...

    @abstractmethod
    def list_job_runs(
        self,
        *,
        job_id: str | None = None,
        job_ids: list[str] | None = None,
        status: ExecutionStatus | str | None = None,
        limit: int = 100,
    ) -> list[Any]:
        """
        List job runs with optional filters.

        Args:
            job_id: Optional filter by a single job_id
            job_ids: Optional filter by a set of job_ids (bulk lookup, uses IN clause in SQL stores)
            status: Optional filter by status
            limit: Maximum number of results

        Returns:
            List of JobStats matching filters (sorted by start_time desc)
        """
        ...

    @abstractmethod
    def count_job_runs(
        self,
        *,
        job_id: str | None = None,
        job_ids: list[str] | None = None,
        status: ExecutionStatus | str | None = None,
    ) -> int:
        """
        Count job runs using the same filters as list_job_runs.

        Args:
            job_id: Optional filter by a single job_id
            job_ids: Optional filter by a set of job_ids
            status: Optional filter by status

        Returns:
            Number of matching job runs, with no result limit
        """
        ...

    @abstractmethod
    def get_job_run_logs(self, *, job_run_id: str) -> list[str]:
        """
        Build best-effort execution logs for a job run.

        Args:
            job_run_id: Job run identifier

        Returns:
            List of synthesized log lines
        """
        ...

    @abstractmethod
    def create_pending_batch_node_stats(
        self,
        *,
        job_run_id: str,
        batch_ids: list[str],
        batch_nums: list[int],
        downstream_node_ids: list[str],
        downstream_node_names: list[str],
    ) -> None:
        """
        Bulk create PENDING batch node stats for all batch/node combinations.

        Args:
            job_run_id: Job run identifier
            batch_ids: List of batch IDs
            batch_nums: List of batch numbers
            downstream_node_ids: List of downstream node IDs
            downstream_node_names: List of downstream node names

        Raises:
            JobRunNotFoundException: If job_run_id not found
            JobStatsStoreWriteException: If bulk operation fails
        """
        ...

    @abstractmethod
    def mark_pending_batches_as_skipped(self, *, job_run_id: str, reason: str) -> None:
        """
        Mark all PENDING/QUEUED batch node stats as SKIPPED.

        Used in fail-fast mode when flow fails before all batches execute.
        This ensures proper status aggregation - without this, pending batches
        cause operators to show as "Running" instead of their actual terminal status.

        Args:
            job_run_id: Job run identifier
            reason: Reason for skipping (e.g., "Skipped - flow failed in fail-fast mode")

        Raises:
            JobRunNotFoundException: If job_run_id not found
        """
        ...

    @abstractmethod
    def get_formatted_job_stats(self, *, job_run_id: str, include_logs: bool = False) -> Any:
        """
        Get job statistics with detailed formatting for API responses.

        Args:
            job_run_id: Job run identifier
            include_logs: Whether to include individual node log strings as dynamic fields

        Returns:
            JobRunStatusResponse DTO ready for API response
        """
        ...

    @abstractmethod
    def get_flow_definition(self, *, job_run_id: str) -> dict[str, Any] | None:
        """
        Retrieve the flow definition snapshot for a specific job run.

        This method abstracts the storage backend (local filesystem, S3, COS, etc.)
        and returns the flow definition that was persisted at job run creation time.

        Args:
            job_run_id: Job run identifier

        Returns:
            Flow definition dictionary if found, None otherwise

        Raises:
            JobRunNotFoundException: If job_run_id not found in stats service
            JobStatsStoreReadException: If flow definition file cannot be read
        """
        ...

    @abstractmethod
    def save_flow_definition(
        self,
        *,
        job_id: str,
        job_run_id: str,
        flow_definition: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> None:
        """
        Save flow definition JSON to filesystem for audit and reproducibility.

        This method stores the flow definition that was used for a specific job run,
        enabling retrieval via get_flow_definition for debugging and audit purposes.

        Args:
            job_id: Job identifier
            job_run_id: Job run identifier
            flow_definition: Flow definition dictionary to save
            params: Optional execution parameters passed to the flow

        Raises:
            DocpipeException: If flow definition cannot be saved
        """
        ...

    @abstractmethod
    def detect_partial_batch_failure(self, *, job_stats: "JobStats", global_config: dict) -> bool:
        """
        Detect if this is a partial batch failure scenario.

        Returns True if:
        - Micro-batching is enabled
        - continue_on_batch_failure is True
        - Some (but not all) batch node stats have FAILED status

        Args:
            job_stats: Job statistics including batch_node_stats
            global_config: Global configuration dictionary (required)

        Returns:
            True if partial batch failure detected, False otherwise
        """
        ...

    @abstractmethod
    def get_failed_doc_ids_for_batch(self, *, job_run_id: str, batch_id: str) -> list[str]:
        """
        Collect failed document IDs scoped to a single batch.

        Queries only the node stats rows for the given batch_id, avoiding
        O(N²) growth where N is the number of completed batches.

        Args:
            job_run_id: Job run identifier
            batch_id: Batch identifier to scope the query

        Returns:
            List of failed document IDs for that batch (may be empty)
        """
        ...
