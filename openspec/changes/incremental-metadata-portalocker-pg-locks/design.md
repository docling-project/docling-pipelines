# Design

## Context

See [proposal.md](proposal.md) for motivation and scope.

Current state, verified in the code:

- `FilesystemIncrementalMetadataStore` wraps all eight methods, reads included, in `filelock.FileLock` on `<base_dir>/<job_id>/inc_update_metadata/.locks/metadata.lock`. `upsert_records` retries on `Timeout` through `retry_with_exponential_backoff`, and does not deduplicate a batch by `doc_id`. `clear()` deletes `.locks/metadata.lock` via `shutil.rmtree(locks_dir)`, which breaks POSIX file-locking guarantees (waiters on an unlinked inode collide with new callers creating a new file).
- `PostgresIncrementalMetadataStore` queries a schema-qualified `self._table`, upserts with `INSERT ... ON CONFLICT` (deduplicated by `doc_id`, chunks of 1000), and bootstraps schema and table under an advisory lock keyed `<schema>.inc_update_metadata:bootstrap`.
- `mark_missing_docs_as_deleted` selects the non-deleted ids and then updates them as two statements in one transaction with no per-job lock. No write method takes a per-job advisory lock, `lock_timeout` is not applied, and driver lock errors are wrapped into a generic `FlowExecutionFailedException`.
- Callers: `IngestSourceOperator` reads processed docs once per run; `IncrementalUpdateService.save_metadata_for_incremental_update` upserts after each micro-batch (the only per-batch concurrent write); `process_ingested_docs` marks missing docs once per run from the orchestrator; `VectorDBOperator` calls `unmark_soft_deleted_docs` job-wide only as a rollback when vector-store cleanup fails; the orchestrator purges once at flow completion. The service wraps store errors in `FlowExecutionFailedException` with `from exc`.
- Existing Postgres patterns to reuse: `pg_advisory_xact_lock(hashtext(:key))` in `ededup_storage/adapters/postgres_store.py`, `storage/postgres/postgres_table_storage.py`, and the bootstrap in `postgres_incremental_store.py`.
- `filelock` is also used across `json_job_stats_store`, `ededup_storage` filesystem store, `local_project_repository`, and `pyarrow_handler`. All of these will be migrated to `portalocker` to standardize file locking and eliminate the direct `filelock` dependency and its litellm pin override.

Layering: store changes are in `adapters/stores/`, plus a shared retry-predicate module there. `LockTimeoutError` is defined in `docpipe/exceptions/docpipe_exceptions.py` and added to its `__all__`, so adapters and callers import it from `docpipe.exceptions`. The port in `domain/ports/incremental_metadata_store.py` and `IncrementalUpdateService` do not change.

```
IngestSourceOperator / VectorDBOperator
        |
IncrementalUpdateService  (application, unchanged)
        |  IncrementalMetadataStore (port, unchanged)
   +----+---------------------+
   |                          |
Filesystem store          Postgres store
portalocker SH / EX       pg_advisory_xact_lock(job)
per-job .lock file        + set-based SQL
single host only          multi-replica safe
```

## Goals / Non-Goals

**Goals:**
- Shared reads and exclusive writes on the filesystem backend with no change to the on-disk layout.
- Cross-replica-safe, set-based writes on the Postgres backend.
- Identical observable behaviour across both backends (see the spec's contract requirement).

**Non-Goals:**
- A shared `LockPort` or a common lock helper. The two backends use unrelated mechanisms.
- Changing the domain ports or services.
- Windows support for the filesystem backend.
- Making `mark_soft_deleted_docs` (mark then read) atomic. See Risks.
- Row-level versioning or optimistic concurrency.

## Deployment modes

| Deployment | Supported backend |
|---|---|
| Distributed execution (workers on more than one host) | `postgresql` only |
| Single machine (threads and processes on one host) | `postgresql` or `filesystem` (`portalocker`) |

## Decisions

### D1. portalocker on a separate lock file, not on the parquet file
`_write_table` writes a temp file and renames it over the parquet file, which replaces the inode. A lock held on the parquet file would then sit on the old inode, and a second process would lock the new one. The lock file is never renamed or replaced, so it stays valid.

Alternatives: lock the parquet file directly (broken by atomic replace); lock the directory (not portable).

### D2. Shared lock for reads, exclusive for writes, taken through one context manager
A private `_locked(job_id, exclusive)` context manager opens the lock file and calls `portalocker.Lock(path, flags=LOCK_SH or LOCK_EX | LOCK_NB, timeout=self._lock_timeout, check_interval=...)`. It converts `portalocker.exceptions.LockException` and `AlreadyLocked` into `LockTimeoutError`, with a message naming the job and whether a read or write lock was requested. This replaces the per-method `except Timeout` blocks in all eight methods, which are removed along with the `filelock` import. Methods that read inside a write (mark, unmark, purge, delete) take exclusive for the whole read-modify-write, because upgrading shared to exclusive can deadlock two upgraders.

Lock-file creation and retention: the existing `_get_lock_path` calls `mkdir(parents=True)`. Importantly, `clear()` must NEVER remove `.locks/metadata.lock` or the `.locks/` directory. Deleting the lock file breaks POSIX mutual exclusion (a waiting process holding a lock on an unlinked inode will not coordinate with a new process creating a new inode). `clear()` only deletes the parquet data file.

Alternatives: `fasteners.InterProcessReaderWriterLock` (extra dependency, POSIX-only); keep `filelock` (no shared mode).

### D3. Unified LockTimeoutError and retry predicate
Define `LockTimeoutError(FlowExecutionFailedException)` in `docpipe/exceptions/docpipe_exceptions.py` and export it. Both stores raise it on lock acquisition timeout. One shared predicate, `should_retry_on_lock_timeout` in `utils/infrastructure/retry.py`, returns a retry for `LockTimeoutError` only. It no longer matches `filelock.Timeout` or the `"Failed to acquire write lock"` message substring. `upsert_records` keeps its retry policy (5 retries, 1s initial, 30s max) on the filesystem store and gains it on the PostgreSQL store.

When retries are exhausted, `retry_with_exponential_backoff` re-raises the original `LockTimeoutError`. `IncrementalUpdateService` wraps it in `FlowExecutionFailedException` with `from exc`, so callers see the generic error and the cause chain keeps `LockTimeoutError`. The service is not changed.

### D4. Postgres: transaction scope and advisory locks
- The `INSERT ... ON CONFLICT (job_id, id) DO UPDATE` upsert is atomic on its own and guarantees row-level correctness for concurrent upserts.
- Compound operations, specifically `mark_missing_docs_as_deleted` (which computes source differences) alongside concurrent batch upserts or unmarking/purging, require transaction-level serialisation per job.
- Each write method opens `engine.begin()`, sets `lock_timeout`, runs `SELECT pg_advisory_xact_lock(hashtext(:key))` with key `"<schema>.inc_update_metadata:<job_id>"`, and executes its statements. The lock is transaction-scoped and released on commit/rollback. Reads use plain `SELECT` with no lock, relying on MVCC. The job key is distinct from the `...:bootstrap` key.
- **Connection pool consideration**: `create_postgres_engine` defaults to `pool_size=5, max_overflow=10, pool_timeout=30`. Writers waiting on an advisory lock hold their checked-out connection. Bounding `lock_timeout` (and providing fail-fast retries) prevents `QueuePool` exhaustion under high contention.

Session-scoped `pg_advisory_lock` is rejected: with a pooled engine the unlock can run on a different connection than the lock, and a crash between lock and unlock would leak the lock on a pooled connection.

`hashtext` returns a 32-bit int, so two jobs may share a lock. That costs latency, not correctness, and the spec says so. Two-key form `pg_advisory_xact_lock(int4, int4)` is not used so the keys stay consistent with the existing code.

### D5. Set-based statements and filesystem batch deduplication
- Filesystem `upsert_records`: deduplicate the batch by `doc_id` (last wins) so both backends behave the same as the PostgreSQL store, which deduplicates.
- `mark_missing_docs_as_deleted`: `UPDATE ... SET deleted = true WHERE job_id = :j AND deleted = false AND id <> ALL(:ids) RETURNING id`. An empty list uses no `id` predicate, so it marks everything.
- `unmark_soft_deleted_docs`, `purge_soft_deleted_docs`, `delete_docs`, `clear`: keep their single `UPDATE` or `DELETE` statements, now inside the locked write transaction.
- Large `doc_ids` lists for `<> ALL` and `IN` are passed as one array bind parameter, not expanded, so statement size stays flat.

Alternatives: `SELECT ... FOR UPDATE` per row (still racy for rows that do not exist yet); advisory lock only, keeping the select-then-update loop in `mark_missing_docs_as_deleted` (correct, but leaves an extra round trip and a large `IN` list).

### D6. Postgres lock timeout and driver error unwrapping
`PostgresIncrementalMetadataStore.__init__` reads `lock_timeout` from the top level of its config dict (the same place `schema` and the filesystem store's `lock_timeout` live), defaulting to `30.0` seconds. The filesystem store's code default changes from `120.0` to `30.0` so both backends share one default, which also matches the shipped `docling-pipelines-config.yaml`. It must be a positive number, otherwise the constructor raises the existing configuration error. The store converts it to milliseconds.

Set it in the transaction before acquiring the advisory lock using `SELECT set_config('lock_timeout', :val, true)` with a bound parameter (e.g. `'30000ms'`). The setting is transaction-local, so it does not leak to other users of the pooled connection.

`lock_timeout` bounds every lock wait in the transaction, row locks taken by the DML as well as the advisory lock. A row-lock timeout is the same SQLSTATE (`55P03`) and maps to the same `LockTimeoutError`.

Because the advisory lock and the DML share one transaction, a timeout rolls the whole transaction back, including any chunks already inserted. A retry of `upsert_records` therefore starts clean and cannot double-apply a partial batch.

SQLAlchemy wraps `psycopg2.errors.LockNotAvailable` inside `sqlalchemy.exc.OperationalError`. The store catches `OperationalError`, checks `exc.orig` (e.g. `getattr(exc.orig, 'pgcode', None) == '55P03'` or `isinstance(exc.orig, psycopg2.errors.LockNotAvailable)`), and maps it to `LockTimeoutError`. `upsert_records` retries on `LockTimeoutError` with exponential backoff.

Note: with the default `lock_timeout=30s`, `upsert_records` makes up to 6 attempts (5 retries) with backoff delays of 1, 2, 4, 8 and 16 seconds, so the worst case is about 3.5 minutes before it fails. Deployments needing faster failure can configure a lower value.

### D7. Code conventions for the new helpers
The SQLSTATE-to-`LockTimeoutError` mapping and the lock-key builder do not read instance state, so they are `@staticmethod`s. `_locked` and `_write_transaction` use instance state and stay instance methods. New log statements use `%s` formatting, with no f-strings and no non-ASCII characters.

### D8. Repository-wide portalocker migration
- **JsonJobStatsStore**: Replace `FileLock` with `portalocker.Lock`. Reads (`get_job_stats`, `get_node_stats`, `get_all_node_stats`, `find_node_stats`) acquire shared locks (`portalocker.LOCK_SH`); writes (`store_job_stats`, `store_node_stats`, `delete_job_stats`, `atomic_update_job_stats`) acquire exclusive locks (`portalocker.LOCK_EX`). Lock timeouts map to existing `JobStatsStoreReadException` / `JobStatsStoreWriteException` as before.
- **FilesystemEdedupStore**: Replace `FileLock` on `hashes_<scope>.parquet.lock` with `portalocker.Lock(..., flags=portalocker.LOCK_EX, timeout=self._lock_timeout)`.
- **LocalProjectRepository**: Replace `FileLock` on `<project_id>.json.lock` with `portalocker.Lock(..., flags=portalocker.LOCK_EX, timeout=30.0)`.
- **CpdParquetTableHandler**: Replace `FileLock` on `<path>.lock` with `portalocker.Lock(..., flags=portalocker.LOCK_SH)` for `read_table` and `portalocker.LOCK_EX` for `save_table` / `delete_file`.
- **Logging**: Remove `"filelock"` suppression from `src/docpipe/utils/infrastructure/logging.py`.
- **Dependency & Lockfile**: Add `portalocker` to `[project.dependencies]` in both `pyproject.toml` and `slim/pyproject.toml`. Remove direct `filelock==4.2.12` from `dependencies` and `override-dependencies` in both files. Run `uv lock` (root and `slim/`) and `uv pip install -e ".[dev]"`.

## Risks / Trade-offs

- **[Intra-run concurrency is limited to batch upserts]** Ingest, the missing-doc mark, and the final purge run once per run on the orchestrator; `unmark_soft_deleted_docs` runs only as a job-wide rollback. Only per-batch `upsert_records` runs concurrently. The backend choice follows the deployment mode (see Deployment modes), not the write pattern.
- **[mark then read is two store calls]** `IncrementalUpdateService.mark_soft_deleted_docs` calls `mark_missing_docs_as_deleted` and then `get_soft_deleted_doc_ids`. Within one run no concurrent writer interleaves between them, because batch upserts start later. Across overlapping runs of one `job_id` it can interleave. That falls under the overlapping-runs risk below, and the port is deliberately not widened.
- **[Overlapping runs of one job_id]** Locks keep the store consistent but give no exactly-once processing: two overlapping runs of the same `job_id` can read the same snapshot and mark missing docs from different source views. No guard against overlapping runs was found in the code. Out of scope; callers needing exclusivity must serialise runs per job. Recorded as a non-goal in the proposal.
- **[Filesystem on NFS or FUSE]** `flock`/`fcntl` semantics are unreliable there. Documented as unsupported; distributed deployments use `postgresql`.
- **[Lock file retention]** Deleting `.locks/metadata.lock` in `clear()` breaks POSIX file locks. `clear()` is changed to retain `.locks/metadata.lock` and remove only the parquet data file. Windows is out of scope.
- **[Empty source listings in mark_missing_docs_as_deleted]** If a source listing returns zero documents (e.g., due to an empty mount or source glitch), `mark_missing_docs_as_deleted([])` will mark all records deleted. Documented operational risk; pipeline authors/operators should guard against unexpected empty source outputs before invoking incremental diffing.
- **[Shared-lock starvation of writers]** A steady stream of readers can delay an exclusive request on some platforms. Reads are short and per run; `lock_timeout` plus the upsert retry bounds the wait.
- **[hashtext collisions]** Unrelated jobs may serialise. Latency only.
- **[Thread-only lock tests]** `portalocker` shared and exclusive locks behave differently within one process than across processes. The filesystem tests include cross-process cases (subprocess or `multiprocessing`), not threads alone.
- **[Concurrency capacity]** No concurrency or load targets are configured for this project. The integration and cross-process tests show correctness under contention. They do not establish throughput or capacity.
- **[Live database test coverage]** Mocked engine tests cannot catch dialect-specific concurrency bugs. `tests/integration/test_postgres_incremental_metadata.py` (shared `postgres_url` fixtures, gated on `DOCPIPE_TEST_POSTGRES_PASSWORD`) covers the locking behaviour against a live PostgreSQL.
- **[Retry decorator scope]** Only `upsert_records` is retried, as today. Other write methods fail fast on timeout. Unchanged behaviour.

## Migration Plan

1. Merge. No config change is required: the new PostgreSQL `lock_timeout` key is optional with a default. Filesystem deployments that relied on the old 120 second code default (no `lock_timeout` in config) now wait 30 seconds before a lock timeout. They can set a larger value explicitly. Existing parquet files and Postgres tables are used as is.
2. Rollback is a code revert. No schema or file-format change is involved, and the `portalocker` dependency can stay unused.
3. Deployments that spread workers across hosts should switch `incremental_metadata.storage.type` to `postgresql` before upgrading. The filesystem backend is single-host only.
