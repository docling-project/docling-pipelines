"""Edge cases of the in-memory, DuckDB and JSON job stats stores.

Each store runs for real (DuckDB file and JSON files in tmp_path). Failures are produced the way
they happen in practice: a dropped table, a value that cannot be copied, a held file lock, a file
name that is too long for the file system.
"""

import threading
from pathlib import Path

import pytest
from filelock import FileLock

from docpipe.core.constants.constants import ExecutionStatus
from docpipe.core.job_management.adapters.stores.duckdb.duckdb_job_stats_store import DuckDBJobStatsStore
from docpipe.core.job_management.adapters.stores.inmemory.inmemory_job_stats_store import InMemoryJobStatsStore
from docpipe.core.job_management.adapters.stores.json.json_job_stats_store import JsonJobStatsStore
from docpipe.core.job_management.domain.models import JobStats, NodeStats
from docpipe.exceptions.docpipe_exceptions import (
    JobStatsStoreReadException,
    JobStatsStoreWriteException,
)

RUN = "run-1"


def _job(job_run_id: str = RUN, job_id: str = "job-a", **fields) -> JobStats:
    return JobStats(job_id=job_id, job_run_id=job_run_id, **fields)


def _node(node_id: str = "node-1", batch_id: str | None = None, **fields) -> NodeStats:
    return NodeStats(id=node_id, name=node_id.title(), batch_id=batch_id, **fields)


# ---------------------------------------------------------------------------
# InMemoryJobStatsStore
# ---------------------------------------------------------------------------


class TestInMemoryStore:
    def test_values_that_cannot_be_copied_are_write_errors(self):
        store = InMemoryJobStatsStore()
        unlockable = {"lock": threading.Lock()}

        with pytest.raises(JobStatsStoreWriteException, match="Failed to store job stats"):
            store.store_job_stats(_job(user_entitlements=unlockable))
        with pytest.raises(JobStatsStoreWriteException, match="Failed to store node stats"):
            store.store_node_stats(job_run_id=RUN, node_stats=_node(node_metadata=unlockable))
        with pytest.raises(JobStatsStoreWriteException, match="Failed to bulk store node stats"):
            store.bulk_store_node_stats(job_run_id=RUN, node_stats_list=[_node(node_metadata=unlockable)])

    def test_failed_docs_for_batch(self):
        store = InMemoryJobStatsStore()
        store.bulk_store_node_stats(
            job_run_id=RUN,
            node_stats_list=[
                _node("extract", batch_id="b1", failed_docs=["d1", "d2"]),
                _node("chunk", batch_id="b1"),
                _node("embed", batch_id="b2", failed_docs=["d9"]),
            ],
        )

        assert store.get_failed_docs_for_batch(job_run_id=RUN, batch_id="b1") == ["d1", "d2"]
        assert store.get_failed_docs_for_batch(job_run_id="unknown", batch_id="b1") == []

    def test_batch_node_stats_leave_out_nodes_without_batches(self):
        store = InMemoryJobStatsStore()
        store.store_node_stats(job_run_id=RUN, node_stats=_node("ingest"))
        store.store_node_stats(job_run_id=RUN, node_stats=_node("extract", batch_id="b1"))

        assert set(store.get_batch_node_stats(job_run_id=RUN)) == {"extract"}

    def test_unknown_node_and_batch(self):
        assert (
            InMemoryJobStatsStore().get_node_stats_by_batch_and_node(job_run_id=RUN, batch_id="b1", node_id="nope")
            is None
        )

    def test_merge_into_a_non_dict_field_is_ignored(self):
        store = InMemoryJobStatsStore()
        store.store_job_stats(_job(message="started"))

        store.atomic_increment_fields(job_run_id=RUN, increments={}, jsonb_merges={"message": {"x": 1}})

        assert store.get_job_stats(RUN).message == "started"

    def test_list_filters_and_all_ids(self):
        store = InMemoryJobStatsStore()
        store.store_job_stats(_job("r1", job_id="job-a"))
        store.store_job_stats(_job("r2", job_id="job-b"))
        store.store_job_stats(_job("r3", job_id="job-c"))

        assert [j.job_run_id for j in store.list_job_runs(job_id="job-b")] == ["r2"]
        assert sorted(j.job_run_id for j in store.list_job_runs(job_ids=["job-a", "job-c"])) == ["r1", "r3"]
        assert sorted(store.get_all_job_run_ids()) == ["r1", "r2", "r3"]

    def test_job_lock_created_by_a_concurrent_caller_is_reused(self):
        """Double-checked locking: another thread registers the lock between the two checks."""
        store = InMemoryJobStatsStore()
        winner = threading.RLock()

        class _RaceLock:
            def __enter__(self):
                store._job_locks[RUN] = winner

            def __exit__(self, *exc):
                return False

        store._global_lock = _RaceLock()

        assert store._get_job_lock(job_run_id=RUN) is winner


# ---------------------------------------------------------------------------
# DuckDBJobStatsStore
# ---------------------------------------------------------------------------


@pytest.fixture
def duck(tmp_path: Path) -> DuckDBJobStatsStore:
    return DuckDBJobStatsStore(config={"database_path": str(tmp_path / "job_stats.duckdb")})


def _drop(store: DuckDBJobStatsStore, table: str) -> None:
    """Drop a table (node_stats references job_stats, so it has to go first)."""
    tables = ["node_stats", "job_stats"] if table == "job_stats" else [table]
    with store.connection_manager.get_connection(database_path=store.database_path) as conn:
        for name in tables:
            conn.execute(f"DROP TABLE {name}")  # nosec B608 - fixed test table names


class TestDuckDBStore:
    def test_storing_a_node_twice_updates_it(self, duck):
        duck.store_job_stats(_job())
        duck.store_node_stats(job_run_id=RUN, node_stats=_node(batch_id="b1", node_status="RUNNING"))
        duck.store_node_stats(job_run_id=RUN, node_stats=_node(batch_id="b1", node_status="COMPLETED"))

        assert [n.node_status for n in duck.get_node_stats(job_run_id=RUN)] == ["COMPLETED"]

    def test_unknown_node_and_batch(self, duck):
        assert duck.get_node_stats_by_batch_and_node(job_run_id=RUN, batch_id="b1", node_id="nope") is None

    def test_atomic_updates_and_empty_changes(self, duck):
        duck.store_job_stats(_job(processed_docs=1))

        duck.atomic_increment_fields(job_run_id=RUN, increments={"processed_docs": 2}, updates={"message": "busy"})
        duck.atomic_increment_fields(job_run_id=RUN, increments={})

        stats = duck.get_job_stats(RUN)
        assert (stats.processed_docs, stats.message) == (3, "busy")

    def test_atomic_update_of_an_unknown_column_is_rolled_back(self, duck):
        duck.store_job_stats(_job(processed_docs=1))

        with pytest.raises(JobStatsStoreWriteException, match="Failed to atomically increment fields"):
            duck.atomic_increment_fields(job_run_id=RUN, increments={"processed_docs": 5, "no_such_column": 1})

        assert duck.get_job_stats(RUN).processed_docs == 1

    def test_list_filters_and_json_fields(self, duck):
        duck.store_job_stats(_job("r1", job_id="job-a", page_type_stats={"text": 2}, user_entitlements={"role": "x"}))
        duck.store_job_stats(_job("r2", job_id="job-b", user_entitlements={}))
        duck.store_job_stats(_job("r3", job_id="job-c", user_entitlements=None))

        by_id = duck.list_job_runs(job_id="job-a")
        by_ids = duck.list_job_runs(job_ids=["job-b", "job-c"])

        assert [(j.job_run_id, j.page_type_stats, j.user_entitlements) for j in by_id] == [
            ("r1", {"text": 2}, {"role": "x"})
        ]
        assert sorted(j.job_run_id for j in by_ids) == ["r2", "r3"]
        assert duck.get_job_stats("r1").user_entitlements == {"role": "x"}
        assert duck.get_job_stats("r3").user_entitlements is None

    def test_bulk_store_round_trips_filled_and_empty_list_fields(self, duck):
        duck.store_job_stats(_job())
        duck.bulk_store_node_stats(
            job_run_id=RUN,
            node_stats_list=[_node(batch_id="b1", failed_docs=["d1"]), _node("n2", batch_id="b1")],
        )

        assert {n.id: n.failed_docs for n in duck.get_node_stats(job_run_id=RUN)} == {"node-1": ["d1"], "n2": []}

    @pytest.mark.parametrize(
        ("table", "call", "error", "message"),
        [
            (
                "job_stats",
                lambda s: s.store_job_stats(_job()),
                JobStatsStoreWriteException,
                "Failed to store job stats",
            ),
            ("job_stats", lambda s: s.get_job_stats(RUN), JobStatsStoreReadException, "Failed to get job stats"),
            ("job_stats", lambda s: s.list_job_runs(), JobStatsStoreReadException, "Failed to list jobs"),
            (
                "node_stats",
                lambda s: s.store_node_stats(job_run_id=RUN, node_stats=_node()),
                JobStatsStoreWriteException,
                "Failed to store node stats",
            ),
            (
                "node_stats",
                lambda s: s.get_node_stats(job_run_id=RUN),
                JobStatsStoreReadException,
                "Failed to get node stats",
            ),
            (
                "node_stats",
                lambda s: s.get_batch_node_stats(job_run_id=RUN),
                JobStatsStoreReadException,
                "Failed to get batch node stats",
            ),
            (
                "node_stats",
                lambda s: s.get_node_stats_by_batch_and_node(job_run_id=RUN, batch_id="b1", node_id="n"),
                JobStatsStoreReadException,
                "Failed to get node stats by batch and node",
            ),
            (
                "node_stats",
                lambda s: s.bulk_store_node_stats(job_run_id=RUN, node_stats_list=[_node(batch_id="b1")]),
                JobStatsStoreWriteException,
                "Failed to bulk store node stats",
            ),
        ],
        ids=[
            "store-job",
            "get-job",
            "list-jobs",
            "store-node",
            "get-nodes",
            "get-batch-nodes",
            "get-node-by-batch",
            "bulk-store-nodes",
        ],
    )
    def test_database_errors_are_wrapped(self, duck, table, call, error, message):
        _drop(duck, table)

        with pytest.raises(error, match=message):
            call(duck)


# ---------------------------------------------------------------------------
# JsonJobStatsStore
# ---------------------------------------------------------------------------


@pytest.fixture
def json_store(tmp_path: Path) -> JsonJobStatsStore:
    return JsonJobStatsStore(base_dir=tmp_path / "job_stats", lock_timeout=0.05)


class TestJsonStore:
    def test_read_times_out_while_another_process_holds_the_lock(self, json_store):
        lock_path = json_store._get_job_stats_lock_path(job_run_id=RUN)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        holder = FileLock(str(lock_path))

        with holder, pytest.raises(JobStatsStoreReadException, match="Failed to acquire lock for job stats read"):
            json_store.get_job_stats(RUN)

    def test_failed_rename_is_a_write_error_and_removes_the_temp_file(self, json_store):
        # A directory where the node stats file belongs: the temp file is written,
        # but replacing the directory with it fails on every platform.
        target = json_store._get_node_stats_path(job_run_id=RUN, node_id="node-1")
        (target / "occupied").mkdir(parents=True)

        with pytest.raises(JobStatsStoreWriteException, match="Failed to write JSON file"):
            json_store.store_node_stats(job_run_id=RUN, node_stats=_node())

        assert target.is_dir()
        assert list(json_store._get_node_stats_dir(job_run_id=RUN).glob("*.tmp")) == []

    def test_unopenable_file_name_is_a_write_error(self, json_store):
        # A NUL character makes open() fail on every platform before the temp file exists.
        with pytest.raises(JobStatsStoreWriteException, match="Failed to write JSON file"):
            json_store.store_node_stats(job_run_id=RUN, node_stats=_node("bad" + chr(0) + "id"))

        assert list(json_store._get_node_stats_dir(job_run_id=RUN).iterdir()) == []

    def test_empty_node_files_are_skipped(self, json_store):
        json_store.store_node_stats(job_run_id=RUN, node_stats=_node(batch_id="b1"))
        (json_store._get_node_stats_dir(job_run_id=RUN) / "empty_file.json").write_text("{}", encoding="utf-8")

        assert [n.id for n in json_store.get_node_stats(job_run_id=RUN)] == ["node-1"]
        assert list(json_store.get_batch_node_stats(job_run_id=RUN)) == ["node-1"]

    def test_batch_node_stats_skip_non_batch_nodes_with_underscores(self, json_store):
        json_store.store_node_stats(job_run_id=RUN, node_stats=_node("my_node"))
        json_store.store_node_stats(job_run_id=RUN, node_stats=_node("extract", batch_id="b1"))

        assert list(json_store.get_batch_node_stats(job_run_id=RUN)) == ["extract"]

    def test_merge_into_a_non_dict_field_is_ignored(self, json_store):
        json_store.store_job_stats(_job(message="started", status=ExecutionStatus.RUNNING))

        json_store.atomic_increment_fields(job_run_id=RUN, increments={}, jsonb_merges={"message": {"x": 1}})

        assert json_store.get_job_stats(RUN).message == "started"
