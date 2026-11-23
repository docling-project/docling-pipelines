# Proposal

## Why

The incremental metadata store has critical correctness and concurrency bugs in PostgreSQL and serialisation bottlenecks in the filesystem backend:
- The PostgreSQL adapter creates its table in the configured schema (`incremental_metadata`), but queries compile to `FROM inc_update_metadata` without schema qualification. On any standard connection where `search_path` does not include `incremental_metadata`, the first read, write, or clear fails immediately with `UndefinedTable: relation "inc_update_metadata" does not exist`.
- The PostgreSQL upsert uses non-atomic `session.get()` followed by `session.add()`. When concurrent workers insert the same new keys, they collide and fail with `UniqueViolation` on `inc_update_metadata_pkey`.
- The PostgreSQL DDL bootstrap (`CREATE SCHEMA IF NOT EXISTS` and `table.create`) is unguarded against concurrent replica startup.
- The filesystem store serialises all operations, including reads, behind one exclusive `filelock` per job, forcing concurrent micro-batches to queue behind read-only calls. Furthermore, `clear()` deletes `.locks/metadata.lock`, which breaks mutual exclusion across unlinked file inodes on POSIX.

## What Changes

Layers affected: **backend-only** (storage adapters under `src/docpipe/core/incremental_metadata/`, one dependency). No REST routes, operators, frontend, BFF, or Redux state change.

The implementation is structured into two phases:
- **Phase 1: Fix demonstrably broken PostgreSQL operations**
  - Qualify all PostgreSQL queries with the configured schema using a schema-qualified `Table`.
  - Rewrite `upsert_records` to use `INSERT ... ON CONFLICT (job_id, id) DO UPDATE`, deduplicating batches by `doc_id` (last wins).
  - Guard DDL bootstrap with `pg_advisory_xact_lock` so concurrent replicas start without race conditions.
  - Add integration tests against a live PostgreSQL database (gated on `DOCPIPE_POSTGRES_*` environment variables).
- **Phase 2: Concurrency hardening & filesystem shared locks**
  - Filesystem adapter: replace `filelock.FileLock` with `portalocker`. Read methods take a shared lock (`LOCK_SH`), write methods take an exclusive lock (`LOCK_EX`). Single-machine execution only. Never delete `.locks/metadata.lock` in `clear()`. Deduplicate batches by `doc_id` (last wins).
  - PostgreSQL adapter: wrap multi-step write methods in `pg_advisory_xact_lock` for the job with set-based SQL (`UPDATE ... RETURNING`, `DELETE`).
  - PostgreSQL adapter: honour `lock_timeout` via `set_config('lock_timeout', :value, true)` and surface a unified `LockTimeoutError(FlowExecutionFailedException)` unwrapping driver errors for retries.
  - Add `portalocker` to `pyproject.toml` and regenerate `uv.lock` (root and `slim/`).
  - Document that the filesystem backend is single-host only, and that distributed deployments must select `postgresql`.

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
