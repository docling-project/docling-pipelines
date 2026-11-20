# Design

## Context

See [proposal.md](proposal.md) for motivation and scope.

Current state, verified in the code:

- `FilesystemIncrementalMetadataStore` wraps all eight methods, reads included, in `filelock.FileLock` on `<base_dir>/<job_id>/inc_update_metadata/.locks/metadata.lock`. `upsert_records` retries on `Timeout` through `retry_with_exponential_backoff`.
- `PostgresIncrementalMetadataStore` runs per-record `session.get()` then `add()` in `upsert_records`, and read-diff-write in `mark_missing_docs_as_deleted`. There is no lock and no `ON CONFLICT`.
- The Postgres model has `__table_args__ = {"extend_existing": True}` with no schema. The constructor builds a schema-qualified copy of the table only to run `CREATE TABLE`. Every query then uses the unqualified `IncrementalMetadataPostgresModel`, which compiles to `FROM inc_update_metadata` (checked by compiling a `select`). The tables are created in `incremental_metadata` but queried through `search_path`, so any deployment whose `search_path` does not include that schema fails at the first query.
- `create_all`-style bootstrap (`CREATE SCHEMA IF NOT EXISTS`, then `table.create(checkfirst=True)`) is not guarded, so two replicas starting together can both pass `checkfirst` and one fails on a duplicate object.
- Callers: `IngestSourceOperator` reads processed docs once per run; `IncrementalUpdateService` upserts after each micro-batch and marks missing docs; `VectorDBOperator` reads and un-marks soft-deleted docs. Writes are per micro-batch, reads are per run, so the shared-read gain is real but modest.
- Existing Postgres patterns to reuse: `pg_advisory_xact_lock(hashtext(:key))` in `ededup_storage/adapters/postgres_store.py` and `storage/postgres/postgres_table_storage.py`.
- `filelock` is still used by four other modules, so it stays a dependency.

Layering: all changes are in `adapters/stores/`. The port in `domain/ports/incremental_metadata_store.py` and `IncrementalUpdateService` do not change.

```
IngestSourceOperator / VectorDBOperator
        |
IncrementalUpdateService  (application, unchanged)
        |  IncrementalMetadataStore (port, unchanged)
   +----+---------------------+
   |                          |
Filesystem store          Postgres store
portalocker SH / EX       pg_advisory_xact_lock(job)
per-job .lock file        + ON CONFLICT / set-based SQL
single host only          multi-replica safe
```

## Goals / Non-Goals

**Goals:**
- Shared reads and exclusive writes on the filesystem backend with no change to the on-disk layout.
- Atomic, set-based, cross-replica-safe writes on the Postgres backend.
- Identical observable behaviour across both backends (see the spec's contract requirement).

**Non-Goals:**
- A shared `LockPort` or a common lock helper. The two backends use unrelated mechanisms. A shared file-lock helper belongs to the follow-up that migrates the other four modules.
- Changing the port, the service, or any config key.
- Row-level versioning or optimistic concurrency.

## Decisions

### D1. portalocker on a separate lock file, not on the parquet file
`_write_table` writes a temp file and renames it over the parquet file, which replaces the inode. A lock held on the parquet file would then sit on the old inode, and a second process would lock the new one. The lock file is never renamed or replaced, so it stays valid.

Alternatives: lock the parquet file directly (broken by atomic replace); lock the directory (not portable on Windows).

### D2. Shared lock for reads, exclusive for writes, taken through one context manager
A private `_locked(job_id, exclusive)` context manager opens the lock file and calls `portalocker.Lock(path, flags=LOCK_SH or LOCK_EX | LOCK_NB, timeout=self._lock_timeout, check_interval=...)`. It converts `portalocker.exceptions.LockException` and `AlreadyLocked` into `FlowExecutionFailedException`. Methods that read inside a write (mark, unmark, purge, delete) take exclusive for the whole read-modify-write, because upgrading shared to exclusive can deadlock two upgraders.

Lock-file creation: the existing `_get_lock_path` calls `mkdir(parents=True)`, so it creates the job directory even for reads of unknown jobs. Keep that behaviour to avoid scope creep.

Alternatives: `fasteners.InterProcessReaderWriterLock` (extra dependency, POSIX-only); keep `filelock` (no shared mode).

### D3. Retry keyed on the new exception types
`_should_retry_on_lock_timeout` currently matches `filelock.Timeout` and a message substring. It becomes a match on a small module-level exception, `_LockTimeoutError`, raised by `_locked`, which is then wrapped into `FlowExecutionFailedException` for callers. The message substring match goes away. `upsert_records` keeps its retry policy (5 retries, 1s initial, 30s max).

### D4. Postgres: one transaction, advisory lock first
Each write method opens `engine.begin()`, runs `SELECT pg_advisory_xact_lock(hashtext(:key))` with key `"<schema>.inc_update_metadata:<job_id>"`, then runs one set-based statement. The lock is released when the transaction ends, including on rollback or a dropped connection. Reads use plain `SELECT` with no lock, relying on MVCC.

Session-scoped `pg_advisory_lock` is rejected: with a pooled engine the unlock can run on a different connection than the lock, and a crash between lock and unlock would leak the lock on a pooled connection.

`hashtext` returns a 32-bit int, so two jobs may share a lock. That costs latency, not correctness, and the spec says so. Two-key form `pg_advisory_xact_lock(int4, int4)` is not used so the keys stay consistent with the existing code.

### D5. Postgres: statements
- `upsert_records`: de-duplicate the batch by `doc_id` (last wins), sort by `doc_id`, then `INSERT ... ON CONFLICT (job_id, id) DO UPDATE SET name, modified_time, job_run_id, deleted=false`, in chunks of 1000 inside the one transaction. De-duplication is required because Postgres rejects a single `ON CONFLICT DO UPDATE` statement that touches the same key twice. Sorting gives a consistent lock order.
- `mark_missing_docs_as_deleted`: `UPDATE ... SET deleted = true WHERE job_id = :j AND deleted = false AND id <> ALL(:ids) RETURNING id`. An empty list uses no `id` predicate, so it marks everything.
- `unmark_soft_deleted_docs`, `purge_soft_deleted_docs`, `delete_docs`, `clear`: one `UPDATE` or `DELETE` each. `delete_docs` also fixes the filter to use the table's `id` column consistently.
- Large `doc_ids` lists for `<> ALL` and `IN` are passed as one array bind parameter, not expanded, so statement size stays flat.

Alternatives: `SELECT ... FOR UPDATE` per row (still racy for rows that do not exist yet); advisory lock only, keeping the ORM loops (correct, but slow and leaves per-row round trips).

### D6. Postgres: schema-qualified table, created under a bootstrap lock
Build the schema-qualified `Table` once in `__init__` (as the constructor already does), store it as `self._table`, and use it for every statement instead of the ORM model. Bootstrap runs in one `engine.begin()` that first takes `pg_advisory_xact_lock(hashtext("<schema>.inc_update_metadata"))`, then `CREATE SCHEMA IF NOT EXISTS` and `table.create(connection, checkfirst=True)`, the same pattern as `PostgresEdedupStore`.

The ORM model stays for column definitions and the existing tests' imports. Setting the schema at the model level is rejected: the class-level `__table__` is shared across store instances with different schemas, which is why the constructor copies it.

### D7. Postgres lock timeout
Set `SET LOCAL lock_timeout = '<n>s'` in the same transaction before taking the advisory lock, using the store's `lock_timeout` (default 120). A timeout surfaces as a `psycopg2` `LockNotAvailable`, mapped to `FlowExecutionFailedException`. `upsert_records` reuses the D3 retry policy for this error. This makes both backends honour `lock_timeout` the same way. Without it, a stuck writer would block replicas indefinitely.

### D8. Dependency
Add `portalocker` to `[project.dependencies]` in both `pyproject.toml` and `slim/pyproject.toml`, pinned like its neighbours (the resolver currently proposes `4.4.2`). Run `uv lock` and `uv pip install -e ".[dev]"`, and commit `pyproject.toml` and `uv.lock` together. The `filelock` pin and the litellm override are untouched.

## Risks / Trade-offs

- **[Intra-run concurrency is limited to batch writes]** Ingest, the missing-doc diff, and the final purge run once on the orchestrator node; only per-batch writes (`upsert_records`, and `unmark_soft_deleted_docs` from `VectorDBOperator`) run concurrently, and under the WorkPool strategy they run on other hosts. → The WorkPool strategy is the distributed path and requires the `postgresql` backend. The filesystem backend covers threads and processes on one host (ThreadPool strategy).
- **[Overlapping runs of one job_id]** Locks keep the store consistent but give no exactly-once processing: two overlapping runs of the same `job_id` can read the same snapshot and mark missing docs from different source views. No guard against overlapping runs was found in the code. → Out of scope; callers needing exclusivity must serialise runs per job. Recorded as a non-goal in the proposal.
- **[Schema qualification changes which table is read]** Deployments that relied on `search_path` including `public` and had a table created there by hand would now read the schema table, which may be empty. → Release note; the first run with an empty table behaves like a first run (full ingest). No data is dropped.
- **[Filesystem on NFS or FUSE]** `flock`/`fcntl` semantics are unreliable there. → Documented as unsupported; distributed deployments use `postgresql`.
- **[Windows]** `portalocker` uses `msvcrt`/`LockFileEx`, so shared locks work, but a held lock blocks deleting the lock file. `clear()` already removes `.locks` after releasing the lock. → Keep that order.
- **[Shared-lock starvation of writers]** A steady stream of readers can delay an exclusive request on some platforms. → Reads are short and per run; `lock_timeout` plus the upsert retry bounds the wait.
- **[hashtext collisions]** Unrelated jobs may serialise. → Latency only.
- **[Test coverage gap]** Existing Postgres tests use a mocked engine, so true concurrency and `ON CONFLICT` semantics are not exercised. → Report as a verification gap. A Postgres-backed integration test needs a decision from the maintainers about CI services; none exists today.
- **[Retry decorator on a method that is now partially applied]** Only `upsert_records` is retried, as today. Other write methods fail fast on timeout. → Unchanged behaviour.

## Migration Plan

1. Merge with no config changes. Existing parquet files and Postgres tables are used as is.
2. The Postgres bootstrap is idempotent, so rolling upgrades with old and new replicas running together are safe: old replicas keep their unlocked path, new ones lock, and `ON CONFLICT` upserts coexist with old `session.add` writes, except that two old replicas can still collide as they do today.
3. Rollback is a code revert. No schema or file-format change is involved, and the `portalocker` dependency can stay unused.
4. Deployments that spread workers across hosts should switch `incremental_metadata.storage.type` to `postgresql` before upgrading. The filesystem backend does not become less safe than before, but it will not become safer either.

## Open Questions

- Which Postgres service, if any, should CI provide for a real concurrency test? This does not change the specs or the tasks; it decides whether a follow-up test is added.
