# SPDX-FileCopyrightText: The Docling-pipeline Contributors
# SPDX-License-Identifier: MIT

"""Real PostgreSQL admissions, including independent worker processes.

Uses the shared PostgreSQL fixtures from ``tests/integration/conftest.py``, so the
DOCPIPE_TEST_POSTGRES_* variables select an expendable database. Tests create a
unique schema and remove only that schema during teardown.
"""

import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from unittest.mock import patch

import pytest
from sqlalchemy import event, inspect, select

from docpipe.core.operators.quality.ededup_storage.adapters.postgres_store import PostgresEdedupStore
from docpipe.exceptions.docpipe_exceptions import FlowExecutionFailedException

_MODULE = "docpipe.core.operators.quality.ededup_storage.adapters.postgres_store"
pytestmark = pytest.mark.integration


def _store(*, url, schema):
    with patch(f"{_MODULE}.get_postgres_connection_string", return_value=url):
        return PostgresEdedupStore(config={"schema": schema})


def _claim_in_process(args):
    url, schema, reverse, barrier, node, run = args
    barrier.wait(timeout=30)
    store = _store(url=url, schema=schema)
    hashes = ["shared-a", "shared-b"]
    if reverse:
        hashes.reverse()
    try:
        return store.check_and_register_hashes(
            job_id="job", node_id=node, job_run_id=run, records={h: str(reverse) for h in hashes}
        )
    finally:
        store._engine.dispose()


@pytest.fixture
def database(postgres_url, postgres_schemas):
    return postgres_url, postgres_schemas("test_ededup_")


def test_concurrent_processes_and_run_node_isolation(database):
    url, schema = database
    context = multiprocessing.get_context("spawn")
    with context.Manager() as manager:
        barrier = manager.Barrier(2)
        with ProcessPoolExecutor(max_workers=2, mp_context=context) as pool:
            results = list(
                pool.map(
                    _claim_in_process,
                    [(url, schema, False, barrier, "ededup", "run-a"), (url, schema, True, barrier, "ededup", "run-a")],
                )
            )
    assert results[0].isdisjoint(results[1])
    assert results[0] | results[1] == {"shared-a", "shared-b"}

    store = _store(url=url, schema=schema)
    try:

        def claim(*, run="run-a", node="ededup", job="job", doc="renamed.txt"):
            return store.check_and_register_hashes(job_id=job, node_id=node, job_run_id=run, records={"shared-a": doc})

        assert claim() == set()
        assert claim(run="run-b") == {"shared-a"}
        assert claim() == set()  # B must not overwrite A's membership.
        assert claim(node="other-branch") == {"shared-a"}
        assert claim(job="other-job") == {"shared-a"}
        with store._engine.connect() as connection:
            row = connection.execute(
                select(store._ededup_table.c.doc_id).where(store._ededup_table.c.job_run_id == "run-b")
            ).scalar_one()
        assert row == "renamed.txt"
    finally:
        store._engine.dispose()


def test_bulk_failure_rolls_back_all_chunks(database):
    url, schema = database
    store = _store(url=url, schema=schema)
    count = 0

    def fail_second_insert(*args):
        nonlocal count
        if args[2].startswith("INSERT"):
            count += 1
            if count == 2:
                raise RuntimeError("injected second chunk failure")

    event.listen(store._engine, "before_cursor_execute", fail_second_insert)
    records = {f"hash-{index:04}": str(index) for index in range(1001)}
    try:
        with pytest.raises(FlowExecutionFailedException, match="register deduplication"):
            store.check_and_register_hashes(job_id="job", node_id="node", job_run_id="run", records=records)
        event.remove(store._engine, "before_cursor_execute", fail_second_insert)
        assert store.check_and_register_hashes(job_id="job", node_id="node", job_run_id="run", records=records) == set(
            records
        )
    finally:
        store._engine.dispose()


def test_source_deletion_does_not_delete_admissions(*, database, tmp_path):
    url, schema = database
    source = tmp_path / "old.txt"
    source.write_text("content")
    store = _store(url=url, schema=schema)
    scope = {"job_id": "job", "node_id": "node", "job_run_id": "run"}
    try:
        assert store.check_and_register_hashes(**scope, records={"hash": str(source)}) == {"hash"}
        source.unlink()
        assert store.check_and_register_hashes(**scope, records={"hash": "copy.txt"}) == set()
        assert store.check_and_register_hashes(
            job_id="job", node_id="node", job_run_id="next-run", records={"hash": "copy.txt"}
        ) == {"hash"}
    finally:
        store.close()


def test_bulk_renames_and_reopening_preserve_all_scopes(database):
    url, schema = database
    store = _store(url=url, schema=schema)
    scopes = [
        {"job_id": "job", "node_id": "branch-a", "job_run_id": "run-a"},
        {"job_id": "job", "node_id": "branch-b", "job_run_id": "run-a"},
        {"job_id": "job", "node_id": "branch-a", "job_run_id": "run-b"},
        {"job_id": "job", "node_id": "branch-b", "job_run_id": "run-b"},
        {"job_id": "other", "node_id": "branch-a", "job_run_id": "run-a"},
    ]
    try:
        assert set(store._ededup_table.columns.keys()) == {"job_id", "node_id", "job_run_id", "hash_value", "doc_id"}
        for index, scope in enumerate(scopes):
            doc = "renamed.txt" if scope["job_run_id"] == "run-b" else f"original-{index}.txt"
            assert store.check_and_register_hashes(**scope, records={"h": doc}) == {"h"}
            assert store.check_and_register_hashes(**scope, records={"h": "same-run-rename", "new": "new.txt"}) == {
                "new"
            }
        with store._engine.connect() as connection:
            before = connection.execute(select(store._ededup_table)).mappings().all()
        assert len(before) == 10
        assert all(row["doc_id"] != "same-run-rename" for row in before)
        assert {row["doc_id"] for row in before if row["hash_value"] == "h" and row["job_run_id"] == "run-b"} == {
            "renamed.txt"
        }
    finally:
        store._engine.dispose()

    for _ in range(2):
        reopened = _store(url=url, schema=schema)
        try:
            for scope in scopes:
                assert reopened.check_and_register_hashes(**scope, records={"h": "overwrite"}) == set()
            with reopened._engine.connect() as connection:
                after = connection.execute(select(reopened._ededup_table)).mappings().all()
            assert {tuple(sorted(row.items())) for row in after} == {tuple(sorted(row.items())) for row in before}
        finally:
            reopened._engine.dispose()


@pytest.mark.parametrize("second_scope", [("branch-b", "run-a"), ("branch-a", "run-b")])
def test_concurrent_processes_have_independent_branch_and_run_membership(database, second_scope):
    url, schema = database
    context = multiprocessing.get_context("spawn")
    with context.Manager() as manager:
        barrier = manager.Barrier(2)
        inputs = [
            (url, schema, False, barrier, "branch-a", "run-a"),
            (url, schema, True, barrier, *second_scope),
        ]
        with ProcessPoolExecutor(max_workers=2, mp_context=context) as pool:
            results = list(pool.map(_claim_in_process, inputs))
    assert results == [{"shared-a", "shared-b"}, {"shared-a", "shared-b"}]
    store = _store(url=url, schema=schema)
    try:
        assert (
            store.check_and_register_hashes(
                job_id="job", node_id="branch-a", job_run_id="run-a", records={"shared-a": "later"}
            )
            == set()
        )
    finally:
        store._engine.dispose()


def test_storage_initialization_is_independent(database):
    url, schema = database
    store = _store(url=url, schema=schema)
    try:
        assert inspect(store._engine).get_table_names(schema=schema) == ["hashes"]
        assert set(inspect(store._engine).get_pk_constraint("hashes", schema=schema)["constrained_columns"]) == {
            "job_id",
            "node_id",
            "job_run_id",
            "hash_value",
        }
    finally:
        store.close()
