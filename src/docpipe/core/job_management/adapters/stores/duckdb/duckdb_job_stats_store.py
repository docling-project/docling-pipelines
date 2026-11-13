"""
DuckDB implementation of JobStatsStore.

Provides persistent storage for job and node statistics using DuckDB,
an embedded analytical database that requires no server setup.

Features:
- Embedded database (no server required)
- Persistent storage in single file
- Atomic operations with transactions
- Support for micro-batching with batch_id tracking
- JSON columns for flexible metadata storage
- Analytical query capabilities

Configuration:
- Set database_path in YAML config or use default
- Default: data/duckdb/job_stats.duckdb
"""

import json
from pathlib import Path
from typing import Any

from docpipe.core.constants.constants import DocpipeConstants, ExecutionStatus
from docpipe.core.job_management.domain.models import JobStats, NodeStats
from docpipe.core.job_management.domain.ports import JobStatsStore
from docpipe.exceptions.docpipe_exceptions import (
    JobStatsStoreDeleteException,
    JobStatsStoreInitializationException,
    JobStatsStoreReadException,
    JobStatsStoreWriteException,
)
from docpipe.utils.duckdb import DuckDBConnectionManager
from docpipe.utils.infrastructure.logging import get_logger

logger = get_logger()


class DuckDBJobStatsStore(JobStatsStore):  # type: ignore[misc]
    """
    DuckDB-backed storage for job statistics.

    Features:
    - Embedded database requiring no server setup
    - Persistent storage in single .duckdb file
    - Atomic operations with SQL transactions
    - Support for micro-batching with batch_id tracking
    - JSON columns for flexible metadata storage
    - Foreign key relationships between job and node stats

    Configuration:
        database_path: Path to DuckDB file (default: data/duckdb/job_stats.duckdb)
    """

    def __init__(self, *, config: dict[str, Any] | None = None):
        """
        Initialize DuckDB job stats store.

        Args:
            config: Optional configuration dict
                - database_path: Path to DuckDB file

        Raises:
            JobStatsStoreInitializationException: If initialization fails
        """
        self.config = config or {}

        # Get database path from config or use default
        self.database_path = self.config.get("database_path", DocpipeConstants.JOB_STATS_DEFAULT_DB_PATH)

        # Ensure directory exists
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize connection manager
        self.connection_manager = DuckDBConnectionManager()

        try:
            # Initialize schema
            self._initialize_schema()
            logger.info("DuckDBJobStatsStore initialized: %s", self.database_path)
        except Exception as e:
            logger.error("Failed to initialize DuckDBJobStatsStore: %s", e)
            raise JobStatsStoreInitializationException(
                message=f"DuckDB initialization failed: {e}", store_type="duckdb"
            ) from e

    def _initialize_schema(self) -> None:
        """Initialize database schema if not exists."""
        with self.connection_manager.get_connection(database_path=self.database_path) as conn:
            # Create job_stats table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS job_stats (
                    job_run_id VARCHAR PRIMARY KEY,
                    job_id VARCHAR NOT NULL,
                    status VARCHAR,
                    message TEXT,
                    start_time BIGINT,
                    end_time BIGINT,
                    duration BIGINT,
                    heartbeat_timestamp BIGINT,
                    progress_timestamp BIGINT DEFAULT 0,
                    total_docs INTEGER DEFAULT 0,
                    processed_docs INTEGER DEFAULT 0,
                    completed_docs INTEGER DEFAULT 0,
                    failed_docs INTEGER DEFAULT 0,
                    skipped_docs INTEGER DEFAULT 0,
                    deleted_doc_count INTEGER DEFAULT 0,
                    total_pages_processed INTEGER DEFAULT 0,
                    page_type_stats JSON,
                    execution_time BIGINT,
                    orchestrator VARCHAR,
                    container_kind VARCHAR,
                    container_id VARCHAR,
                    flow_id VARCHAR,
                    flow_name VARCHAR,
                    user_id VARCHAR,
                    account_id VARCHAR,
                    user_entitlements JSON
                )
            """)

            # Forward-compatibility: add flow_name to existing databases
            conn.execute("""
                ALTER TABLE job_stats ADD COLUMN IF NOT EXISTS flow_name VARCHAR
            """)

            # Create node_stats table with auto-incrementing primary key
            conn.execute("""
                CREATE SEQUENCE IF NOT EXISTS node_stats_id_seq START 1
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS node_stats (
                    id INTEGER PRIMARY KEY DEFAULT nextval('node_stats_id_seq'),
                    job_run_id VARCHAR NOT NULL,
                    node_id VARCHAR NOT NULL,
                    name VARCHAR NOT NULL,
                    batch_id VARCHAR,
                    batch_num INTEGER,
                    node_status VARCHAR,
                    error TEXT,
                    start_time BIGINT,
                    end_time BIGINT,
                    time_taken BIGINT,
                    col_names JSON,
                    total_docs JSON,
                    failed_docs JSON,
                    skipped_docs JSON,
                    docs_completed JSON,
                    docs_completed_count INTEGER DEFAULT 0,
                    node_metadata JSON,
                    FOREIGN KEY (job_run_id) REFERENCES job_stats(job_run_id),
                    UNIQUE(job_run_id, node_id, batch_id)
                )
            """)

            # Create sequence for node_stats id
            conn.execute("""
                CREATE SEQUENCE IF NOT EXISTS node_stats_id_seq START 1
            """)

    def store_job_stats(self, job_stats: JobStats) -> None:
        """
        Store job-level statistics (UPSERT).

        Args:
            job_stats: Job statistics to store

        Raises:
            JobStatsStoreWriteException: If storage operation fails
        """
        try:
            with self.connection_manager.get_connection(database_path=self.database_path) as conn:
                # Convert to dict, excluding nested node_stats
                data = job_stats.model_dump(exclude={"node_stats", "batch_node_stats"})

                # Serialize JSON fields
                if data.get("page_type_stats"):
                    data["page_type_stats"] = json.dumps(data["page_type_stats"])
                if data.get("user_entitlements"):
                    data["user_entitlements"] = json.dumps(data["user_entitlements"])

                # UPSERT using INSERT OR REPLACE
                conn.execute(
                    """
                    INSERT OR REPLACE INTO job_stats (
                        job_run_id, job_id, status, message,
                        start_time, end_time, duration, heartbeat_timestamp, progress_timestamp,
                        total_docs, processed_docs, completed_docs, failed_docs,
                        skipped_docs, deleted_doc_count, total_pages_processed,
                        page_type_stats, execution_time, orchestrator,
                        container_kind, container_id, flow_id, flow_name,
                        user_id, account_id, user_entitlements
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    [
                        data["job_run_id"],
                        data["job_id"],
                        data["status"],
                        data["message"],
                        data["start_time"],
                        data["end_time"],
                        data["duration"],
                        data["heartbeat_timestamp"],
                        data["progress_timestamp"],
                        data["total_docs"],
                        data["processed_docs"],
                        data["completed_docs"],
                        data["failed_docs"],
                        data["skipped_docs"],
                        data["deleted_doc_count"],
                        data["total_pages_processed"],
                        data.get("page_type_stats"),
                        data.get("execution_time"),
                        data["orchestrator"],
                        data.get("container_kind"),
                        data.get("container_id"),
                        data.get("flow_id"),
                        data.get("flow_name"),
                        data.get("user_id"),
                        data.get("account_id"),
                        data.get("user_entitlements"),
                    ],
                )

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
            with self.connection_manager.get_connection(database_path=self.database_path, read_only=True) as conn:
                result = conn.execute("SELECT * FROM job_stats WHERE job_run_id = ?", [job_run_id]).fetchone()

                if result is None:
                    return None

                # Convert to dict
                columns = [desc[0] for desc in conn.description]
                data = dict(zip(columns, result, strict=False))

                # Parse JSON fields
                if data.get("page_type_stats"):
                    data["page_type_stats"] = json.loads(data["page_type_stats"])
                if data.get("user_entitlements"):
                    data["user_entitlements"] = json.loads(data["user_entitlements"])

                return JobStats(**data)
        except Exception as e:
            logger.error("Failed to get job stats: %s", e)
            raise JobStatsStoreReadException(
                message=f"Failed to get job stats: {e}", job_run_id=job_run_id, operation="get_job_stats"
            ) from e

    def store_node_stats(self, *, job_run_id: str, node_stats: NodeStats) -> None:
        """
        Store node-level statistics (UPSERT).

        Args:
            job_run_id: Job run identifier
            node_stats: Node statistics to store

        Raises:
            JobStatsStoreWriteException: If storage operation fails
        """
        try:
            with self.connection_manager.get_connection(database_path=self.database_path) as conn:
                data = node_stats.model_dump(by_alias=True)

                # Serialize JSON/list fields
                for field in [
                    "col_names",
                    "total_docs",
                    "failed_docs",
                    "skipped_docs",
                    "docs_completed",
                    "node_metadata",
                ]:
                    if data.get(field):
                        data[field] = json.dumps(data[field])

                # Check if record exists
                existing = conn.execute(
                    """
                    SELECT id FROM node_stats
                    WHERE job_run_id = ? AND node_id = ? AND
                          (batch_id = ? OR (batch_id IS NULL AND ? IS NULL))
                """,
                    [job_run_id, data["id"], data.get("batch_id"), data.get("batch_id")],
                ).fetchone()

                if existing:
                    # Update existing record
                    conn.execute(
                        """
                        UPDATE node_stats SET
                            name = ?, node_status = ?, error = ?,
                            start_time = ?, end_time = ?, time_taken = ?,
                            col_names = ?, total_docs = ?, failed_docs = ?,
                            skipped_docs = ?, docs_completed = ?, docs_completed_count = ?,
                            node_metadata = ?, batch_num = ?
                        WHERE id = ?
                    """,
                        [
                            data["name"],
                            data["node_status"],
                            data.get("error"),
                            data["start_time"],
                            data["end_time"],
                            data.get("time_taken"),
                            data.get("col_names"),
                            data.get("total_docs"),
                            data.get("failed_docs"),
                            data.get("skipped_docs"),
                            data.get("docs_completed"),
                            data.get("docs_completed_count", 0),
                            data.get("node_metadata"),
                            data.get("batch_num"),
                            existing[0],
                        ],
                    )
                else:
                    # Insert new record
                    conn.execute(
                        """
                        INSERT INTO node_stats (
                            id, job_run_id, node_id, name, batch_id, batch_num,
                            node_status, error, start_time, end_time, time_taken,
                            col_names, total_docs, failed_docs, skipped_docs,
                            docs_completed, docs_completed_count, node_metadata
                        ) VALUES (nextval('node_stats_id_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        [
                            job_run_id,
                            data["id"],
                            data["name"],
                            data.get("batch_id"),
                            data.get("batch_num"),
                            data["node_status"],
                            data.get("error"),
                            data["start_time"],
                            data["end_time"],
                            data.get("time_taken"),
                            data.get("col_names"),
                            data.get("total_docs"),
                            data.get("failed_docs"),
                            data.get("skipped_docs"),
                            data.get("docs_completed"),
                            data.get("docs_completed_count", 0),
                            data.get("node_metadata"),
                        ],
                    )

                logger.debug(
                    "Stored node stats: job_run_id=%s, node_id=%s, batch_id=%s",
                    job_run_id,
                    data["id"],
                    data.get("batch_id"),
                )
        except Exception as e:
            logger.error("Failed to store node stats: %s", e)
            raise JobStatsStoreWriteException(
                message=f"Failed to store node stats: {e}", job_run_id=job_run_id, operation="store_node_stats"
            ) from e

    def get_node_stats(self, *, job_run_id: str) -> list[NodeStats]:
        """
        Retrieve ALL node statistics records (NO AGGREGATION).

        Args:
            job_run_id: Job run identifier

        Returns:
            List of ALL NodeStats records

        Raises:
            JobStatsStoreReadException: If read operation fails
        """
        try:
            with self.connection_manager.get_connection(database_path=self.database_path, read_only=True) as conn:
                results = conn.execute(
                    "SELECT * FROM node_stats WHERE job_run_id = ? ORDER BY id", [job_run_id]
                ).fetchall()

                node_stats_list = []
                columns = [desc[0] for desc in conn.description]

                for result in results:
                    data = dict(zip(columns, result, strict=False))

                    # Parse JSON fields
                    for field in [
                        "col_names",
                        "total_docs",
                        "failed_docs",
                        "skipped_docs",
                        "docs_completed",
                        "node_metadata",
                    ]:
                        if data.get(field):
                            data[field] = json.loads(data[field])

                    # Remove auto-increment id and job_run_id; map node_id -> id
                    data.pop("id", None)
                    data.pop("job_run_id", None)
                    data["id"] = data.pop("node_id")

                    node_stats_list.append(NodeStats(**data))

                logger.debug("Retrieved %s node stats: job_run_id=%s", len(node_stats_list), job_run_id)
                return node_stats_list
        except Exception as e:
            logger.error("Failed to get node stats: %s", e)
            raise JobStatsStoreReadException(
                message=f"Failed to get node stats: {e}", job_run_id=job_run_id, operation="get_node_stats"
            ) from e

    def get_failed_docs_for_batch(self, *, job_run_id: str, batch_id: str) -> list[str]:
        """Retrieve failed document IDs for all nodes in a single batch."""
        try:
            all_records = self.get_node_stats(job_run_id=job_run_id)
            failed_doc_ids: list[str] = []
            for record in all_records:
                if getattr(record, "batch_id", None) != batch_id:
                    continue
                failed_docs = getattr(record, "failed_docs", None)
                if failed_docs:
                    failed_doc_ids.extend(failed_docs)
            return failed_doc_ids
        except Exception as e:
            raise JobStatsStoreReadException(
                message=f"Failed to get failed docs for batch: {e}",
                job_run_id=job_run_id,
                operation="get_failed_docs_for_batch",
            ) from e

    def get_batch_node_stats(self, *, job_run_id: str) -> dict[str, dict[str, NodeStats]]:
        """
        Retrieve batch-level node statistics for micro-batching.

        Returns nested dictionary grouped by node_id, then batch_id.

        Args:
            job_run_id: Job run identifier

        Returns:
            Nested dict: {node_id: {batch_id: NodeStats}}

        Raises:
            JobStatsStoreReadException: If read operation fails
        """
        try:
            with self.connection_manager.get_connection(database_path=self.database_path, read_only=True) as conn:
                results = conn.execute(
                    "SELECT * FROM node_stats WHERE job_run_id = ? AND batch_id IS NOT NULL ORDER BY id", [job_run_id]
                ).fetchall()

                batch_stats: dict[str, dict[str, NodeStats]] = {}
                columns = [desc[0] for desc in conn.description]

                for result in results:
                    data = dict(zip(columns, result, strict=False))

                    # Parse JSON fields
                    for field in [
                        "col_names",
                        "total_docs",
                        "failed_docs",
                        "skipped_docs",
                        "docs_completed",
                        "node_metadata",
                    ]:
                        if data.get(field):
                            data[field] = json.loads(data[field])

                    node_id = data["node_id"]
                    batch_id = data["batch_id"]

                    # Remove auto-increment id and job_run_id; map node_id -> id
                    data.pop("id", None)
                    data.pop("job_run_id", None)
                    data["id"] = data.pop("node_id")

                    if node_id not in batch_stats:
                        batch_stats[node_id] = {}

                    batch_stats[node_id][batch_id] = NodeStats(**data)

                logger.debug("Retrieved batch node stats: job_run_id=%s, nodes=%s", job_run_id, len(batch_stats))
                return batch_stats
        except Exception as e:
            logger.error("Failed to get batch node stats: %s", e)
            raise JobStatsStoreReadException(
                message=f"Failed to get batch node stats: {e}", job_run_id=job_run_id, operation="get_batch_node_stats"
            ) from e

    def bulk_store_node_stats(self, *, job_run_id: str, node_stats_list: list[NodeStats]) -> None:
        """
        Bulk store multiple node statistics (micro-batching).

        Args:
            job_run_id: Job run identifier
            node_stats_list: List of node statistics to store

        Raises:
            JobStatsStoreWriteException: If bulk operation fails
        """
        if not node_stats_list:
            return

        try:
            with self.connection_manager.get_connection(database_path=self.database_path) as conn:
                conn.execute("BEGIN TRANSACTION")

                try:
                    for node_stats in node_stats_list:
                        data = node_stats.model_dump(by_alias=True)

                        # Serialize JSON/list fields
                        for field in [
                            "col_names",
                            "total_docs",
                            "failed_docs",
                            "skipped_docs",
                            "docs_completed",
                            "node_metadata",
                        ]:
                            if data.get(field):
                                data[field] = json.dumps(data[field])

                        conn.execute(
                            """
                            INSERT INTO node_stats (
                                id, job_run_id, node_id, name, batch_id, batch_num,
                                node_status, error, start_time, end_time, time_taken,
                                col_names, total_docs, failed_docs, skipped_docs,
                                docs_completed, docs_completed_count, node_metadata
                            ) VALUES (nextval('node_stats_id_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                            [
                                job_run_id,
                                data["id"],
                                data["name"],
                                data.get("batch_id"),
                                data.get("batch_num"),
                                data["node_status"],
                                data.get("error"),
                                data["start_time"],
                                data["end_time"],
                                data.get("time_taken"),
                                data.get("col_names"),
                                data.get("total_docs"),
                                data.get("failed_docs"),
                                data.get("skipped_docs"),
                                data.get("docs_completed"),
                                data.get("docs_completed_count", 0),
                                data.get("node_metadata"),
                            ],
                        )

                    conn.execute("COMMIT")
                    logger.debug("Bulk stored %s node stats: job_run_id=%s", len(node_stats_list), job_run_id)
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
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
        jsonb_merges: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """
        Atomically increment numeric fields and update others.

        Uses DuckDB transactions for atomicity.

        Args:
            job_run_id: Job run identifier
            increments: Fields to increment {field_name: increment_value}
            updates: Fields to update {field_name: new_value}
            jsonb_merges: JSON fields to merge {field_name: merge_dict}

        Raises:
            JobStatsStoreWriteException: If atomic update fails
        """
        try:
            with self.connection_manager.get_connection(database_path=self.database_path) as conn:
                conn.execute("BEGIN TRANSACTION")

                try:
                    # Build SET clauses
                    set_clauses: list[str] = []
                    params: list[Any] = []

                    # Increment fields
                    for field_name, increment_value in increments.items():
                        set_clauses.append(f"{field_name} = {field_name} + ?")
                        params.append(increment_value)

                    # Update fields
                    if updates:
                        for field_name, new_value in updates.items():
                            set_clauses.append(f"{field_name} = ?")
                            params.append(new_value)

                    # JSON merges (read, merge, write)
                    if jsonb_merges:
                        for field_name, merge_dict in jsonb_merges.items():
                            # Read current value
                            current = conn.execute(
                                f"SELECT {field_name} FROM job_stats WHERE job_run_id = ?",  # nosec B608 — field_name is an internal dict key from known schema fields, not user input
                                [job_run_id],
                            ).fetchone()

                            if current and current[0]:
                                current_dict = json.loads(current[0])
                                current_dict.update(merge_dict)
                                set_clauses.append(f"{field_name} = ?")
                                params.append(json.dumps(current_dict))
                            else:
                                set_clauses.append(f"{field_name} = ?")
                                params.append(json.dumps(merge_dict))

                    # Execute update
                    if set_clauses:
                        params.append(job_run_id)
                        sql = f"UPDATE job_stats SET {', '.join(set_clauses)} WHERE job_run_id = ?"  # nosec B608 — field_name values are internal schema keys, not user input
                        conn.execute(sql, params)

                    conn.execute("COMMIT")
                    logger.debug("Atomic update applied: job_run_id=%s", job_run_id)
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
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
            with self.connection_manager.get_connection(database_path=self.database_path, read_only=True) as conn:
                if batch_id is not None:
                    result = conn.execute(
                        """
                        SELECT * FROM node_stats
                        WHERE job_run_id = ? AND node_id = ? AND batch_id = ?
                    """,
                        [job_run_id, node_id, batch_id],
                    ).fetchone()
                else:
                    result = conn.execute(
                        """
                        SELECT * FROM node_stats
                        WHERE job_run_id = ? AND node_id = ? AND batch_id IS NULL
                    """,
                        [job_run_id, node_id],
                    ).fetchone()

                if result is None:
                    return None

                columns = [desc[0] for desc in conn.description]
                data = dict(zip(columns, result, strict=False))

                # Parse JSON fields
                for field in [
                    "col_names",
                    "total_docs",
                    "failed_docs",
                    "skipped_docs",
                    "docs_completed",
                    "node_metadata",
                ]:
                    if data.get(field):
                        data[field] = json.loads(data[field])

                # Remove auto-increment id and job_run_id; map node_id -> id
                data.pop("id", None)
                data.pop("job_run_id", None)
                data["id"] = data.pop("node_id")

                return NodeStats(**data)
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

        DuckDB CASCADE delete handles node_stats automatically.

        Args:
            job_run_id: Job run identifier

        Raises:
            JobStatsStoreDeleteException: If job_run_id not found or deletion fails
        """
        try:
            with self.connection_manager.get_connection(database_path=self.database_path) as conn:
                # Check if exists
                exists = conn.execute("SELECT 1 FROM job_stats WHERE job_run_id = ?", [job_run_id]).fetchone()

                if not exists:
                    raise JobStatsStoreDeleteException(
                        message=f"Job run not found: {job_run_id}", job_run_id=job_run_id
                    )

                # Delete (CASCADE will handle node_stats)
                conn.execute("DELETE FROM job_stats WHERE job_run_id = ?", [job_run_id])

                logger.info("Deleted job stats: job_run_id=%s", job_run_id)
        except JobStatsStoreDeleteException:
            raise
        except Exception as e:
            logger.error("Failed to delete job stats: %s", e)
            raise JobStatsStoreDeleteException(message=f"Failed to delete job stats: {e}", job_run_id=job_run_id) from e

    @staticmethod
    def _job_run_where_sql(
        *,
        job_id: str | None,
        job_ids: list[str] | None,
        status: ExecutionStatus | str | None,
    ) -> tuple[str, list[Any]]:
        where_clauses: list[str] = []
        params: list[Any] = []

        if job_id:
            where_clauses.append("job_id = ?")
            params.append(job_id)

        if job_ids:
            placeholders = ", ".join("?" * len(job_ids))
            where_clauses.append(f"job_id IN ({placeholders})")
            params.extend(job_ids)

        if status:
            status_value = status.value if isinstance(status, ExecutionStatus) else status
            where_clauses.append("status = ?")
            params.append(status_value)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        return where_sql, params

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
            with self.connection_manager.get_connection(database_path=self.database_path, read_only=True) as conn:
                where_sql, params = self._job_run_where_sql(job_id=job_id, job_ids=job_ids, status=status)

                sql = f"""
                    SELECT * FROM job_stats
                    {where_sql}
                    ORDER BY start_time DESC
                    LIMIT ?
                """  # nosec B608 — where_sql is built from parameterised clauses with no user-controlled identifiers
                params.append(limit)

                results = conn.execute(sql, params).fetchall()

                job_stats_list = []
                columns = [desc[0] for desc in conn.description]

                for result in results:
                    data = dict(zip(columns, result, strict=False))

                    # Parse JSON fields
                    if data.get("page_type_stats"):
                        data["page_type_stats"] = json.loads(data["page_type_stats"])
                    if data.get("user_entitlements"):
                        data["user_entitlements"] = json.loads(data["user_entitlements"])

                    job_stats_list.append(JobStats(**data))

                return job_stats_list
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
            with self.connection_manager.get_connection(database_path=self.database_path, read_only=True) as conn:
                where_sql, params = self._job_run_where_sql(job_id=job_id, job_ids=job_ids, status=status)
                sql = f"SELECT COUNT(*) FROM job_stats {where_sql}"  # nosec B608 — where_sql is parameterised clauses only
                row = conn.execute(sql, params).fetchone()
                return int(row[0]) if row else 0
        except Exception as e:
            logger.error("Failed to count jobs: %s", e)
            raise JobStatsStoreReadException(
                message=f"Failed to count jobs: {e}", job_run_id=None, operation="count_job_runs"
            ) from e
