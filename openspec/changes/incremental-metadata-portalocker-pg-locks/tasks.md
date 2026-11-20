# Tasks

## 1. Dependency setup

- [ ] 1.1 [backend] Add `portalocker` to `[project.dependencies]` in `pyproject.toml` and `slim/pyproject.toml`, pinned to the version `uv` resolves (currently `4.4.2`). Leave the `filelock==4.2.1` pin and the litellm override untouched. Verify: both files list `portalocker==<version>` and `filelock` is unchanged.
- [ ] 1.2 [backend] Run `uv lock` in the repo root and in `slim/`, then `uv pip install -e ".[dev]"`. Verify: `uv.lock` and `slim/uv.lock` contain `portalocker`, `python -c "import portalocker"` succeeds in `.venv`, and the lock diff adds no unrelated package changes beyond `portalocker` and its own requirements.

## 2. Filesystem store: portalocker

- [ ] 2.1 [backend] In `filesystem_incremental_store.py`, replace `filelock` with `portalocker`. Add a private `_locked(job_id=..., exclusive=...)` context manager on the per-job `.locks/metadata.lock` file. It takes `LOCK_SH` for reads and `LOCK_EX` for writes, honours `lock_timeout`, and raises a module-local `_LockTimeoutError` on timeout. Verify: `grep -n filelock` on the file returns nothing and the module imports.
- [ ] 2.2 [backend] Convert the read methods (`get_processed_docs`, `get_soft_deleted_doc_ids`) to the shared lock. Convert every write method (`upsert_records`, `mark_missing_docs_as_deleted`, `unmark_soft_deleted_docs`, `purge_soft_deleted_docs`, `delete_docs`, `clear`) to the exclusive lock for the whole read-modify-write. Keep `clear()` releasing the lock before it removes `.locks`. Wrap `_LockTimeoutError` into `FlowExecutionFailedException` naming the job. Verify: existing behavioural tests in `test_filesystem_store.py` still pass.
- [ ] 2.3 [backend] Update `_should_retry_on_lock_timeout` to retry on `_LockTimeoutError` and its wrapped `FlowExecutionFailedException`, replacing the `filelock.Timeout` and message-substring match. Keep the `upsert_records` retry policy (5 retries, 1s initial, 30s max). Verify: a unit test shows `upsert_records` retries after a lock timeout and then succeeds, and fails after the retries are exhausted.
- [ ] 2.4 [backend] Add filesystem tests in `tests/unit/core/incremental_metadata/test_filesystem_store.py`. Cover: two concurrent readers do not block each other, a writer excludes readers and writers on the same job, writers on different jobs do not block, lock timeout raises `FlowExecutionFailedException`, duplicate `doc_id`s in one batch store the last record once, and `mark_missing_docs_as_deleted([])` marks all non-deleted records. Verify: `pytest tests/unit/core/incremental_metadata/test_filesystem_store.py -v` passes.

## 3. PostgreSQL store: schema, bootstrap, locking

- [ ] 3.1 [backend] In `postgres_incremental_store.py`, keep the schema-qualified `Table` copy as `self._table` and use it for every statement in place of the unqualified ORM model. Verify: a test compiles each store statement with the PostgreSQL dialect and asserts the SQL addresses `<schema>.inc_update_metadata`, for the default and a custom schema.
- [ ] 3.2 [backend] Move bootstrap into one `engine.begin()` transaction that first takes `pg_advisory_xact_lock(hashtext('<schema>.inc_update_metadata'))`, then runs `CREATE SCHEMA IF NOT EXISTS` (quoted via the dialect) and `table.create(connection, checkfirst=True)`. Dispose the engine on bootstrap failure. Verify: a test asserts the lock statement is executed before the DDL, in the same transaction.
- [ ] 3.3 [backend] Add a private write-transaction helper on the store. It opens `engine.begin()`, runs `SET LOCAL lock_timeout` from the store's `lock_timeout` (default 120s), then `SELECT pg_advisory_xact_lock(hashtext(:key))` with key `<schema>.inc_update_metadata:<job_id>`. It maps psycopg2 `LockNotAvailable` to a retryable lock-timeout error wrapped in `FlowExecutionFailedException`. Verify: tests assert the statement order and the exception mapping.

## 4. PostgreSQL store: set-based writes

- [ ] 4.1 [backend] Rewrite `upsert_records` as `INSERT ... ON CONFLICT (job_id, id) DO UPDATE SET name, modified_time, job_run_id, deleted = false`. De-duplicate the batch by `doc_id` (last wins), sort by `doc_id`, and write in chunks of 1000 inside the single locked transaction. Apply the same retry decorator as the filesystem store. Verify: tests cover an empty batch (no-op), duplicate ids in one batch, a batch larger than one chunk, and retry on lock timeout.
- [ ] 4.2 [backend] Rewrite `mark_missing_docs_as_deleted` as one `UPDATE ... SET deleted = true WHERE job_id AND deleted = false AND id <> ALL(:ids) RETURNING id`, passing ids as one array parameter. An empty list omits the `id` predicate. Verify: tests cover a normal list, an empty list marking all records, and an all-present list returning an empty set.
- [ ] 4.3 [backend] Rewrite `unmark_soft_deleted_docs`, `purge_soft_deleted_docs`, `delete_docs`, and `clear` as one `UPDATE` or `DELETE` each inside the locked transaction. `delete_docs` filters on the table's `id` column. `unmark_soft_deleted_docs` with an empty `doc_ids` list stays a no-op. Verify: tests cover each method including its empty-input and error paths.
- [ ] 4.4 [backend] Keep the read methods (`get_processed_docs`, `get_soft_deleted_doc_ids`) lock-free, but query through `self._table`. Verify: a test asserts no advisory-lock statement runs for reads and the returned shape is unchanged.
- [ ] 4.5 [backend] Rewrite the affected cases in `tests/unit/core/incremental_metadata/test_postgres_incremental_store.py` for the new statement-based flow. The old session-mock helpers no longer fit, because the writes no longer use the ORM session. Keep the init and error-wrapping cases. Verify: `pytest tests/unit/core/incremental_metadata/test_postgres_incremental_store.py -v` passes.

## 5. Documentation and validation

- [ ] 5.1 [backend] Update `docs/guides/ADVANCED_CONFIGURATION.md` (Incremental Metadata Configuration) to state three things. The filesystem backend is for single-host use only and is not supported on NFS or object-store mounts. The WorkPool strategy and any multi-host deployment must use `postgresql`. Both backends honour `lock_timeout`. Also note that the Postgres store now queries its configured schema. Verify: the new text renders and relative links resolve.
- [ ] 5.2 [backend] Run the existing incremental metadata and affected suites: `pytest tests/unit/core/incremental_metadata/ tests/unit/operators/ingest/ -v`. Verify: all pass with no new warnings.
- [ ] 5.3 [backend] Run the repository checks on the changed files: `pre-commit run --from-ref origin/main --to-ref HEAD` after committing, plus `openspec validate incremental-metadata-portalocker-pg-locks --strict`. Verify: both pass.
- [ ] 5.4 [backend] Record the verification gap in the PR description. Postgres tests use a mocked engine, so real concurrency and `ON CONFLICT` behaviour were not exercised against a live database, and overlapping runs of one `job_id` are not guarded. Verify: the gap text is present in the PR description or handoff report.

## Workflow follow-up

- Open a follow-up change to migrate `json_job_stats_store`, the ededup filesystem store, `local_project_repository`, and `pyarrow_handler` from `filelock` to `portalocker`. That change can then drop the `filelock` pin and the litellm override.
- Archive this change after review: `openspec archive incremental-metadata-portalocker-pg-locks`.
