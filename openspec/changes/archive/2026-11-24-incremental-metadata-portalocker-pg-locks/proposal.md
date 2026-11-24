# Proposal

## Why

File locking across the repository relies on `filelock`, which lacks shared/exclusive reader-writer locking support and suffers from POSIX inode unlinking races. In addition, the incremental metadata store has concurrency gaps in both backends:

- The filesystem incremental metadata store serialises all operations, including reads, behind one exclusive `filelock` per job, so concurrent micro-batches queue behind read-only calls.
- Filesystem `clear()` deletes `.locks/metadata.lock`, which breaks mutual exclusion across unlinked file inodes on POSIX.
- Filesystem `upsert_records` does not deduplicate a batch by `doc_id`, so the two backends differ when a batch repeats a key.
- Other storage adapters (`JsonJobStatsStore`, `FilesystemEdedupStore`, `LocalProjectRepository`, and `CpdParquetTableHandler`) still depend on `filelock.FileLock`, preventing complete removal of the `filelock` dependency and its litellm version pin override.
- PostgreSQL compound writes for incremental metadata are unserialised per job. `mark_missing_docs_as_deleted` reads ids and then updates them in separate statements, so it can race with concurrent upserts, unmarks and purges.
- The PostgreSQL incremental adapter does not honour `lock_timeout`, and there is no unified timeout error across backends.

## What Changes

Layers affected: **backend-only** (filesystem and PostgreSQL storage adapters, repository adapters, and utilities). No REST routes, operators contracts, frontend, BFF, or Redux state change.

- **Incremental Metadata Filesystem Store**: Replace `filelock.FileLock` with `portalocker`. Read methods take a shared lock (`LOCK_SH`), write methods take an exclusive lock (`LOCK_EX`). Single-machine execution only. Never delete `.locks/metadata.lock` in `clear()`. Deduplicate batches by `doc_id` (last wins).
- **PostgreSQL Incremental Metadata Store**: Wrap each write method in a transaction that takes `pg_advisory_xact_lock` for the job, and make multi-step writes set-based (`UPDATE ... RETURNING`, `DELETE`).
- **PostgreSQL Lock Timeout**: Read a new optional `lock_timeout` config key (seconds, default `30.0`, same key and default as the filesystem backend, whose code default changes from `120.0` to `30.0`), apply it with `set_config('lock_timeout', :value, true)`, and raise a unified `LockTimeoutError(FlowExecutionFailedException)` that unwraps driver errors, so `upsert_records` can retry.
- **Unified Error**: Define `LockTimeoutError` in `docpipe.exceptions` and share one retry predicate between both incremental stores.
- **Repository-wide `filelock` Migration**:
  - Replace `filelock` with `portalocker` in `JsonJobStatsStore` (shared locks for reads, exclusive locks for writes, converting timeouts to store exceptions).
  - Replace `filelock` with `portalocker` in `FilesystemEdedupStore`.
  - Replace `filelock` with `portalocker` in `LocalProjectRepository`.
  - Replace `filelock` with `portalocker` in `CpdParquetTableHandler` (shared locks for reading, exclusive locks for writing and deleting).
  - Clean up logger configuration (`src/docpipe/utils/infrastructure/logging.py`).
- **Dependency & Lockfile**: Add `portalocker` to `pyproject.toml` and `slim/pyproject.toml`, remove direct `filelock` dependency and litellm override, and regenerate `uv.lock` (root and `slim/`).
- **Documentation**: Document the deployment rule: distributed execution requires `postgresql`; on a single machine either `postgresql` or `filesystem` (`portalocker`) is supported, and the filesystem backend is single-host only.

## Capabilities

### New Capabilities
- `backend/incremental-metadata-store`: observable behaviour of the incremental metadata store contract: per-job record semantics, soft-delete lifecycle, and the concurrency guarantees of the filesystem and PostgreSQL backends.

### Modified Capabilities
<!-- None. No existing spec covers incremental metadata. -->

## Impact

- Code: `filesystem_incremental_store.py`, `postgres_incremental_store.py`, `json_job_stats_store.py`, `filesystem_store.py` (ededup), `local_project_repository.py`, `pyarrow_handler.py`, `logging.py`, `docpipe_exceptions.py` (`LockTimeoutError`), `docs/guides/ADVANCED_CONFIGURATION.md`.
- Dependencies: replace direct `filelock` dependency with `portalocker` in `pyproject.toml` and `slim/pyproject.toml`; remove `filelock` override.
- Tests: `tests/unit/core/incremental_metadata/`, `tests/unit/core/job_management/`, `tests/unit/common/util/test_pyarrow_handler.py`, and `tests/integration/test_postgres_incremental_metadata.py`.
- Runtime: one new optional config key, `lock_timeout` for the `postgresql` backend. The filesystem backend's `lock_timeout` keeps its meaning. `IncrementalUpdateService` and ports are unchanged.

## Non-goals

- Introducing a shared `LockPort` abstraction.
- Preventing overlapping runs of the same `job_id`. Within one run, ingest, the missing-doc diff and the purge are single-node, and only batch writes are concurrent. Locks keep the store consistent but do not give exactly-once processing across overlapping runs (see design, Risks). No existing guard against overlapping runs was found.
- Alembic migrations for the incremental metadata table.
- Supporting the filesystem backend on NFS or object-store mounts.
- Windows support for the filesystem backend. The project targets Linux and macOS.
- An atomic mark-then-read in `IncrementalUpdateService.mark_soft_deleted_docs`. The two store calls run once per run on the orchestrator, before batch writes, so no concurrent writer interleaves within a run.
