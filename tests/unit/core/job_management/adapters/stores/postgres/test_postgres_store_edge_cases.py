"""Edge cases of the Postgres job stats store, its DALs and the database helpers.

CI has no PostgreSQL server and the models use JSONB/ARRAY columns, so SQLite cannot stand in.
The tests therefore follow the existing pattern (real DAL and BaseDAO over a mocked session,
statements compiled with the PostgreSQL dialect), and use real engines where no server is
needed: an SQLite engine for the pool settings, an unreachable port for connection failures,
and real Alembic for a migration environment that exits.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from docpipe.core.job_management.adapters.stores.postgres import database
from docpipe.core.job_management.adapters.stores.postgres.dal.base_dao import BaseDAO
from docpipe.core.job_management.adapters.stores.postgres.dal.job_stats_dal import JobStatsDAL
from docpipe.core.job_management.adapters.stores.postgres.models import JobStatsModel, NodeStatsModel
from docpipe.core.job_management.adapters.stores.postgres.postgres_job_stats_store import PostgresJobStatsStore
from docpipe.exceptions.docpipe_exceptions import (
    DatabaseMigrationException,
    JobStatsStoreInitializationException,
    PostgresConnectionException,
    PostgresOperationException,
)

# Nothing listens on port 1, so a connection is refused immediately
_UNREACHABLE = {
    "host": "127.0.0.1",
    "port": 1,
    "database": "jobs",
    "user": "docpipe",
    "password": "secret",  # pragma: allowlist secret
}


def _sql(statement) -> str:
    """PostgreSQL SQL for a statement, without the configurable schema qualifier."""
    return str(statement.compile(dialect=postgresql.dialect())).replace("docpipe_oss.", "")


def _node_row(node_id: str, batch_id: str | None) -> NodeStatsModel:
    return NodeStatsModel(
        node_id=node_id,
        name=node_id.title(),
        job_run_id="run-1",
        batch_id=batch_id,
        node_status="COMPLETED",
        start_time=1,
        end_time=2,
        time_taken=1,
        error="",
    )


# ---------------------------------------------------------------------------
# database.py
# ---------------------------------------------------------------------------


class TestDatabaseHelpers:
    def test_engine_uses_the_configured_pool_settings(self, tmp_path):
        config = {"postgres": {"pool_size": 3, "max_overflow": 4, "pool_timeout": 7}}

        engine = database.create_postgres_engine(connection_string=f"sqlite:///{tmp_path / 'db.sqlite'}", config=config)

        try:
            assert (engine.pool.size(), engine.pool._max_overflow, engine.pool._timeout) == (3, 4, 7)
            session = database.create_session_factory(engine=engine)()
            assert session.bind is engine
            session.close()
        finally:
            engine.dispose()

    def test_unreachable_server_is_a_connection_error(self):
        url = "postgresql+psycopg2://docpipe:secret@127.0.0.1:1/jobs"  # pragma: allowlist secret

        with pytest.raises(PostgresConnectionException, match="PostgreSQL engine creation failed") as exc:
            database.create_postgres_engine(connection_string=url, config={"postgres": _UNREACHABLE})

        assert (exc.value.host, exc.value.database) == ("127.0.0.1", "jobs")

    def test_migration_environment_that_exits_is_a_migration_error(self, tmp_path, monkeypatch):
        migrations = tmp_path / "migrations"
        (migrations / "versions").mkdir(parents=True)
        (migrations / "env.py").write_text("import sys\n\nsys.exit(3)\n", encoding="utf-8")
        monkeypatch.setattr(database, "MIGRATIONS_DIR", migrations)

        with pytest.raises(DatabaseMigrationException, match="exited unexpectedly with code 3"):
            database.run_migrations(connection_string=f"sqlite:///{tmp_path / 'db.sqlite'}")


# ---------------------------------------------------------------------------
# PostgresJobStatsStore
# ---------------------------------------------------------------------------


class _NodeStatsDAL:
    """Stands in for NodeStatsDAL and returns real NodeStatsModel rows."""

    def __init__(self, rows: list[NodeStatsModel]) -> None:
        self.rows = rows

    def get_all_node_stats(self, *, job_run_id: str) -> list[NodeStatsModel]:
        return self.rows

    def get_batch_node_stats(self, *, job_run_id: str) -> list[NodeStatsModel]:
        return self.rows

    def get_node_stats_by_run_batch(self, *, node_id: str, job_run_id: str, batch_id: str | None):
        return next((r for r in self.rows if r.node_id == node_id and r.batch_id == batch_id), None)


def _store(rows: list[NodeStatsModel]) -> PostgresJobStatsStore:
    store = PostgresJobStatsStore(session_factory=MagicMock())
    store._node_stats_dal = _NodeStatsDAL(rows)
    return store


class TestPostgresJobStatsStore:
    def test_unreachable_server_fails_initialisation(self):
        with pytest.raises(JobStatsStoreInitializationException, match="PostgreSQL initialization failed"):
            PostgresJobStatsStore(config={"postgres": _UNREACHABLE})

    def test_node_stats_are_mapped_to_the_domain_model(self):
        store = _store([_node_row("extract", None), _node_row("chunk", "b1")])

        nodes = store.get_node_stats(job_run_id="run-1")

        assert [(n.id, n.name, n.batch_id) for n in nodes] == [("extract", "Extract", None), ("chunk", "Chunk", "b1")]

    def test_batch_node_stats_group_by_node_and_skip_rows_without_batch(self):
        store = _store([_node_row("extract", "b1"), _node_row("extract", "b2"), _node_row("ingest", None)])

        batches = store.get_batch_node_stats(job_run_id="run-1")

        assert {node: sorted(by_batch) for node, by_batch in batches.items()} == {"extract": ["b1", "b2"]}

    def test_node_stats_by_batch_and_node(self):
        store = _store([_node_row("extract", "b1")])

        found = store.get_node_stats_by_batch_and_node(job_run_id="run-1", batch_id="b1", node_id="extract")

        assert (found.id, found.batch_id) == ("extract", "b1")


# ---------------------------------------------------------------------------
# BaseDAO
# ---------------------------------------------------------------------------


def _dao(model: Any = NodeStatsModel) -> tuple[BaseDAO, MagicMock]:
    session = MagicMock()
    return BaseDAO(model=model, session_factory=lambda: session), session


class TestBaseDAO:
    def test_upsert_values_keep_explicit_ids(self):
        dao, _ = _dao()
        rows = [_node_row("a", "b1"), _node_row("b", "b1")]
        rows[0].id, rows[1].id = 10, 11

        values = dao._build_upsert_values(objs=rows, index_elements=["job_run_id", "node_id", "batch_id"])

        assert [v["id"] for v in values] == [10, 11]

    def test_bulk_upsert_runs_in_the_callers_session(self):
        dao, own_session = _dao()
        callers_session = MagicMock()

        dao.bulk_upsert_with_conflict(
            objs=[_node_row("a", "b1")],
            index_elements=["job_run_id", "node_id", "batch_id"],
            update_fields=["node_status"],
            session=callers_session,
        )

        assert "ON CONFLICT (job_run_id, node_id, batch_id) DO UPDATE" in _sql(
            callers_session.execute.call_args.args[0]
        )
        own_session.execute.assert_not_called()
        callers_session.commit.assert_not_called()

    def test_atomic_update_sets_plain_fields(self):
        dao, session = _dao(JobStatsModel)

        dao.atomic_increment_fields(
            condition=JobStatsModel.job_run_id == "run-1", increments={}, updates={"message": "done"}
        )

        statement = session.execute.call_args.args[0]
        assert _sql(statement).startswith("UPDATE job_run_stats SET message=")
        assert statement.compile().params["message"] == "done"


# ---------------------------------------------------------------------------
# JobStatsDAL
# ---------------------------------------------------------------------------


def _dal() -> tuple[JobStatsDAL, MagicMock]:
    session = MagicMock()
    return JobStatsDAL(session_factory=lambda: session), session


class TestJobStatsDAL:
    def test_operations_go_through_the_session(self):
        dal, session = _dal()
        session.get.return_value = "row"
        session.execute.return_value.rowcount = 1
        stats = JobStatsModel(job_id="job-a", job_run_id="run-1")

        dal.upsert(job_run_stats=stats)
        assert dal.get_by_job_run_id(job_run_id="run-1") == "row"
        assert dal.delete_job_stats(job_run_id="run-1") == 1
        dal.atomic_increment_fields(job_run_id="run-1", increments={"processed_docs": 2})

        session.merge.assert_called_once_with(stats)
        session.get.assert_called_once_with(JobStatsModel, "run-1")
        statements = [_sql(c.args[0]) for c in session.execute.call_args_list]
        assert statements[0].startswith("DELETE FROM job_run_stats WHERE job_run_stats.job_run_id =")
        assert statements[1].startswith(
            "UPDATE job_run_stats SET processed_docs=(coalesce(job_run_stats.processed_docs"
        )

    @pytest.mark.parametrize(
        ("filters", "where"),
        [
            ({}, ""),
            (
                {"job_id": "job-a", "job_ids": ["job-a", "job-b"], "status": "RUNNING"},
                "WHERE job_run_stats.job_id = %(job_id_1)s AND job_run_stats.job_id IN "
                "(__[POSTCOMPILE_job_id_2]) AND job_run_stats.status = %(status_1)s ",
            ),
        ],
        ids=["no-filters", "all-filters"],
    )
    def test_list_job_runs_builds_the_query(self, filters, where):
        dal, session = _dal()
        session.execute.return_value.scalars.return_value.all.return_value = ["r1"]

        assert dal.list_job_runs(limit=5, **filters) == ["r1"]

        sql = _sql(session.execute.call_args.args[0])
        assert sql.endswith(f"{where}ORDER BY job_run_stats.start_time DESC \n LIMIT %(param_1)s".lstrip())

    @pytest.mark.parametrize(
        ("call", "message", "operation"),
        [
            (
                lambda d: d.upsert(job_run_stats=JobStatsModel(job_id="j", job_run_id="r")),
                "upsert job run stats",
                "upsert",
            ),
            (lambda d: d.get_by_job_run_id(job_run_id="r"), "retrieve job run stats for r", "get_by_id"),
            (lambda d: d.delete_job_stats(job_run_id="r"), "delete job run stats for r", "delete"),
            (
                lambda d: d.atomic_increment_fields(job_run_id="r", increments={"processed_docs": 1}),
                "atomically increment fields for r",
                "atomic_increment",
            ),
            (lambda d: d.list_job_runs(), "list jobs", "list"),
        ],
        ids=["upsert", "get", "delete", "atomic", "list"],
    )
    def test_database_errors_are_wrapped(self, call, message, operation):
        dal, session = _dal()
        for method in (session.merge, session.get, session.execute):
            method.side_effect = RuntimeError("connection reset")

        with pytest.raises(PostgresOperationException, match=f"Failed to {message}: .*connection reset") as exc:
            call(dal)

        assert exc.value.operation == operation
        session.rollback.assert_called_once()
