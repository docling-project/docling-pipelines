# Tasks

Each task is sized for at most two hours. Activate `.venv` before Python validation commands.
All work below implements the [incremental-update capability](specs/backend/incremental-update/spec.md),
including its source, orchestration, and VectorDB integration.

## 1. Source discovery contracts and adapters

- [x] 1.1 [backend] Reuse `fetch_documents(..., full_listing=True)` for identity-only listing with errors propagated to the flow, with
  unsupported/event-scoped behavior; verify contract tests cannot mistake capped or unsupported discovery for completion.
- [x] 1.2 [backend] Implement filesystem identity discovery before processing filters, with missing-root, subtree,
  and stat-error propagation; verify empty-root success and incomplete-walk tests in the filesystem adapter suite.
- [x] 1.3 [backend] Implement S3/IBM COS identity discovery preserving listed identities on conversion errors and
  exhausting pagination without binary reads; verify paginated fake-client tests and existing S3 tests.
- [x] 1.4 [backend] Implement streaming Google Drive discovery independent of `max_files` in synchronization mode;
  verify multi-page discovery, no full inventory arrays, no binary downloads, and unchanged limited-fetch tests.
- [x] 1.5 [backend] Implement complete Box discovery including folder pagination, without the synchronization-mode
  adapter cap; verify nested/paginated listings, error propagation, and existing limited-fetch tests.
- [x] 1.6 [backend] Implement complete Dropbox discovery independent of its synchronization-mode adapter cap;
  verify continuation pages, processing-filter presence evidence, and unchanged limited-fetch tests.
- [x] 1.7 [backend] Implement authoritative OneDrive metadata discovery with page/error completion evidence;
  verify fake-client multi-page, partial-failure, and single-file tests.
- [x] 1.8 [backend] Implement authoritative SharePoint metadata discovery with page/error completion evidence;
  verify fake-client multi-page, partial-failure, and single-file tests.
- [x] 1.9 [backend] Document supported discovery modes and incomplete/unsupported-provider behavior in existing
  source integration documentation; verify links and examples against the source contracts.

## 2. Incremental deletion lifecycle

- [x] 2.1 [backend] Extend domain ports and application services for historical/pending candidate retrieval,
  complete-scan marking, reappearance invalidation, and guarded acknowledgment; verify service tests for all transitions.
- [x] 2.2 [backend] Implement filesystem store operations without prematurely purging tombstones; verify persistence,
  reappearance outside selection, scope isolation, and all-destinations acknowledgment tests.
- [x] 2.3 [backend] Implement equivalent Postgres operations using the mapped document ID column; verify store parity
  tests, conditional deletion, and transaction rollback on acknowledgment failure.
- [x] 2.4 [backend] Add a dedicated filesystem context execution guard independent of record locks; verify two-process
  contention, independent contexts, batch metadata writes, and release after cancellation/failure.
- [x] 2.5 [backend] Add the Postgres context execution guard on a dedicated advisory-lock connection; verify contention,
  connection cleanup, and normal concurrent batch record writes in Postgres integration tests.
- [x] 2.6 [backend] Update existing incremental-processing documentation for tombstone retries and context ownership;
  verify the documented lifecycle matches service and backend parity tests.

## 3. Conditional ingestion and forced processing

- [x] 3.1 [backend] Separate presence recording from selected-row conversion using the existing source ID algorithm
  and unmatched historical candidates; verify unchanged, filtered, and beyond-limit entries never become missing.
- [x] 3.2 [backend] Wire complete discovery only with retention disabled, retain provider/loader behavior otherwise,
  and preserve typed empty output; verify both ingestion paths, selected-row schema, and metrics with fake iterators.
- [x] 3.3 [backend] Preserve comparison history with forced ingestion when retention is disabled, while bypassing
  incremental eligibility checks; verify all four flag combinations and preservation of unselected history.
- [x] 3.4 [backend] Emit explicit internal discovery evidence and scope; suppress reconciliation for failed,
  cancelled, unsupported, and file-event runs; verify existing ingestion error tests and new absence-evidence tests.
- [x] 3.5 [backend] Update `docs/reference/GLOBAL_CONFIG.md`, the ingest section of `docs/reference/OPERATORS.md`,
  and the existing ingest operator README for conditional discovery costs, filters, limits, and force behavior;
  verify examples and relative links without changing the changelog.

## 4. VectorDB source-document cleanup

- [x] 4.1 [backend] Define strict chunk-resolution and source-level cleanup results through the vector store port;
  verify errors cannot become successful empty lookups and existing best-effort update cleanup remains compatible.
- [x] 4.2 [backend] Implement bounded OpenSearch source-ID lookup and complete chunk pagination with mapped fields;
  verify multiple lookup batches, multiple result pages, missing-index checks, and lookup-failure tests.
- [x] 4.3 [backend] Implement complete Milvus chunk lookup for original source IDs with bounded requests;
  verify all matching chunks beyond a single result page, prefix identity, missing-collection checks, and errors.
- [x] 4.4 [backend] Add independent VectorDB cleanup business logic using the incremental service and adapter port;
  verify chunk deletion, partial failures, already-absent idempotency, resource cleanup, and preservation of unrelated IDs.
- [x] 4.5 [backend] Document source deletion versus stale-chunk replacement in existing VectorDB reference/operator
  documentation; verify configuration examples and original-ID-to-chunk explanations against adapter tests.

## 5. Execution scheduling and acknowledgment

- [x] 5.1 [backend] Resolve one tracking context and acquire/release the execution guard around synchronization runs;
  remove empty-inventory fallback reconciliation; verify explicit context, missing evidence, and cancellation tests.
- [x] 5.2 [backend] Schedule one executor-mediated cleanup phase per configured VectorDB node before batches,
  including zero-row ingestion; verify no unnecessary extraction/embedding execution and no per-batch duplicate cleanup.
- [x] 5.3 [backend] Coordinate acknowledgment across configured destinations and preserve backlog on failures or no
  destinations; verify two-sink partial failure, retry, reappearance, and interrupted-run tests.
- [x] 5.4 [backend] Integrate cleanup results into existing node/run reporting and failure policies without resetting
  deletion state in batch scheduling; verify processing, discovery, deleted-document, and deleted-chunk counts remain distinct.
- [x] 5.5 [backend] Document deletion-only execution, destination retries, and same-context serialization in the
  existing flow configuration guide; verify the guide agrees with engine tests and configuration reference.

## 6. Integration verification

- [x] 6.1 [backend] Add a filesystem-to-fake-VectorDB repeated-run scenario with 100 files and `max_files: 10`;
  verify ten incremental runs process all files once, complete discovery never selects more than ten, and deleted files
  lose all chunks in a later run. Use a lazy large-cardinality fake to verify discovery memory/selection behavior
  without creating ten million physical files.
- [x] 6.2 [backend] Exercise forced ingestion plus deletion, empty source, no-new-document cleanup, retained backlog,
  and concurrent micro-batches end to end; verify outcomes for both orchestrator configurations and mocked sinks.
- [x] 6.3 [backend] Verify CLI, library, and REST job execution preserve effective flags and tracking context using
  entrypoint tests; run the affected ingestion, incremental-store, VectorDB, and orchestration pytest suites.
- [x] 6.4 [backend] Run `uv run ruff check --fix .` and `uv run mypy .`, inspect any generated edits, and rerun affected
  tests if fixes alter behavior; verify failures are resolved or identified as existing baseline issues.
- [x] 6.5 [backend] Run `openspec validate update-incremental-processing --strict`, review changed docs
  and relative links, and verify the implementation diff contains no frontend, dependency, or changelog changes.

## 7. Reviewed follow-up improvements

- [x] 7.1 [backend] Use shared processing filters in Box for both modes; verify exclusion patterns and paths.
- [x] 7.2 [backend] Replace S3 metadata task batches with direct streaming conversion; preserve error semantics.
- [x] 7.3 [backend] Reuse Graph streaming traversal in the list-returning compatibility API; verify pagination/recursion.
- [x] 7.4 [backend] Reuse complete Box listing metadata with a fallback for incomplete entries; verify request counts.
- [x] 7.5 [backend] Stream filesystem/Postgres tracking into a temporary disk-backed snapshot for synchronization;
  verify bounded ingestion history, incremental eligibility, force behavior, reappearance, and cleanup on errors.

## 8. Tracking-loss correction

- [x] 8.1 [backend] Restore reappearing tombstones in place with an invalidated processing timestamp in filesystem
  and PostgreSQL stores; verify second disappearance, regeneration, scope isolation, and rollback in existing tests.

## Workflow follow-up

- Review these planning artifacts before starting implementation with `openspec-apply-change`.
- If committing implementation, use signed-off commits and the repository's branch-scoped pre-commit workflow;
  never run pre-commit with `--all-files`.
- Archive only after implementation review and required checks pass; do not edit live specs directly.

## Verification results

- Test-file consolidation: moved all added cases into the existing ingest source, incremental update service,
  Postgres incremental store, OpenSearch batch processor, and Milvus batch processor test files. Removed all five
  new test files. The affected suites pass with 287 tests and one optional PostgreSQL integration test skipped when
  `DOCPIPE_TEST_POSTGRES_URL` is unset. Ruff checks on those existing test files pass.

- Discovery-state simplification: removed `DiscoveryState`; discovery errors now fail ingestion and the flow before
  reconciliation or downstream processing. The 42 focused discovery, synchronization, and empty-ingest tests pass.

- Backend regression suite: 2,472 passed, one existing log-capture test deselected. The same test fails in the
  unchanged HEAD overlay with 998 other orchestration tests passing, and passes when run separately.
- Follow-up adapter verification after final pagination adjustments: 124 passed. Follow-up executor, source discovery,
  and synchronization checks after final internal-metadata filtering: 61 passed.
- Real PostgreSQL advisory-lock and filesystem/SQL parity checks: seven passed using an isolated temporary PostgreSQL
  server on a private Unix socket. The server was stopped after verification. Set `DOCPIPE_TEST_POSTGRES_URL` to run
  the added PostgreSQL integration test against a test database.
- Repository-wide Ruff and mypy commands were run. Mypy matches HEAD's 45 errors across 12 files. Follow-up fixes
  resolve all 68 logging violations in touched files (62 G004 and six G201); Ruff now passes for every changed Python
  file. Unrelated automatic lint edits were restored.
- Strict OpenSpec validation, changed Python formatting, whitespace checks, and touched-document relative links pass.
- Live OpenSearch/Milvus and cloud credentials were not used; their pagination, strict lookup, and failure behavior
  are covered with mocked clients. Canonical specs, frontend, dependencies, and the changelog are unchanged.

- Fetch-path simplification: removed `SUPPORTS_DISCOVERY`, `discover_documents()`, and `_discover_metadata()`.
  Complete enumeration now uses `fetch_documents(..., full_listing=True)` and the existing provider listing paths;
  Google Drive streams pages in both modes. Legacy signatures do not authorize reconciliation. All 627 ingestion
  and incremental tests passed; after final simplification and compatibility cases, 220 focused tests passed,
  followed by 34 filesystem checks. Tests remain in existing files. Changed-file Ruff/formatting and strict OpenSpec
  validation pass; mypy remains at the existing 45 errors in 12 files.

- Reviewed follow-up improvements: shared Box processing eligibility in folder/single-file modes; full folder pages
  request and reuse complete metadata, with a per-file fallback only for incomplete entries. S3 converts metadata
  directly without async task batches, and Graph list-returning callers use the streaming traversal.
- Synchronization history now streams filesystem Parquet or PostgreSQL rows in 1,000-record batches into a temporary
  SQLite snapshot (standard library, no dependency or persistent-schema change). Tests verify scope/soft-deletion
  parity, repeated/forced ingestion, failure/cancellation cleanup, and no all-history dictionary API calls. A lazy
  100,000-record history stays below 8 MiB of traced Python allocations; selected rows and actual deletion evidence
  still scale with their own counts. Temporary disk usage scales with tracked history.
- Follow-up regression verification: 2,323 checks passed in the sandbox; six Prefect integration checks initially
  failed because the temporary server could not bind a local port, then all six passed with local-server access.
  Two opt-in PostgreSQL checks were skipped in that run and both passed against an isolated temporary PostgreSQL
  server, including a 2,501-record streaming snapshot. The server was stopped and removed. One previously documented
  baseline log-capture test remains deselected. Updated history tests separately pass (102 passed, two opt-in skips).
- Changed-file Ruff/formatting, strict OpenSpec validation, and whitespace checks pass. Mypy remains at 45 existing
  errors in 12 files. All test additions remain in existing test files.

- Tracking-loss correction: reappearance now restores still-deleted records in place and nulls the processing
  timestamp, preserving identity until regeneration or acknowledged cleanup. A regression reproduced the old loss
  in filesystem and SQL stores before the fix. Existing-file tests now cover reappearance beyond `max_files`, a
  second disappearance and orphaned-chunk cleanup, scope isolation, stale restoration after regeneration, and atomic
  failure/rollback. The incremental-metadata and VectorDB suites pass (730 passed, three opt-in PostgreSQL skips);
  six focused transition checks also pass. The new live PostgreSQL restoration check passed against an isolated
  temporary server, which was stopped and removed. Ruff, formatting, whitespace, and strict OpenSpec validation
  pass. Mypy remains at the existing 45 errors in 12 files.
