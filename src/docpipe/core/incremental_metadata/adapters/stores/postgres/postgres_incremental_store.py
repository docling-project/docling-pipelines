# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
PostgreSQL-based implementation of IncrementalMetadataStore.

Provides persistent storage for incremental metadata using PostgreSQL database,
offering ACID compliance and scalability for production environments.

Features:
- Persistent storage in PostgreSQL database
- ACID transactions for data consistency
- Advisory transaction-level locking per job with bounded lock_timeout
- Efficient querying with indexes
- Separate schema for isolation from job stats
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, cast

import psycopg2.errors
import sqlalchemy.exc
from sqlalchemy import MetaData, String, all_, any_, bindparam, delete, select, text, update
from sqlalchemy import Table as SATable
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from docpipe.core.incremental_metadata.adapters.config.incremental_metadata_factory import (
    register_incremental_update_store,
)
from docpipe.core.incremental_metadata.domain import (
    IncrementalMetadataRecord,
    IncrementalMetadataStore,
)
from docpipe.core.job_management.adapters.stores.postgres.database import (
    create_postgres_engine,
    create_session_factory,
    get_postgres_connection_string,
)
from docpipe.exceptions import (
    FlowExecutionFailedException,
    JobStatsStoreInitializationException,
    LockTimeoutError,
)
from docpipe.utils.infrastructure.logging import get_logger
from docpipe.utils.infrastructure.retry import retry_with_exponential_backoff, should_retry_on_lock_timeout

from .models import IncrementalMetadataPostgresModel

logger = get_logger("INCREMENTAL_METADATA_POSTGRES")


@register_incremental_update_store
class PostgresIncrementalMetadataStore(IncrementalMetadataStore):
    """
    PostgreSQL-based storage adapter for incremental metadata.

    Stores metadata in PostgreSQL database with separate schema:
    Schema: incremental_metadata (configurable)
    Table: inc_update_metadata

    Primary Key: (job_id, id)

    Configuration:
        Set environment variables or provide config dict:
        - DOCPIPE_POSTGRES_HOST (default: localhost)
        - DOCPIPE_POSTGRES_PORT (default: 5432)
        - DOCPIPE_POSTGRES_DB (default: docpipe)
        - DOCPIPE_POSTGRES_USER (default: docpipe_user)
        - DOCPIPE_POSTGRES_PASSWORD (required)
        - DOCPIPE_INCREMENTAL_POSTGRES_SCHEMA (default: incremental_metadata)
        - lock_timeout: lock acquisition timeout in seconds (default: 30.0)
    """

    STORE_BACKEND = "postgresql"

    def __init__(self, *, config: dict[str, Any] | None = None):
        """
        Initialize PostgreSQL incremental metadata store.

        Args:
            config: Configuration dict. May contain a nested "postgres" key (as produced
                    by the YAML config merge), or flat postgres connection keys directly.

        Raises:
            JobStatsStoreInitializationException: If initialization fails
        """
        self.config = config or {}

        # Validate and read lock_timeout (seconds, positive number)
        raw_lock_timeout = self.config.get("lock_timeout", 30.0)
        if (
            isinstance(raw_lock_timeout, bool)
            or not isinstance(raw_lock_timeout, (int, float))
            or raw_lock_timeout <= 0
        ):
            raise JobStatsStoreInitializationException(
                message=f"Invalid lock_timeout: {raw_lock_timeout!r}. Must be a positive number of seconds.",
                store_type="postgres",
            )
        self._lock_timeout_ms: int = int(raw_lock_timeout * 1000)

        # Extract flat postgres config: nested "postgres" key takes precedence
        postgres_config = self.config.get("postgres")
        flat_config = postgres_config if isinstance(postgres_config, dict) else self.config

        # Log the config keys being used (without password value)
        logger.debug("PostgresIncrementalMetadataStore config keys: %s", list(flat_config.keys()))

        # Wrap flat config in expected structure for get_postgres_connection_string
        wrapped_config = {"postgres": flat_config}

        # Get connection string from config or environment
        connection_string = get_postgres_connection_string(config=wrapped_config)
        if not connection_string:
            raise JobStatsStoreInitializationException(
                message="PostgreSQL connection not configured for incremental metadata. "
                "Set password in config or DOCPIPE_POSTGRES_PASSWORD environment variable.",
                store_type="postgres",
            )

        try:
            # Create engine and session factory
            self._engine = create_postgres_engine(connection_string=connection_string, config=wrapped_config)
            self._session_factory = create_session_factory(engine=self._engine)

            # Create schema and incremental metadata table if they don't exist.
            self.schema_name = flat_config.get("schema", "incremental_metadata")
            source_table = cast(SATable, IncrementalMetadataPostgresModel.__table__)  # type: ignore[attr-defined]
            instance_metadata = MetaData(schema=self.schema_name)
            self._table = source_table.tometadata(instance_metadata)

            bootstrap_lock_key = f"{self.schema_name}.inc_update_metadata:bootstrap"
            with self._engine.begin() as connection:
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                    {"key": bootstrap_lock_key},
                )
                connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{self.schema_name}"'))
                self._table.create(connection, checkfirst=True)

            logger.info(
                "PostgresIncrementalMetadataStore initialized successfully (schema: %s, table: %s, lock_timeout: %sms)",
                self.schema_name,
                self._table.name,
                self._lock_timeout_ms,
            )

        except JobStatsStoreInitializationException:
            raise
        except Exception as e:
            logger.error("Failed to initialize PostgresIncrementalMetadataStore: %s", e)
            raise JobStatsStoreInitializationException(
                message=f"PostgreSQL initialization failed: {e}", store_type="postgres"
            ) from e

    @staticmethod
    def _is_lock_timeout(exc: Exception) -> bool:
        """Check if an exception is a PostgreSQL lock timeout (55P03 / LockNotAvailable)."""
        if isinstance(exc, sqlalchemy.exc.OperationalError):
            orig = getattr(exc, "orig", None)
            if orig is not None:
                if getattr(orig, "pgcode", None) == "55P03":
                    return True
                if isinstance(orig, psycopg2.errors.LockNotAvailable):
                    return True
        return False

    @contextmanager
    def _write_transaction(self, *, job_id: str, operation: str) -> Generator[Connection, None, None]:
        """Execute a write operation inside an advisory-locked transaction with bounded lock_timeout.

        Sets transaction-level lock_timeout and acquires an advisory xact lock for the job.
        Maps lock timeout errors (SQLSTATE 55P03) to LockTimeoutError.
        """
        lock_key = f"{self.schema_name}.inc_update_metadata:{job_id}"
        timeout_val = f"{self._lock_timeout_ms}ms"

        try:
            with self._engine.begin() as conn:
                conn.execute(
                    text("SELECT set_config('lock_timeout', :val, true)"),
                    {"val": timeout_val},
                )
                conn.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                    {"key": lock_key},
                )
                yield conn
        except Exception as exc:
            if self._is_lock_timeout(exc):
                raise LockTimeoutError(
                    f"Lock timeout during {operation} for job_id={job_id} (timeout={self._lock_timeout_ms}ms)"
                ) from exc
            if isinstance(exc, FlowExecutionFailedException):
                raise
            raise FlowExecutionFailedException(f"Failed to {operation} for job_id={job_id}: {exc}") from exc

    def get_processed_docs(self, *, job_id: str) -> dict[str, Any]:
        """Retrieve processed document IDs with modification times and job run IDs (non-deleted only)."""
        try:
            stmt = select(
                self._table.c.id,
                self._table.c.modified_time,
                self._table.c.job_run_id,
            ).where(
                self._table.c.job_id == job_id,
                self._table.c.deleted == False,  # noqa: E712
            )
            with self._engine.connect() as conn:
                rows = conn.execute(stmt).fetchall()
                result = {row.id: {"modified_time": row.modified_time, "job_run_id": row.job_run_id} for row in rows}
                logger.debug("Retrieved %s processed docs for job_id=%s", len(result), job_id)
                return result

        except Exception as exc:
            raise FlowExecutionFailedException(f"Failed to retrieve processed docs for job_id={job_id}: {exc}") from exc

    @retry_with_exponential_backoff(
        max_retries=5, initial_delay=1, max_delay=30, retry_logic=should_retry_on_lock_timeout
    )
    def upsert_records(self, *, job_id: str, job_run_id: str, records: list[IncrementalMetadataRecord]) -> None:
        """Insert or update incremental metadata records with retry on lock timeout."""
        if not records:
            return

        # Deduplicate by doc_id (last wins) and sort by doc_id
        deduped: dict[str, IncrementalMetadataRecord] = {record.doc_id: record for record in records}
        sorted_records = sorted(deduped.values(), key=lambda r: r.doc_id)

        values = [
            {
                "job_id": job_id,
                "id": record.doc_id,
                "name": record.name,
                "modified_time": record.modified_time,
                "job_run_id": job_run_id,
                "deleted": False,
            }
            for record in sorted_records
        ]

        chunk_size = 1000
        with self._write_transaction(job_id=job_id, operation="upsert records") as conn:
            for i in range(0, len(values), chunk_size):
                chunk = values[i : i + chunk_size]
                stmt = pg_insert(self._table).values(chunk)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["job_id", "id"],
                    set_={
                        "name": stmt.excluded.name,
                        "modified_time": stmt.excluded.modified_time,
                        "job_run_id": stmt.excluded.job_run_id,
                        "deleted": stmt.excluded.deleted,
                    },
                )
                conn.execute(stmt)

        logger.info("Upserted %s records for job_id=%s", len(records), job_id)

    def get_soft_deleted_doc_ids(self, *, job_id: str) -> set[str]:
        """Retrieve document IDs marked as soft-deleted."""
        try:
            stmt = select(self._table.c.id).where(
                self._table.c.job_id == job_id,
                self._table.c.deleted == True,  # noqa: E712
            )
            with self._engine.connect() as conn:
                rows = conn.execute(stmt).scalars().all()
                result = set(rows)
                logger.debug("Retrieved %s soft-deleted docs for job_id=%s", len(result), job_id)
                return result

        except Exception as exc:
            raise FlowExecutionFailedException(
                f"Failed to retrieve soft-deleted docs for job_id={job_id}: {exc}"
            ) from exc

    def mark_missing_docs_as_deleted(self, *, job_id: str, doc_ids: list[str]) -> set[str]:
        """Mark documents as soft-deleted if not in provided list."""
        stmt = (
            update(self._table)
            .where(
                self._table.c.job_id == job_id,
                self._table.c.deleted == False,  # noqa: E712
            )
            .values(deleted=True)
            .returning(self._table.c.id)
        )
        params: dict[str, Any] = {}
        if doc_ids:
            stmt = stmt.where(self._table.c.id != all_(bindparam("doc_ids", type_=postgresql.ARRAY(String))))
            params["doc_ids"] = list(doc_ids)

        with self._write_transaction(job_id=job_id, operation="mark missing docs as deleted") as conn:
            rows = conn.execute(stmt, params).scalars().all()
            deleted_ids = set(rows)

        if deleted_ids:
            logger.info("Marked %s docs as deleted for job_id=%s", len(deleted_ids), job_id)

        return deleted_ids

    def unmark_soft_deleted_docs(self, *, job_id: str, doc_ids: list[str] | None = None) -> None:
        """Unmark soft-deleted documents, setting deleted flag back to False."""
        if doc_ids is not None and not doc_ids:
            return

        stmt = (
            update(self._table)
            .where(
                self._table.c.job_id == job_id,
                self._table.c.deleted == True,  # noqa: E712
            )
            .values(deleted=False)
        )
        params: dict[str, Any] = {}
        if doc_ids is not None:
            stmt = stmt.where(self._table.c.id == any_(bindparam("doc_ids", type_=postgresql.ARRAY(String))))
            params["doc_ids"] = list(doc_ids)

        with self._write_transaction(job_id=job_id, operation="unmark soft deleted docs") as conn:
            result = conn.execute(stmt, params)
            if result.rowcount > 0:
                logger.info("Unmarked %s soft-deleted docs for job_id=%s", result.rowcount, job_id)

    def purge_soft_deleted_docs(self, *, job_id: str) -> None:
        """Permanently delete all soft-deleted records for a given job."""
        stmt = delete(self._table).where(
            self._table.c.job_id == job_id,
            self._table.c.deleted == True,  # noqa: E712
        )
        with self._write_transaction(job_id=job_id, operation="purge soft deleted docs") as conn:
            conn.execute(stmt)

        logger.info("Purged soft-deleted records for job_id=%s", job_id)

    def delete_docs(self, *, job_id: str, doc_ids: list[str]) -> None:
        """Permanently delete metadata records for specified documents."""
        if not doc_ids:
            return

        stmt = delete(self._table).where(
            self._table.c.job_id == job_id,
            self._table.c.id == any_(bindparam("doc_ids", type_=postgresql.ARRAY(String))),
        )
        with self._write_transaction(job_id=job_id, operation="delete docs") as conn:
            conn.execute(stmt, {"doc_ids": list(doc_ids)})

        logger.info("Deleted %s docs for job_id=%s", len(doc_ids), job_id)

    def clear(self, *, job_id: str) -> None:
        """Clear all incremental metadata for a specific job."""
        stmt = delete(self._table).where(
            self._table.c.job_id == job_id,
        )
        with self._write_transaction(job_id=job_id, operation="clear metadata") as conn:
            conn.execute(stmt)

        logger.info("Cleared all metadata for job_id=%s", job_id)
