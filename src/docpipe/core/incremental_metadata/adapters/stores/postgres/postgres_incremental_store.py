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

import hashlib
from contextlib import contextmanager
from typing import Any, cast

from sqlalchemy import MetaData, delete, text, update
from sqlalchemy import Table as SATable
from sqlmodel import select

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

        # Extract flat postgres config: nested "postgres" key takes precedence
        postgres_config = self.config.get("postgres")
        flat_config = postgres_config if isinstance(postgres_config, dict) else self.config

        # Log the config keys being used (without password value)
        logger.debug("PostgresIncrementalMetadataStore config keys: %s", list(flat_config.keys()))

        # Wrap flat config in expected structure for get_postgres_connection_string
        # The function expects config["postgres"]["password"], etc.
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

            # Create schema and incremental metadata table if they don't exist.
            # We copy the SQLAlchemy Table into a per-instance MetaData with the
            # target schema so we never mutate the shared class-level __table__.
            schema_name = flat_config.get("schema", "incremental_metadata")
            # ORM history reads/upserts and Core synchronization writes must use the same schema.
            self._session_factory = create_session_factory(
                engine=self._engine.execution_options(schema_translate_map={None: schema_name})
            )
            source_table = cast(SATable, IncrementalMetadataPostgresModel.__table__)  # type: ignore[attr-defined]
            instance_metadata = MetaData(schema=schema_name)
            incremental_table = source_table.tometadata(instance_metadata)
            self._sync_table = incremental_table

            with self._engine.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))

            incremental_table.create(self._engine, checkfirst=True)

            logger.info(
                "PostgresIncrementalMetadataStore initialized successfully (schema: %s, table: %s)",
                schema_name,
                incremental_table.name,
            )

        except JobStatsStoreInitializationException:
            raise
        except Exception as e:
            logger.error("Failed to initialize PostgresIncrementalMetadataStore: %s", e)
            raise JobStatsStoreInitializationException(
                message=f"PostgreSQL initialization failed: {e}", store_type="postgres"
            ) from e

    @contextmanager
    def synchronization_guard(self, *, job_id: str):
        """Hold an advisory lock on a dedicated connection, outside batch transactions."""
        key = int.from_bytes(hashlib.sha256(job_id.encode()).digest()[:8], "big", signed=True)
        with self._engine.connect() as connection:
            acquired = connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar()
            if not acquired:
                raise FlowExecutionFailedException("An incremental synchronization is already running for this context")
            try:
                yield
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})

    def mark_deleted_candidates(self, *, job_id: str, doc_ids: set[str]) -> None:
        """Update only explicit candidates in this scope."""
        if not doc_ids:
            return
        with self._session_factory() as session:
            ids = sorted(doc_ids)
            for offset in range(0, len(ids), 500):
                session.execute(
                    update(self._sync_table)
                    .where(self._sync_table.c.job_id == job_id, self._sync_table.c.id.in_(ids[offset : offset + 500]))
                    .values(deleted=True)
                )
            session.commit()

    def acknowledge_deletions(self, *, job_id: str, doc_ids: set[str]) -> None:
        """Conditionally delete tombstones without removing regenerated records."""
        if not doc_ids:
            return
        with self._session_factory() as session:
            ids = sorted(doc_ids)
            for offset in range(0, len(ids), 500):
                session.execute(
                    delete(self._sync_table).where(
                        self._sync_table.c.job_id == job_id,
                        self._sync_table.c.id.in_(ids[offset : offset + 500]),
                        self._sync_table.c.deleted.is_(True),
                    )
                )
            session.commit()

    def get_processed_docs(self, *, job_id: str) -> dict[str, Any]:
        """Retrieve processed document IDs with modification times and job run IDs (non-deleted only)."""
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        select(IncrementalMetadataPostgresModel).where(
                            IncrementalMetadataPostgresModel.job_id == job_id,
                            IncrementalMetadataPostgresModel.deleted == False,  # noqa: E712
                        )
                    )
                    .scalars()
                    .all()
                )
                result = {
                    row.doc_id: {"modified_time": row.modified_time, "job_run_id": row.job_run_id} for row in rows
                }
                logger.debug("Retrieved %s processed docs for job_id=%s", len(result), job_id)
                return result

        except Exception as exc:
            raise FlowExecutionFailedException(f"Failed to retrieve processed docs for job_id={job_id}: {exc}") from exc

    def upsert_records(self, *, job_id: str, job_run_id: str, records: list[IncrementalMetadataRecord]) -> None:
        """Insert or update incremental metadata records."""
        if not records:
            return

        try:
            with self._session_factory() as session:
                for record in records:
                    # Check if record exists
                    model = session.get(IncrementalMetadataPostgresModel, (job_id, record.doc_id))

                    if model is None:
                        # Insert new record
                        model = IncrementalMetadataPostgresModel(job_id=job_id, doc_id=record.doc_id)

                    # Update fields
                    model.name = record.name
                    model.modified_time = record.modified_time
                    model.job_run_id = job_run_id
                    model.deleted = False

                    session.add(model)

                session.commit()
                logger.info("Upserted %s records for job_id=%s", len(records), job_id)

        except Exception as exc:
            raise FlowExecutionFailedException(f"Failed to upsert records for job_id={job_id}: {exc}") from exc

    def get_soft_deleted_doc_ids(self, *, job_id: str) -> set[str]:
        """Retrieve document IDs marked as soft-deleted."""
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        select(IncrementalMetadataPostgresModel.doc_id).where(
                            IncrementalMetadataPostgresModel.job_id == job_id,
                            IncrementalMetadataPostgresModel.deleted == True,  # noqa: E712
                        )
                    )
                    .scalars()
                    .all()
                )
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

            with self._session_factory() as session:
                # Get all non-deleted records for this job
                rows = (
                    session.execute(
                        select(IncrementalMetadataPostgresModel).where(
                            IncrementalMetadataPostgresModel.job_id == job_id,
                            IncrementalMetadataPostgresModel.deleted == False,  # noqa: E712
                        )
                    )
                    .scalars()
                    .all()
                )

                # Find documents to mark as deleted
                deleted_ids = {row.doc_id for row in rows if row.doc_id not in current_doc_ids}

                # Mark as deleted
                for row in rows:
                    if row.doc_id in deleted_ids:
                        row.deleted = True
                        session.add(row)

                session.commit()

                if deleted_ids:
                    logger.info("Marked %s docs as deleted for job_id=%s", len(deleted_ids), job_id)

                return deleted_ids

        except Exception as exc:
            raise FlowExecutionFailedException(
                f"Failed to mark missing docs as deleted for job_id={job_id}: {exc}"
            ) from exc

    def delete_docs(self, *, job_id: str, doc_ids: list[str]) -> None:
        """Permanently delete metadata records for specified documents."""
        if not doc_ids:
            return

        try:
            with self._session_factory() as session:
                table_c = cast(SATable, IncrementalMetadataPostgresModel.__table__).c  # type: ignore[attr-defined]
                session.execute(
                    delete(IncrementalMetadataPostgresModel).where(
                        table_c.job_id == job_id,
                        table_c.id.in_(doc_ids),
                    )
                )
                session.commit()
                logger.info("Deleted %s docs for job_id=%s", len(doc_ids), job_id)

        except Exception as exc:
            raise FlowExecutionFailedException(f"Failed to delete docs for job_id={job_id}: {exc}") from exc

    def clear(self, *, job_id: str) -> None:
        """Clear all incremental metadata for a specific job."""
        try:
            with self._session_factory() as session:
                table_c = cast(SATable, IncrementalMetadataPostgresModel.__table__).c  # type: ignore[attr-defined]
                session.execute(
                    delete(IncrementalMetadataPostgresModel).where(
                        table_c.job_id == job_id,
                    )
                )
                session.commit()
                logger.info("Cleared all metadata for job_id=%s", job_id)

        except Exception as exc:
            raise FlowExecutionFailedException(f"Failed to clear metadata for job_id={job_id}: {exc}") from exc
