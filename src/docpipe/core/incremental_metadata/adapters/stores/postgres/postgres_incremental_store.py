# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""
PostgreSQL-based implementation of IncrementalMetadataStore.

Provides persistent storage for incremental metadata using PostgreSQL database,
offering ACID compliance and scalability for production environments.

Features:
- Persistent storage in PostgreSQL database
- ACID transactions for data consistency
- Efficient querying with indexes
- Separate schema for isolation from job stats
"""

from typing import Any, cast

from sqlalchemy import MetaData, delete, select, text, update
from sqlalchemy import Table as SATable
from sqlalchemy.dialects.postgresql import insert as pg_insert

from docpipe.core.incremental_metadata.adapters.config.incremental_metadata_factory import (
    register_incremental_update_store,
)
from docpipe.core.incremental_metadata.domain import (
    IncrementalMetadataRecord,
    IncrementalMetadataStore,
)
from docpipe.core.job_management.adapters.stores.postgres.database import (
    _postgres_settings,
    create_postgres_engine,
    create_session_factory,
    get_postgres_connection_string,
)
from docpipe.exceptions.docpipe_exceptions import (
    FlowExecutionFailedException,
    JobStatsStoreInitializationException,
)
from docpipe.utils.infrastructure.logging import get_logger

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
    """

    STORE_BACKEND = "postgres"
    STORE_BACKEND_ALIASES = ("postgresql",)

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

        # Get connection string from config or environment
        connection_string = get_postgres_connection_string(config=self.config)
        if not connection_string:
            raise JobStatsStoreInitializationException(
                message="PostgreSQL connection not configured for incremental metadata. "
                "Set password in config or DOCPIPE_POSTGRES_PASSWORD environment variable.",
                store_type="postgres",
            )

        try:
            # Create engine and session factory
            self._engine = create_postgres_engine(connection_string=connection_string, config=self.config)
            self._session_factory = create_session_factory(engine=self._engine)

            # Create schema and incremental metadata table if they don't exist.
            # We copy the SQLAlchemy Table into a per-instance MetaData with the
            # target schema so we never mutate the shared class-level __table__.
            self.schema_name = _postgres_settings(self.config).get("schema") or "incremental_metadata"
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
                "PostgresIncrementalMetadataStore initialized successfully (schema: %s, table: %s)",
                self.schema_name,
                self._table.name,
            )

        except JobStatsStoreInitializationException:
            raise
        except Exception as e:
            logger.error("Failed to initialize PostgresIncrementalMetadataStore: %s", e)
            raise JobStatsStoreInitializationException(
                message=f"PostgreSQL initialization failed: {e}", store_type="postgres"
            ) from e

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

    def upsert_records(self, *, job_id: str, job_run_id: str, records: list[IncrementalMetadataRecord]) -> None:
        """Insert or update incremental metadata records."""
        if not records:
            return

        try:
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
            with self._engine.begin() as conn:
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

        except Exception as exc:
            raise FlowExecutionFailedException(f"Failed to upsert records for job_id={job_id}: {exc}") from exc

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
        try:
            current_doc_ids = set(doc_ids)

            with self._engine.begin() as conn:
                # Get all non-deleted record ids for this job
                stmt = select(self._table.c.id).where(
                    self._table.c.job_id == job_id,
                    self._table.c.deleted == False,  # noqa: E712
                )
                rows = conn.execute(stmt).scalars().all()

                # Find documents to mark as deleted
                deleted_ids = {doc_id for doc_id in rows if doc_id not in current_doc_ids}

                if deleted_ids:
                    update_stmt = (
                        update(self._table)
                        .where(
                            self._table.c.job_id == job_id,
                            self._table.c.id.in_(list(deleted_ids)),
                        )
                        .values(deleted=True)
                    )
                    conn.execute(update_stmt)
                    logger.info("Marked %s docs as deleted for job_id=%s", len(deleted_ids), job_id)

                return deleted_ids

        except Exception as exc:
            raise FlowExecutionFailedException(
                f"Failed to mark missing docs as deleted for job_id={job_id}: {exc}"
            ) from exc

    def unmark_soft_deleted_docs(self, *, job_id: str, doc_ids: list[str] | None = None) -> None:
        """Unmark soft-deleted documents, setting deleted flag back to False."""
        if doc_ids is not None and not doc_ids:
            return
        try:
            stmt = update(self._table).where(
                self._table.c.job_id == job_id,
                self._table.c.deleted == True,  # noqa: E712
            )
            if doc_ids is not None:
                stmt = stmt.where(self._table.c.id.in_(doc_ids))

            stmt = stmt.values(deleted=False)
            with self._engine.begin() as conn:
                result = conn.execute(stmt)
                if result.rowcount > 0:
                    logger.info("Unmarked %s soft-deleted docs for job_id=%s", result.rowcount, job_id)

        except Exception as exc:
            raise FlowExecutionFailedException(
                f"Failed to unmark soft-deleted docs for job_id={job_id}: {exc}"
            ) from exc

    def purge_soft_deleted_docs(self, *, job_id: str) -> None:
        """Permanently delete all soft-deleted records for a given job."""
        try:
            stmt = delete(self._table).where(
                self._table.c.job_id == job_id,
                self._table.c.deleted == True,  # noqa: E712
            )
            with self._engine.begin() as conn:
                conn.execute(stmt)
                logger.info("Purged soft-deleted records for job_id=%s", job_id)

        except Exception as exc:
            raise FlowExecutionFailedException(f"Failed to purge soft-deleted docs for job_id={job_id}: {exc}") from exc

    def delete_docs(self, *, job_id: str, doc_ids: list[str]) -> None:
        """Permanently delete metadata records for specified documents."""
        if not doc_ids:
            return

        try:
            stmt = delete(self._table).where(
                self._table.c.job_id == job_id,
                self._table.c.id.in_(doc_ids),
            )
            with self._engine.begin() as conn:
                conn.execute(stmt)
                logger.info("Deleted %s docs for job_id=%s", len(doc_ids), job_id)

        except Exception as exc:
            raise FlowExecutionFailedException(f"Failed to delete docs for job_id={job_id}: {exc}") from exc

    def clear(self, *, job_id: str) -> None:
        """Clear all incremental metadata for a specific job."""
        try:
            stmt = delete(self._table).where(
                self._table.c.job_id == job_id,
            )
            with self._engine.begin() as conn:
                conn.execute(stmt)
                logger.info("Cleared all metadata for job_id=%s", job_id)

        except Exception as exc:
            raise FlowExecutionFailedException(f"Failed to clear metadata for job_id={job_id}: {exc}") from exc
