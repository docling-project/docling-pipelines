# Design

## Context

See [proposal.md](proposal.md) for motivation and scope.

Current state, verified in the code and against live PostgreSQL 16:

- `FilesystemIncrementalMetadataStore` wraps all eight methods, reads included, in `filelock.FileLock` on `<base_dir>/<job_id>/inc_update_metadata/.locks/metadata.lock`. `upsert_records` retries on `Timeout` through `retry_with_exponential_backoff`. Furthermore, `clear()` deletes `.locks/metadata.lock` via `shutil.rmtree(locks_dir)`, which breaks POSIX file-locking guarantees (waiters on an unlinked inode collide with new callers creating a new file).
- `PostgresIncrementalMetadataStore` runs per-record `session.get()` then `add()` in `upsert_records`. Concurrent workers upserting overlapping new keys fail with `UniqueViolation on inc_update_metadata_pkey`.
- The Postgres model has `__table_args__ = {"extend_existing": True}` with no schema. The constructor builds a schema-qualified copy of the table only to run `CREATE TABLE`. Every query then uses the unqualified `IncrementalMetadataPostgresModel`, which compiles to `FROM inc_update_metadata`. The tables are created in `incremental_metadata` but queried through `search_path`. On default `search_path`, any read, write, or clear fails immediately with `UndefinedTable: relation "inc_update_metadata" does not exist`.
- `create_all`-style bootstrap (`CREATE SCHEMA IF NOT EXISTS`, then `table.create(checkfirst=True)`) is not guarded, so two replicas starting together can both pass `checkfirst` and one fails on a duplicate object.
- Callers: `IngestSourceOperator` reads processed docs once per run; `IncrementalUpdateService` upserts after each micro-batch and marks missing docs; `VectorDBOperator` reads and un-marks soft-deleted docs. Writes are per micro-batch, reads are per run.
- Existing Postgres patterns to reuse: `pg_advisory_xact_lock(hashtext(:key))` in `ededup_storage/adapters/postgres_store.py` and `storage/postgres/postgres_table_storage.py`.
- `filelock` is still used by four other modules, so it stays a dependency until a separate follow-up.

Layering: all changes are in `adapters/stores/` (plus a shared `LockTimeoutError` in domain/ports or shared exceptions). The port in `domain/ports/incremental_metadata_store.py` and `IncrementalUpdateService` do not change.

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
A private `_locked(job_id, exclusive)` context manager opens the lock file and calls `portalocker.Lock(path, flags=LOCK_SH or LOCK_EX | LOCK_NB, timeout=self._lock_timeout, check_interval=...)`. It converts `portalocker.exceptions.LockException` and `AlreadyLocked` into a dedicated `LockTimeoutError(FlowExecutionFailedException)`. Methods that read inside a write (mark, unmark, purge, delete) take exclusive for the whole read-modify-write, because upgrading shared to exclusive can deadlock two upgraders.

Lock-file creation and retention: the existing `_get_lock_path` calls `mkdir(parents=True)`. Importantly, `clear()` must NEVER remove `.locks/metadata.lock` or the `.locks/` directory. Deleting the lock file breaks POSIX mutual exclusion (a waiting process holding a lock on an unlinked inode will not coordinate with a new process creating a new inode). `clear()` only deletes the parquet data file.

Alternatives: `fasteners.InterProcessReaderWriterLock` (extra dependency, POSIX-only); keep `filelock` (no shared mode).

### D3. Unified LockTimeoutError and retry predicate
Define a dedicated `LockTimeoutError(FlowExecutionFailedException)` raised by both the filesystem store and PostgreSQL store on lock acquisition timeout. `_should_retry_on_lock_timeout` matches `LockTimeoutError` (and not generic exceptions or message substrings). `upsert_records` keeps its retry policy (5 retries, 1s initial, 30s max).

### D4. Postgres: transaction scope and advisory locks
- `INSERT ... ON CONFLICT (job_id, id) DO UPDATE` is atomic on its own and guarantees row-level correctness without table locks for simple concurrent upserts.
- Compound operations — specifically `mark_missing_docs_as_deleted` (which computes source differences) alongside concurrent batch upserts or unmarking/purging — require transaction-level serialisation per job.
- Each write method opens `engine.begin()`, optionally sets `lock_timeout`, runs `SELECT pg_advisory_xact_lock(hashtext(:key))` with key `"<schema>.inc_update_metadata:<job_id>"`, and executes its set-based statement. The lock is transaction-scoped and released on commit/rollback. Reads use plain `SELECT` with no lock, relying on MVCC.
- **Connection pool consideration**: `create_postgres_engine` defaults to `pool_size=5, max_overflow=10, pool_timeout=30`. Writers waiting on an advisory lock hold their checked-out connection. Bounding `lock_timeout` (and providing fail-fast retries) prevents `QueuePool` exhaustion under high contention.

Session-scoped `pg_advisory_lock` is rejected: with a pooled engine the unlock can run on a different connection than the lock, and a crash between lock and unlock would leak the lock on a pooled connection.

`hashtext` returns a 32-bit int, so two jobs may share a lock. That costs latency, not correctness, and the spec says so. Two-key form `pg_advisory_xact_lock(int4, int4)` is not used so the keys stay consistent with the existing code.

### D5. Postgres and Filesystem: set-based statements & batch deduplication
- `upsert_records`: de-duplicate the batch by `doc_id` (last wins) on both filesystem and PostgreSQL backends. De-duplication is required because PostgreSQL rejects a single `ON CONFLICT DO UPDATE` statement that touches the same key twice ("cannot affect row a second time"). Sorting by `doc_id` gives a consistent lock order.
- In PostgreSQL, write batches in chunks of 1000 inside the transaction: `INSERT ... ON CONFLICT (job_id, id) DO UPDATE SET name = EXCLUDED.name, modified_time = EXCLUDED.modified_time, job_run_id = EXCLUDED.job_run_id, deleted = false`.
- `mark_missing_docs_as_deleted`: `UPDATE ... SET deleted = true WHERE job_id = :j AND deleted = false AND id <> ALL(:ids) RETURNING id`. An empty list uses no `id` predicate, so it marks everything.
- `unmark_soft_deleted_docs`, `purge_soft_deleted_docs`, `delete_docs`, `clear`: one `UPDATE` or `DELETE` each. `delete_docs` also fixes the filter to use the table's `id` column consistently.
- Large `doc_ids` lists for `<> ALL` and `IN` are passed as one array bind parameter, not expanded, so statement size stays flat.

Alternatives: `SELECT ... FOR UPDATE` per row (still racy for rows that do not exist yet); advisory lock only, keeping the ORM loops (correct, but slow and leaves per-row round trips).

### D6. Postgres: schema-qualified table, created under a bootstrap lock
Build the schema-qualified `Table` once in `__init__` (as the constructor already does), store it as `self._table`, and use it for every statement instead of the ORM model. Bootstrap runs in one `engine.begin()` that first takes `pg_advisory_xact_lock(hashtext("<schema>.inc_update_metadata"))`, then `CREATE SCHEMA IF NOT EXISTS` and `table.create(connection, checkfirst=True)`, the same pattern as `PostgresEdedupStore`.

The ORM model stays for column definitions and the existing tests' imports. Setting the schema at the model level is rejected: the class-level `__table__` is shared across store instances with different schemas, which is why the constructor copies it.

### D7. Postgres lock timeout & driver error unwrapping
Set `lock_timeout` in the transaction before acquiring the advisory lock using `SELECT set_config('lock_timeout', :val, true)` with bound parameter (e.g. `'120s'`).

SQLAlchemy wraps `psycopg2.errors.LockNotAvailable` inside `sqlalchemy.exc.OperationalError`. The store catches `OperationalError`, checks `exc.orig` (e.g. `getattr(exc.orig, 'pgcode', None) == '55P03'` or `isinstance(exc.orig, psycopg2.errors.LockNotAvailable)`), and maps it to `LockTimeoutError`. `upsert_records` retries on `LockTimeoutError` with exponential backoff.

Note: with default `lock_timeout=120s` and 5 retries, worst-case wait is ~10 minutes; deployments needing fast failure can configure a lower `lock_timeout` (e.g. 10s-30s).

### D8. Dependency
Add `portalocker` to `[project.dependencies]` in both `pyproject.toml` and `slim/pyproject.toml`, pinned like its neighbours (the resolver currently proposes `4.4.2`). Run `uv lock` and `uv pip install -e ".[dev]"`, and commit `pyproject.toml` and `uv.lock` together. The `filelock` pin and the litellm override are untouched.

## Risks / Trade-offs

- **[Intra-run concurrency is limited to batch writes]** Ingest, the missing-doc diff, and the final purge run once on the orchestrator node; only per-batch writes (`upsert_records`, and `unmark_soft_deleted_docs` from `VectorDBOperator`) run concurrently, and under the WorkPool strategy they run on other hosts. → The WorkPool strategy is the distributed path and requires the `postgresql` backend. The filesystem backend covers threads and processes on one host (ThreadPool strategy).
- **[Overlapping runs of one job_id]** Locks keep the store consistent but give no exactly-once processing: two overlapping runs of the same `job_id` can read the same snapshot and mark missing docs from different source views. No guard against overlapping runs was found in the code. → Out of scope; callers needing exclusivity must serialise runs per job. Recorded as a non-goal in the proposal.
- **[Schema qualification changes which table is read]** Deployments that relied on `search_path` including `public` and had a table created there by hand would now read the schema table, which may be empty. → Release note; the first run with an empty table behaves like a first run (full ingest). No data is dropped.
- **[Filesystem on NFS or FUSE]** `flock`/`fcntl` semantics are unreliable there. → Documented as unsupported; distributed deployments use `postgresql`.
- **[Windows and POSIX lock file retention]** Deleting `.locks/metadata.lock` in `clear()` breaks POSIX and Windows file locks. → `clear()` is changed to retain `.locks/metadata.lock` and remove only the parquet data file.
- **[Empty source listings in mark_missing_docs_as_deleted]** If a source listing returns zero documents (e.g., due to an empty mount or source glitch), `mark_missing_docs_as_deleted([])` will mark all records deleted. → Documented operational risk; pipeline authors/operators should guard against unexpected empty source outputs before invoking incremental diffing.
- **[Shared-lock starvation of writers]** A steady stream of readers can delay an exclusive request on some platforms. → Reads are short and per run; `lock_timeout` plus the upsert retry bounds the wait.
- **[hashtext collisions]** Unrelated jobs may serialise. → Latency only.
- **[Live database test coverage]** Mocked engine tests cannot catch schema qualification or dialect-specific concurrency bugs. → Real PostgreSQL integration tests (run locally against Docker/Podman and in CI via `services: postgres`, gated on `DOCPIPE_POSTGRES_*` environment variables) are included as part of Phase 1.
- **[Retry decorator on a method that is now partially applied]** Only `upsert_records` is retried, as today. Other write methods fail fast on timeout. → Unchanged behaviour.

## Migration Plan

1. Merge with no config changes. Existing parquet files and Postgres tables are used as is.
2. **Rolling upgrades**: Mixed old and new replicas running simultaneously carry the risk that an old replica's read-then-add can fail with `UniqueViolation` if a new replica inserts between `get()` and `add()`. Rollouts should complete cleanly or drain workers prior to upgrading.
3. Rollback is a code revert. No schema or file-format change is involved, and the `portalocker` dependency can stay unused.
4. Deployments that spread workers across hosts should switch `incremental_metadata.storage.type` to `postgresql` before upgrading. The filesystem backend is single-host only.
