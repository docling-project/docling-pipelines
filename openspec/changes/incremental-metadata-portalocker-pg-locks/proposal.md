# Proposal

## Why

The incremental metadata store has concurrency gaps in both backends:

- The filesystem store serialises all operations, including reads, behind one exclusive `filelock` per job, so concurrent micro-batches queue behind read-only calls.
- Filesystem `clear()` deletes `.locks/metadata.lock`, which breaks mutual exclusion across unlinked file inodes on POSIX.
- Filesystem `upsert_records` does not deduplicate a batch by `doc_id`, so the two backends differ when a batch repeats a key.
- PostgreSQL compound writes are unserialised per job. `mark_missing_docs_as_deleted` reads ids and then updates them in separate statements, so it can race with concurrent upserts, unmarks and purges.
- The PostgreSQL adapter does not honour `lock_timeout`, and there is no unified timeout error across backends.

## What Changes

Layers affected: **backend-only** (storage adapters under `src/docpipe/core/incremental_metadata/`, one dependency). No REST routes, operators, frontend, BFF, or Redux state change.

- Filesystem adapter: replace `filelock.FileLock` with `portalocker`. Read methods take a shared lock (`LOCK_SH`), write methods take an exclusive lock (`LOCK_EX`). Single-machine execution only. Never delete `.locks/metadata.lock` in `clear()`. Deduplicate batches by `doc_id` (last wins).
- PostgreSQL adapter: wrap each write method in a transaction that takes `pg_advisory_xact_lock` for the job, and make the multi-step writes set-based (`UPDATE ... RETURNING`, `DELETE`).
- PostgreSQL adapter: read a new optional `lock_timeout` config key (seconds, default `30.0`, same key and default as the filesystem backend, whose code default changes from `120.0` to `30.0`), apply it with `set_config('lock_timeout', :value, true)`, and raise a unified `LockTimeoutError(FlowExecutionFailedException)` that unwraps driver errors, so `upsert_records` can retry.
- Define `LockTimeoutError` in `docpipe.exceptions` and share one retry predicate between both stores.
- Add `portalocker` to `pyproject.toml` and regenerate `uv.lock` (root and `slim/`).
- Document the deployment rule: distributed execution requires `postgresql`; on a single machine either `postgresql` or `filesystem` (`portalocker`) is supported, and the filesystem backend is single-host only.

## Capabilities

### New Capabilities
- `backend/incremental-metadata-store`: observable behaviour of the incremental metadata store contract: per-job record semantics, soft-delete lifecycle, and the concurrency guarantees of the filesystem and PostgreSQL backends.

### Modified Capabilities
<!-- None. No existing spec covers incremental metadata. -->

## Impact

- Code: `filesystem_incremental_store.py`, `postgres_incremental_store.py`, a small shared retry-predicate module under `adapters/stores/`, `src/docpipe/exceptions/docpipe_exceptions.py` (`LockTimeoutError`), `docs/guides/ADVANCED_CONFIGURATION.md`.
- Dependencies: new `portalocker`; `filelock` stays because four other modules still use it.
- Tests: `tests/unit/core/incremental_metadata/` (filesystem and Postgres store tests) and `tests/integration/test_postgres_incremental_metadata.py`.
- Runtime: one new optional config key, `lock_timeout` for the `postgresql` backend. The filesystem backend's `lock_timeout` keeps its meaning. `IncrementalUpdateService` and the port are unchanged.

## Non-goals

- Migrating `json_job_stats_store`, the ededup filesystem store, `local_project_repository`, or `pyarrow_handler` off `filelock`. That is a separate follow-up change, and the `filelock` pin and litellm override stay until then.
- Introducing a shared `LockPort` abstraction.
- Preventing overlapping runs of the same `job_id`. Within one run, ingest, the missing-doc diff and the purge are single-node, and only batch writes are concurrent. Locks keep the store consistent but do not give exactly-once processing across overlapping runs (see design, Risks). No existing guard against overlapping runs was found.
- Alembic migrations for the incremental metadata table.
- Supporting the filesystem backend on NFS or object-store mounts.
- Windows support for the filesystem backend. The project targets Linux and macOS.
- An atomic mark-then-read in `IncrementalUpdateService.mark_soft_deleted_docs`. The two store calls run once per run on the orchestrator, before batch writes, so no concurrent writer interleaves within a run.
