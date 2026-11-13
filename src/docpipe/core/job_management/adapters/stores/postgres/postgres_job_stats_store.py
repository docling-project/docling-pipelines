"""
PostgreSQL implementation of JobStatsStore.

Provides persistent storage for job and node statistics using PostgreSQL
with schema managed during application startup when PostgreSQL storage is enabled.

Features:
- Persistent storage in PostgreSQL database
- Atomic operations for concurrent updates
- Atomic operations for concurrent updates
- Support for micro-batching with batch_id tracking
- JSONB fields for flexible metadata storage

Configuration:
- Set environment variables or YAML config for connection details

"""

from typing import Any

from docpipe.core.constants.constants import ExecutionStatus
from docpipe.core.job_management.domain.models import JobStats, NodeStats
from docpipe.core.job_management.domain.ports import JobStatsStore
from docpipe.exceptions.docpipe_exceptions import (
    JobStatsStoreDeleteException,
    JobStatsStoreInitializationException,
    JobStatsStoreReadException,
    JobStatsStoreWriteException,
)
from docpipe.utils.infrastructure.logging import get_logger

from .dal.job_stats_dal import JobStatsDAL
from .dal.node_stats_dal import NodeStatsDAL
from .database import create_postgres_engine, create_session_factory, get_postgres_connection_string
from .mappers import PostgresModelMapper

logger = get_logger()


class PostgresJobStatsStore(JobStatsStore):
    """
    PostgreSQL-backed storage for job statistics.

    Features:
    - Persistent storage in PostgreSQL database
    - Atomic operations for concurrent updates
    - Support for micro-batching with batch_id tracking
    - JSONB fields for flexible metadata storage
    - Foreign key relationships between job and node stats

    Configuration:
        Set environment variables:
        - DOCPIPE_POSTGRES_HOST (default: localhost)
        - DOCPIPE_POSTGRES_PORT (default: 5432)
        - DOCPIPE_POSTGRES_DB (default: docpipe)
        - DOCPIPE_POSTGRES_USER (default: docpipe_user)
        - DOCPIPE_POSTGRES_PASSWORD (required)
    """

    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        job_stats_model=None,
        node_stats_model=None,
        session_factory=None,
    ):
        """
        Initialize PostgreSQL job stats store.

        Args:
            config: Optional configuration dict (from YAML or factory)
                - postgres: PostgreSQL connection settings
            job_stats_model: Optional SQLModel class for job stats.
                When provided, the default JobStatsModel is never imported or instantiated.
            node_stats_model: Optional SQLModel class for node stats.
                When provided, the default NodeStatsModel is never imported or instantiated.
            session_factory: Optional session factory.
                When provided, engine creation is skipped entirely — the caller owns the pool.

        Raises:
            JobStatsStoreInitializationException: If initialization fails
        """
        self.config = config or {}
        self._job_stats_model_cls = job_stats_model
        self._node_stats_model_cls = node_stats_model

        try:
            if session_factory is not None:
                # Caller owns the connection pool — skip engine creation entirely
                self._engine = None
                sf = session_factory
            else:
                # Build engine from config / environment
                connection_string = get_postgres_connection_string(config=self.config)
                if not connection_string:
                    raise JobStatsStoreInitializationException(
                        message="PostgreSQL connection not configured. "
                        "Set password in YAML config or DOCPIPE_POSTGRES_PASSWORD environment variable.",
                        store_type="postgres",
                    )
                self._engine = create_postgres_engine(connection_string=connection_string, config=self.config)
                sf = create_session_factory(engine=self._engine)

            # Initialize DAL components, passing injected model classes
            self._job_stats_dal = JobStatsDAL(session_factory=sf, model=job_stats_model)
            self._node_stats_dal = NodeStatsDAL(session_factory=sf, model=node_stats_model)

            logger.info("PostgresJobStatsStore initialized successfully")
        except JobStatsStoreInitializationException:
            raise
        except Exception as e:
            logger.error("Failed to initialize PostgresJobStatsStore: %s", e)
            raise JobStatsStoreInitializationException(
                message=f"PostgreSQL initialization failed: {e}", store_type="postgres"
            ) from e

    def store_job_stats(self, job_stats: JobStats) -> None:
        """
        Store job-level statistics.

        Args:
            job_stats: Job statistics to store

        Raises:
            JobStatsStoreWriteException: If storage operation fails
        """
        try:
            job_run_stats_model = PostgresModelMapper.to_db_job_stats(
                domain_model=job_stats,
                job_stats_cls=self._job_stats_model_cls,
            )
            self._job_stats_dal.upsert(job_run_stats=job_run_stats_model)
            logger.debug("Stored job stats: job_run_id=%s", job_stats.job_run_id)
        except Exception as e:
            logger.error("Failed to store job stats: %s", e)
            raise JobStatsStoreWriteException(
                message=f"Failed to store job stats: {e}", job_run_id=job_stats.job_run_id, operation="store_job_stats"
            ) from e

    def get_job_stats(self, job_run_id: str) -> JobStats | None:
        """
        Retrieve job-level statistics.

        Args:
            job_run_id: Job run identifier

        Returns:
            JobStats if found, None otherwise

        Raises:
            JobStatsStoreReadException: If read operation fails
        """
        try:
            db_model = self._job_stats_dal.get_by_job_run_id(job_run_id=job_run_id)
            if db_model is None:
                return None
            return PostgresModelMapper.to_domain_job_stats(db_model=db_model)
        except Exception as e:
            logger.error("Failed to get job stats: %s", e)
            raise JobStatsStoreReadException(
                message=f"Failed to get job stats: {e}", job_run_id=job_run_id, operation="get_job_stats"
            ) from e

    def store_node_stats(self, *, job_run_id: str, node_stats: NodeStats) -> None:
        """
        Store node-level statistics.

        Args:
            job_run_id: Job run identifier (globally unique)
            node_stats: Node statistics to store

        Raises:
            JobStatsStoreWriteException: If storage operation fails
        """
        try:
            node_stats_model = PostgresModelMapper.to_db_node_stats(
                domain_model=node_stats,
                job_run_id=job_run_id,
                node_stats_cls=self._node_stats_model_cls,
            )
            self._node_stats_dal.upsert(node_stat=node_stats_model)
            logger.debug(
                "Stored node stats: job_run_id=%s, node_id=%s, batch_id=%s",
                job_run_id,
                node_stats.id,
                node_stats.batch_id,
            )
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

        Raises:
            JobStatsStoreReadException: If read operation fails
        """
        try:
            db_models = self._node_stats_dal.get_all_node_stats(job_run_id=job_run_id)
            return [PostgresModelMapper.to_domain_node_stats(db_model=ns) for ns in db_models]
        except Exception as e:
            logger.error("Failed to get node stats: %s", e)
            raise JobStatsStoreReadException(
                message=f"Failed to get node stats: {e}", job_run_id=job_run_id, operation="get_node_stats"
            ) from e

    def get_batch_node_stats(self, *, job_run_id: str) -> dict[str, dict[str, NodeStats]]:
        """
        Retrieve batch-level node statistics for micro-batching.

        Returns nested dictionary grouped by node_id, then batch_id.

        Args:
            job_run_id: Job run identifier (globally unique)

        Returns:
            Nested dict: {node_id: {batch_id: NodeStats}}

        Raises:
            JobStatsStoreReadException: If read operation fails
        """
        try:
            batch_node_stats = self._node_stats_dal.get_batch_node_stats(job_run_id=job_run_id)

            result: dict[str, dict[str, NodeStats]] = {}
            for db_model in batch_node_stats:
                batch_id = db_model.batch_id
                if batch_id is None:
                    continue

                node_id = db_model.node_id
                if node_id not in result:
                    result[node_id] = {}

                result[node_id][batch_id] = PostgresModelMapper.to_domain_node_stats(db_model=db_model)

            return result
        except Exception as e:
            logger.error("Failed to get batch node stats: %s", e)
            raise JobStatsStoreReadException(
                message=f"Failed to get batch node stats: {e}", job_run_id=job_run_id, operation="get_batch_node_stats"
            ) from e

    def get_failed_docs_for_batch(self, *, job_run_id: str, batch_id: str) -> list[str]:
        """
        Retrieve failed document IDs for all nodes in a single batch.

        SQL-scoped: only rows matching job_run_id + batch_id are fetched —
        no full-job aggregation, no Python-side filter.
        """
        try:
            db_models = self._node_stats_dal.get_failed_docs_for_batch(job_run_id=job_run_id, batch_id=batch_id)
            failed_doc_ids: list[str] = []
            for db_model in db_models:
                failed_docs = getattr(db_model, "failed_docs", None)
                if failed_docs:
                    failed_doc_ids.extend(failed_docs)
            return failed_doc_ids
        except Exception as e:
            logger.error("Failed to get failed docs for batch: %s", e)
            raise JobStatsStoreReadException(
                message=f"Failed to get failed docs for batch: {e}",
                job_run_id=job_run_id,
                operation="get_failed_docs_for_batch",
            ) from e

    def bulk_store_node_stats(self, *, job_run_id: str, node_stats_list: list[NodeStats]) -> None:
        """
        Bulk store multiple node statistics (micro-batching).

        Args:
            job_run_id: Job run identifier (globally unique)
            node_stats_list: List of node statistics to store

        Raises:
            JobStatsStoreWriteException: If bulk operation fails
        """
        if not node_stats_list:
            return

        try:
            node_stats_models = [
                PostgresModelMapper.to_db_node_stats(
                    domain_model=ns,
                    job_run_id=job_run_id,
                    node_stats_cls=self._node_stats_model_cls,
                )
                for ns in node_stats_list
            ]
            self._node_stats_dal.bulk_insert(node_stats=node_stats_models)
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

        Uses PostgreSQL atomic operations for thread-safety.

        Args:
            job_run_id: Job run identifier
            increments: Fields to increment {field_name: increment_value}
            updates: Fields to update {field_name: new_value}
            jsonb_merges: JSONB fields to merge {field_name: merge_dict}

        Raises:
            JobStatsStoreWriteException: If atomic update fails
        """
        try:
            self._job_stats_dal.atomic_increment_fields(
                job_run_id=job_run_id, increments=increments, updates=updates, jsonb_merges=jsonb_merges
            )
            logger.debug("Atomic update applied: job_run_id=%s", job_run_id)
        except Exception as e:
            logger.error("Failed to atomically increment fields: %s", e)
            raise JobStatsStoreWriteException(
                message=f"Failed to atomically increment fields: {e}",
                job_run_id=job_run_id,
                operation="atomic_increment_fields",
            ) from e

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

        Raises:
            JobStatsStoreReadException: If read operation fails
        """
        try:
            db_model = self._node_stats_dal.get_node_stats_by_run_batch(
                node_id=node_id, job_run_id=job_run_id, batch_id=batch_id
            )

            if db_model is None:
                return None

            return PostgresModelMapper.to_domain_node_stats(db_model=db_model)
        except Exception as e:
            logger.error("Failed to get node stats by batch and node: %s", e)
            raise JobStatsStoreReadException(
                message=f"Failed to get node stats by batch and node: {e}",
                job_run_id=job_run_id,
                operation="get_node_stats_by_batch_and_node",
            ) from e

    def delete_job_stats(self, job_run_id: str) -> None:
        """
        Delete job statistics and all associated node statistics.

        PostgreSQL CASCADE delete handles node_stats automatically.

        Args:
            job_run_id: Job run identifier

        Raises:
            JobStatsStoreDeleteException: If job_run_id not found or deletion fails
        """
        try:
            rows_deleted = self._job_stats_dal.delete_job_stats(job_run_id=job_run_id)
            if rows_deleted == 0:
                raise JobStatsStoreDeleteException(message=f"Job run not found: {job_run_id}", job_run_id=job_run_id)
            logger.info("Deleted job stats: job_run_id=%s", job_run_id)
        except JobStatsStoreDeleteException:
            raise
        except Exception as e:
            logger.error("Failed to delete job stats: %s", e)
            raise JobStatsStoreDeleteException(message=f"Failed to delete job stats: {e}", job_run_id=job_run_id) from e

    def list_job_runs(
        self,
        job_id: str | None = None,
        job_ids: list[str] | None = None,
        status: ExecutionStatus | str | None = None,
        limit: int = 100,
    ) -> list[JobStats]:
        """
        List job runs with optional filters.

        Args:
            job_id: Optional filter by a single job_id
            job_ids: Optional filter by a set of job_ids (adds WHERE job_id IN (...) clause)
            status: Optional filter by status
            limit: Maximum number of results

        Returns:
            List of JobStats matching filters (sorted by start_time desc)

        Raises:
            JobStatsStoreReadException: If list operation fails
        """
        try:
            job_run_stats_list = self._job_stats_dal.list_job_runs(
                job_id=job_id,
                job_ids=job_ids,
                status=status.value if isinstance(status, ExecutionStatus) else status,
                limit=limit,
            )

            return [PostgresModelMapper.to_domain_job_stats(db_model=jrs) for jrs in job_run_stats_list]
        except Exception as e:
            logger.error("Failed to list jobs: %s", e)
            raise JobStatsStoreReadException(
                message=f"Failed to list jobs: {e}", job_run_id=None, operation="list_job_runs"
            ) from e

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

        Raises:
            JobStatsStoreReadException: If the count operation fails
        """
        try:
            return self._job_stats_dal.count_job_runs(
                job_id=job_id,
                job_ids=job_ids,
                status=status.value if isinstance(status, ExecutionStatus) else status,
            )
        except Exception as e:
            logger.error("Failed to count jobs: %s", e)
            raise JobStatsStoreReadException(
                message=f"Failed to count jobs: {e}", job_run_id=None, operation="count_job_runs"
            ) from e
