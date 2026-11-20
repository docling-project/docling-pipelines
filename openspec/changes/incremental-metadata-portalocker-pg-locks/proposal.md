# Proposal

## Why

The incremental metadata store serialises every operation, including reads, behind one exclusive `filelock` per job, so concurrent micro-batches queue behind each other on read-only calls. The PostgreSQL adapter has no cross-process coordination at all: its upserts and soft-delete updates are read-then-write sequences, its DDL bootstrap is unguarded, and its queries do not target the schema it creates. None of this has produced a reported failure yet; this change hardens both backends before distributed execution depends on them.

## What Changes

Layers affected: **backend-only** (storage adapters under `src/docpipe/core/incremental_metadata/`, one dependency). No REST routes, operators, frontend, BFF, or Redux state change.

- Filesystem adapter: replace `filelock.FileLock` with `portalocker`. Read methods take a shared lock, write methods take an exclusive lock. Single-machine execution only.
- PostgreSQL adapter: every write method runs in one transaction that first takes `pg_advisory_xact_lock` for the job, then performs a single set-based statement (`INSERT ... ON CONFLICT DO UPDATE`, `UPDATE ... RETURNING`, `DELETE`). Reads stay lock-free.
- PostgreSQL adapter: qualify all queries with the configured schema, and guard schema/table creation with an advisory lock so several replicas can start together.
- PostgreSQL adapter: honour `lock_timeout` from the store config, and surface a lock timeout as a retryable error with the same retry behaviour as the filesystem adapter.
- Add `portalocker` to `pyproject.toml` and regenerate `uv.lock` (root and `slim/`).
- Document that the filesystem backend is not supported across hosts, and that distributed deployments must select `postgresql`.

## Capabilities

### New Capabilities
- `backend/incremental-metadata-store`: observable behaviour of the incremental metadata store contract: per-job record semantics, soft-delete lifecycle, and the concurrency guarantees of the filesystem and PostgreSQL backends.

### Modified Capabilities
<!-- None. No existing spec covers incremental metadata. -->

## Impact

- Code: `filesystem_incremental_store.py`, `postgres_incremental_store.py`, `models.py` (schema handling), `docs/guides/ADVANCED_CONFIGURATION.md`.
- Dependencies: new `portalocker`; `filelock` stays because four other modules still use it.
- Tests: `tests/unit/core/incremental_metadata/` (filesystem and Postgres store tests).
- Runtime: no config key changes. `lock_timeout` keeps its meaning for both backends.

## Non-goals

- Migrating `json_job_stats_store`, the ededup filesystem store, `local_project_repository`, or `pyarrow_handler` off `filelock`. That is a separate follow-up change, and the `filelock` pin and litellm override stay until then.
- Introducing a shared `LockPort` abstraction.
- Preventing overlapping runs of the same `job_id`. Within one run, ingest, the missing-doc diff and the purge are single-node, and only batch writes are concurrent. Locks keep the store consistent but do not give exactly-once processing across overlapping runs (see design, Risks). No existing guard against overlapping runs was found.
- Alembic migrations for the incremental metadata table.
- Supporting the filesystem backend on NFS or object-store mounts.
