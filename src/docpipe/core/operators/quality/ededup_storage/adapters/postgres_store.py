"""Atomic PostgreSQL deduplication admissions."""

from typing import Any, cast

from sqlalchemy import MetaData, Table, text
from sqlalchemy.dialects.postgresql import insert

from docpipe.core.job_management.adapters.stores.postgres.database import (
    create_postgres_engine,
    get_postgres_connection_string,
)
from docpipe.core.operators.quality.ededup_storage.adapters.models import EdedupHashPostgresModel
from docpipe.core.operators.quality.ededup_storage.ports.ededup_store import EdedupStore
from docpipe.exceptions.docpipe_exceptions import DocpipeException, FlowExecutionFailedException


class PostgresEdedupStore(EdedupStore):
    """Own only the admission table and its transaction lifecycle."""

    def __init__(self, *, config: dict[str, Any] | None = None):
        config = config or {}
        postgres = config.get("postgres", config)
        wrapped = {"postgres": postgres}
        connection_string = get_postgres_connection_string(config=wrapped)
        if not connection_string:
            raise DocpipeException("PostgreSQL connection not configured for ededup")
        self._engine = create_postgres_engine(connection_string=connection_string, config=wrapped)
        try:
            schema = postgres.get("schema", "ededup_registry")
            metadata = MetaData(schema=schema)
            self._ededup_table = cast(Table, EdedupHashPostgresModel.__table__).to_metadata(metadata)
            with self._engine.begin() as connection:
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                    {"key": f"{schema}.hashes"},
                )
                quoted = self._engine.dialect.identifier_preparer.quote_schema(schema)
                connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {quoted}"))
                self._ededup_table.create(connection, checkfirst=True)
        except Exception:
            self._engine.dispose()
            raise

    def close(self) -> None:
        """Release connections owned by this adapter."""
        self._engine.dispose()

    def check_and_register_hashes(
        self, *, job_id: str, node_id: str, job_run_id: str, records: dict[str, str]
    ) -> set[str]:
        """Bulk admission using PostgreSQL's unique index as cross-process synchronization."""
        if not records:
            return set()
        accepted: set[str] = set()
        # Consistent lock order avoids opposite-order overlapping inserts deadlocking.
        hashes = sorted(records)
        try:
            with self._engine.begin() as connection:
                # Bound statement size while committing the entire call atomically.
                for offset in range(0, len(hashes), 1000):
                    values = [
                        {
                            "job_id": job_id,
                            "node_id": node_id,
                            "job_run_id": job_run_id,
                            "hash_value": hash_value,
                            "doc_id": records[hash_value],
                        }
                        for hash_value in hashes[offset : offset + 1000]
                    ]
                    statement = (
                        insert(self._ededup_table)
                        .values(values)
                        .on_conflict_do_nothing(index_elements=["job_id", "node_id", "job_run_id", "hash_value"])
                        .returning(self._ededup_table.c.hash_value)
                    )
                    accepted.update(connection.execute(statement).scalars().all())
            return accepted
        except Exception as exc:
            raise FlowExecutionFailedException("Failed to register deduplication hashes") from exc
