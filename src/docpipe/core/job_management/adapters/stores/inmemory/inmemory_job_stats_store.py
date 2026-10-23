"""
InMemoryJobStatsStore - Production-grade thread-safe in-memory storage adapter

High-performance in-memory implementation of JobStatsStore port with:
- Fine-grained per-job locking for concurrent micro-batching
- Immutable data access patterns (deep copy on read/write)
- Lock-free reads for different job runs
- Optimized for single-process, multi-threaded Prefect deployments
"""

from collections import defaultdict
from copy import deepcopy
from threading import RLock
from typing import Any

from docpipe.core.constants.constants import ExecutionStatus
from docpipe.core.job_management.domain.models import JobStats, NodeStats
from docpipe.core.job_management.domain.ports import JobStatsStore
from docpipe.exceptions.docpipe_exceptions import (
    JobStatsStoreDeleteException,
    JobStatsStoreWriteException,
)
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class InMemoryJobStatsStore(JobStatsStore):
    """
    Production-grade thread-safe in-memory storage for job statistics.

    Concurrency Model:
    - Fine-grained locking: Separate lock per job_run_id
    - Concurrent job runs: No contention between different jobs
    - Concurrent batches: Batches within same job serialize (safe)
    - Immutability: Deep copy on all reads/writes prevents shared references

    Storage Structure:
    - job_stats: {job_run_id: JobStats}
    - node_stats: {job_run_id: {node_id: {batch_id: NodeStats}}}
    - job_locks: {job_run_id: RLock} (per-job synchronization)

    Thread Safety Guarantees:
    1. All mutations acquire job-specific lock
    2. Deep copies prevent external mutations
    3. Lock-free reads for different job runs
    4. Atomic updates via copy-modify-replace pattern

    Performance Characteristics:
    - O(1) lookup for job stats
    - O(1) lookup for node stats by batch_id
    - O(n) for listing all node stats (n = number of batches)
    - Minimal lock contention for concurrent job runs

    Lifecycle:
    - Instantiated as singleton via dependency injection
    - Shared across all requests in single-process deployment
    - Supports unlimited concurrent job runs
    - Memory grows with active jobs (cleanup via delete_job_stats)
    """

    def __init__(self) -> None:
        """Initialize in-memory storage with fine-grained locking."""
        # Global lock for structure modifications (adding/removing jobs)
        self._global_lock = RLock()

        # Per-job locks for concurrent batch operations
        self._job_locks: dict[str, RLock] = {}

        # Job-level storage: {job_run_id: JobStats}
        self._job_stats: dict[str, JobStats] = {}

        # Node-level storage: {job_run_id: {node_id: {batch_id: NodeStats}}}
        # batch_id is None for non-batch records
        self._node_stats: dict[str, dict[str, dict[str | None, NodeStats]]] = defaultdict(lambda: defaultdict(dict))

    def _get_job_lock(self, *, job_run_id: str) -> RLock:
        """
        Get or create lock for specific job run.

        Uses double-checked locking pattern for performance.

        Args:
            job_run_id: Job run identifier

        Returns:
            RLock for this job run
        """
        # Fast path: lock already exists (no global lock needed)
        if job_run_id in self._job_locks:
            return self._job_locks[job_run_id]

        # Slow path: create new lock (requires global lock)
        with self._global_lock:
            # Double-check: another thread might have created it
            if job_run_id not in self._job_locks:
                self._job_locks[job_run_id] = RLock()
            return self._job_locks[job_run_id]

    def store_job_stats(self, job_stats: JobStats) -> None:
        """
        Store job-level statistics with fine-grained locking.

        Args:
            job_stats: Job statistics to store

        Raises:
            JobStatsStoreWriteException: If storage operation fails
        """
        job_run_id = job_stats.job_run_id
        lock = self._get_job_lock(job_run_id=job_run_id)

        with lock:
            try:
                # Deep copy to prevent external mutations
                self._job_stats[job_run_id] = deepcopy(job_stats)
                logger.debug("Stored job stats: job_run_id=%s", job_run_id)
            except Exception as e:
                logger.error("Failed to store job stats: %s", e)
                raise JobStatsStoreWriteException(
                    message=f"Failed to store job stats: {e}", job_run_id=job_run_id, operation="store_job_stats"
                ) from e

    def get_job_stats(self, job_run_id: str) -> JobStats | None:
        """
        Retrieve job-level statistics with fine-grained locking.

        Args:
            job_run_id: Job run identifier

        Returns:
            JobStats if found, None otherwise
        """
        lock = self._get_job_lock(job_run_id=job_run_id)

        with lock:
            job_stats = self._job_stats.get(job_run_id)
            if job_stats:
                # Deep copy to prevent external mutations
                return deepcopy(job_stats)
            return None

    def store_node_stats(self, *, job_run_id: str, node_stats: NodeStats) -> None:
        """
        Store node-level statistics with fine-grained locking.

        Args:
            job_run_id: Job run identifier (globally unique)
            node_stats: Node statistics to store

        Raises:
            JobStatsStoreWriteException: If storage operation fails
        """
        lock = self._get_job_lock(job_run_id=job_run_id)

        with lock:
            try:
                node_id = node_stats.id
                batch_id = getattr(node_stats, "batch_id", None)

                # Store in nested structure (None is valid key for non-batch records)
                self._node_stats[job_run_id][node_id][batch_id] = deepcopy(node_stats)

                logger.debug("Stored node stats: job_run_id=%s, node_id=%s, batch_id=%s", job_run_id, node_id, batch_id)
            except Exception as e:
                logger.error("Failed to store node stats: %s", e)
                raise JobStatsStoreWriteException(
                    message=f"Failed to store node stats: {e}", job_run_id=job_run_id, operation="store_node_stats"
                ) from e

    def get_node_stats(self, *, job_run_id: str) -> list[NodeStats]:
        """
        Retrieve ALL node statistics records (NO AGGREGATION).

        Returns a flat list of all node stats (batch and non-batch).
        Aggregation is handled by NodeStatsAggregator service layer.

        Args:
            job_run_id: Job run identifier (globally unique)

        Returns:
            List of ALL NodeStats records
        """
        lock = self._get_job_lock(job_run_id=job_run_id)

        with lock:
            result = []

            # Get all nodes for this job run
            nodes = self._node_stats.get(job_run_id, {})

            # Flatten nested structure into list
            for _node_id, batches in nodes.items():
                for _batch_id, node_stats in batches.items():
                    # Deep copy to prevent external mutations
                    result.append(deepcopy(node_stats))

            logger.debug("Retrieved %s node stats records: job_run_id=%s", len(result), job_run_id)
            return result

    def get_batch_node_stats(self, *, job_run_id: str) -> dict[str, dict[str, NodeStats]]:
        """
        Retrieve batch-level node statistics for micro-batching.

        Returns nested dictionary grouped by node_id, then batch_id.
        Used for detailed batch-level progress tracking.

        Args:
            job_run_id: Job run identifier (globally unique)

        Returns:
            Nested dict: {node_id: {batch_id: NodeStats}}
        """
        lock = self._get_job_lock(job_run_id=job_run_id)

        with lock:
            result = {}

            # Get all nodes for this job run
            nodes = self._node_stats.get(job_run_id, {})

            # Build nested structure, filtering out non-batch records
            for node_id, batches in nodes.items():
                batch_dict = {}
                for batch_id, node_stats in batches.items():
                    if batch_id is not None:  # Only include batch records
                        batch_dict[batch_id] = deepcopy(node_stats)

                if batch_dict:  # Only include nodes with batch records
                    result[node_id] = batch_dict

            logger.debug("Retrieved batch node stats: job_run_id=%s, nodes=%s", job_run_id, len(result))
            return result

    def get_failed_docs_for_batch(self, *, job_run_id: str, batch_id: str) -> list[str]:
        """Retrieve failed document IDs for all nodes in a single batch."""
        lock = self._get_job_lock(job_run_id=job_run_id)
        with lock:
            failed_doc_ids: list[str] = []
            nodes = self._node_stats.get(job_run_id, {})
            for _node_id, batches in nodes.items():
                node_stats = batches.get(batch_id)
                if node_stats is None:
                    continue
                failed_docs = getattr(node_stats, "failed_docs", None)
                if failed_docs:
                    failed_doc_ids.extend(failed_docs)
            return failed_doc_ids

    def bulk_store_node_stats(self, *, job_run_id: str, node_stats_list: list[NodeStats]) -> None:
        """
        Bulk store multiple node statistics (micro-batching).

        Used to create pending node stats for all batches at once.

        Args:
            job_run_id: Job run identifier (globally unique)
            node_stats_list: List of node statistics to store

        Raises:
            JobStatsStoreWriteException: If bulk operation fails
        """
        lock = self._get_job_lock(job_run_id=job_run_id)

        with lock:
            try:
                for node_stats in node_stats_list:
                    node_id = node_stats.id
                    batch_id = getattr(node_stats, "batch_id", None)

                    # Store in nested structure
                    self._node_stats[job_run_id][node_id][batch_id] = deepcopy(node_stats)

                logger.debug("Bulk stored %s node stats: job_run_id=%s", len(node_stats_list), job_run_id)
            except Exception as e:
                logger.error("Failed to bulk store node stats: %s", e)
                raise JobStatsStoreWriteException(
                    message=f"Failed to bulk store node stats: {e}",
                    job_run_id=job_run_id,
                    operation="bulk_store_node_stats",
                ) from e

    def atomic_increment_fields(
        self,
        job_run_id: str,
        increments: dict[str, int],
        updates: dict[str, Any] | None = None,
        jsonb_merges: dict[str, dict] | None = None,
    ) -> None:
        """
        Atomically increment numeric fields and update others.

        Production-grade implementation with:
        - Fine-grained per-job locking
        - Copy-modify-replace pattern for immutability
        - No in-place mutations of stored objects

        Args:
            job_run_id: Job run identifier
            increments: Fields to increment {field_name: increment_value}
            updates: Fields to update {field_name: new_value}
            jsonb_merges: JSONB fields to merge (treated as dict merge)

        Example:
            atomic_increment_fields(
                job_run_id="job_123",
                increments={DocpipeConstants.PROCESSED_DOCS: 10, DocpipeConstants.FAILED_DOCS: 2},
                updates={DocpipeConstants.STATUS: ExecutionStatus.RUNNING.value, "heartbeat_timestamp": 1704067260}
            )
        """
        lock = self._get_job_lock(job_run_id=job_run_id)

        with lock:
            job_stats = self._job_stats.get(job_run_id)
            if not job_stats:
                logger.warning("Job stats not found for atomic update: %s", job_run_id)
                return

            # CRITICAL: Deep copy before mutation to maintain immutability
            job_stats = deepcopy(job_stats)

            # Apply increments to copy
            for field_name, increment_value in increments.items():
                current_value = getattr(job_stats, field_name, 0)
                setattr(job_stats, field_name, current_value + increment_value)

            # Apply updates to copy
            if updates:
                for field_name, new_value in updates.items():
                    setattr(job_stats, field_name, new_value)

            # Apply JSONB merges to copy
            if jsonb_merges:
                for field_name, merge_dict in jsonb_merges.items():
                    current_dict = getattr(job_stats, field_name, {})
                    if isinstance(current_dict, dict):
                        # Deep copy dict to avoid nested mutations
                        updated_dict = deepcopy(current_dict)
                        updated_dict.update(merge_dict)
                        setattr(job_stats, field_name, updated_dict)

            # Atomic replacement of stored object
            self._job_stats[job_run_id] = job_stats

            logger.debug("Atomic update applied: job_run_id=%s", job_run_id)

    def get_node_stats_by_batch_and_node(
        self, job_run_id: str, node_id: str, batch_id: str | None = None
    ) -> NodeStats | None:
        """
        Get specific node stats for batch and node combination.

        Args:
            job_run_id: Job run identifier
            node_id: Node identifier
            batch_id: Batch identifier (None for aggregated stats)

        Returns:
            NodeStats if found, None otherwise
        """
        lock = self._get_job_lock(job_run_id=job_run_id)

        with lock:
            nodes = self._node_stats.get(job_run_id, {})
            batches = nodes.get(node_id, {})
            node_stats = batches.get(batch_id)

            if node_stats:
                return deepcopy(node_stats)
            return None

    def delete_job_stats(self, job_run_id: str) -> None:
        """
        Delete job statistics and all associated node statistics.

        Args:
            job_run_id: Job run identifier

        Raises:
            JobStatsStoreDeleteException: If job_run_id not found or deletion fails
        """
        lock = self._get_job_lock(job_run_id=job_run_id)

        with lock:
            if job_run_id not in self._job_stats:
                raise JobStatsStoreDeleteException(message=f"Job run not found: {job_run_id}", job_run_id=job_run_id)

            # Plain dict deletes of keys checked under the same lock cannot fail
            del self._job_stats[job_run_id]
            self._node_stats.pop(job_run_id, None)

            # Clean up lock (prevents memory leak)
            with self._global_lock:
                self._job_locks.pop(job_run_id, None)

            logger.info("Deleted job stats: job_run_id=%s", job_run_id)

    def clear(self) -> None:
        """
        Clear all stored data (useful for testing).

        Not part of JobStatsStore interface, but useful for test cleanup.
        """
        with self._global_lock:
            self._job_stats.clear()
            self._node_stats.clear()
            self._job_locks.clear()
            logger.info("Cleared all in-memory job stats")

    def get_all_job_run_ids(self) -> list[str]:
        """
        Get all job run IDs (useful for testing and debugging).

        Not part of JobStatsStore interface.

        Returns:
            List of all job_run_ids
        """
        with self._global_lock:
            return list(self._job_stats.keys())

    def list_job_runs(
        self,
        job_id: str | None = None,
        job_ids: list[str] | None = None,
        status: ExecutionStatus | str | None = None,
        limit: int = 100,
    ) -> list[JobStats]:
        """
        List job runs with optional filters.

        Uses global lock since it needs to iterate all jobs.

        Args:
            job_id: Optional filter by a single job_id
            job_ids: Optional filter by a set of job_ids (evaluated as set membership)
            status: Optional filter by status
            limit: Maximum number of results

        Returns:
            List of JobStats matching filters (sorted by start_time desc)
        """
        job_ids_set = set(job_ids) if job_ids else None

        with self._global_lock:
            result = []

            for job_stats in self._job_stats.values():
                # Apply filters
                if job_id and job_stats.job_id != job_id:
                    continue
                if job_ids_set and job_stats.job_id not in job_ids_set:
                    continue
                if status and job_stats.status != status:
                    continue

                # Deep copy to prevent external mutations
                result.append(deepcopy(job_stats))

            # Sort by start_time descending (most recent first)
            result.sort(key=lambda x: x.start_time or 0, reverse=True)

            # Apply limit
            return result[:limit]
