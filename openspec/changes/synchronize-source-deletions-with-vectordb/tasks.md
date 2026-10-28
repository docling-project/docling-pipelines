# Tasks

Each task is sized for at most two hours. Activate `.venv` before Python validation commands.
All work below implements the [incremental-update capability](specs/backend/incremental-update/spec.md),
including its source, orchestration, and VectorDB integration.

## 1. Source discovery contracts and adapters

- [ ] 1.1 [backend] Define identity-only discovery and explicit completion/error results on the source port, with
  unsupported/event-scoped behavior; verify contract tests cannot mistake capped or unsupported discovery for completion.
- [ ] 1.2 [backend] Implement filesystem identity discovery before processing filters, with missing-root, subtree,
  and stat-error propagation; verify empty-root success and incomplete-walk tests in the filesystem adapter suite.
- [ ] 1.3 [backend] Implement S3/IBM COS identity discovery preserving listed identities on conversion errors and
  exhausting pagination without binary reads; verify paginated fake-client tests and existing S3 tests.
- [ ] 1.4 [backend] Implement streaming Google Drive discovery independent of `max_files` in synchronization mode;
  verify multi-page discovery, no full inventory arrays, no binary downloads, and unchanged limited-fetch tests.
- [ ] 1.5 [backend] Implement complete Box discovery including folder pagination, without the synchronization-mode
  adapter cap; verify nested/paginated listings, error propagation, and existing limited-fetch tests.
- [ ] 1.6 [backend] Implement complete Dropbox discovery independent of its synchronization-mode adapter cap;
  verify continuation pages, processing-filter presence evidence, and unchanged limited-fetch tests.
- [ ] 1.7 [backend] Implement authoritative OneDrive metadata discovery with page/error completion evidence;
  verify fake-client multi-page, partial-failure, and single-file tests.
- [ ] 1.8 [backend] Implement authoritative SharePoint metadata discovery with page/error completion evidence;
  verify fake-client multi-page, partial-failure, and single-file tests.
- [ ] 1.9 [backend] Document supported discovery modes and incomplete/unsupported-provider behavior in existing
  source integration documentation; verify links and examples against the source contracts.

## 2. Incremental deletion lifecycle

- [ ] 2.1 [backend] Extend domain ports and application services for historical/pending candidate retrieval,
  complete-scan marking, reappearance invalidation, and guarded acknowledgment; verify service tests for all transitions.
- [ ] 2.2 [backend] Implement filesystem store operations without prematurely purging tombstones; verify persistence,
  reappearance outside selection, scope isolation, and all-destinations acknowledgment tests.
- [ ] 2.3 [backend] Implement equivalent Postgres operations using the mapped document ID column; verify store parity
  tests, conditional deletion, and transaction rollback on acknowledgment failure.
- [ ] 2.4 [backend] Add a dedicated filesystem context execution guard independent of record locks; verify two-process
  contention, independent contexts, batch metadata writes, and release after cancellation/failure.
- [ ] 2.5 [backend] Add the Postgres context execution guard on a dedicated advisory-lock connection; verify contention,
  connection cleanup, and normal concurrent batch record writes in Postgres integration tests.
- [ ] 2.6 [backend] Update existing incremental-processing documentation for tombstone retries and context ownership;
  verify the documented lifecycle matches service and backend parity tests.

## 3. Conditional ingestion and forced processing

- [ ] 3.1 [backend] Separate presence recording from selected-row conversion using the existing source ID algorithm
  and unmatched historical candidates; verify unchanged, filtered, and beyond-limit entries never become missing.
- [ ] 3.2 [backend] Wire complete discovery only with retention disabled, retain provider/loader behavior otherwise,
  and preserve typed empty output; verify both ingestion paths, selected-row schema, and metrics with fake iterators.
- [ ] 3.3 [backend] Preserve comparison history with forced ingestion when retention is disabled, while bypassing
  incremental eligibility checks; verify all four flag combinations and preservation of unselected history.
- [ ] 3.4 [backend] Emit explicit internal discovery evidence and scope; suppress reconciliation for failed,
  cancelled, unsupported, and file-event runs; verify existing ingestion error tests and new absence-evidence tests.
- [ ] 3.5 [backend] Update `docs/reference/GLOBAL_CONFIG.md`, the ingest section of `docs/reference/OPERATORS.md`,
  and the existing ingest operator README for conditional discovery costs, filters, limits, and force behavior;
  verify examples and relative links without changing the changelog.

## 4. VectorDB source-document cleanup

- [ ] 4.1 [backend] Define strict chunk-resolution and source-level cleanup results through the vector store port;
  verify errors cannot become successful empty lookups and existing best-effort update cleanup remains compatible.
- [ ] 4.2 [backend] Implement bounded OpenSearch source-ID lookup and complete chunk pagination with mapped fields;
  verify multiple lookup batches, multiple result pages, missing-index checks, and lookup-failure tests.
- [ ] 4.3 [backend] Implement complete Milvus chunk lookup for original source IDs with bounded requests;
  verify all matching chunks beyond a single result page, prefix identity, missing-collection checks, and errors.
- [ ] 4.4 [backend] Add independent VectorDB cleanup business logic using the incremental service and adapter port;
  verify chunk deletion, partial failures, already-absent idempotency, resource cleanup, and preservation of unrelated IDs.
- [ ] 4.5 [backend] Document source deletion versus stale-chunk replacement in existing VectorDB reference/operator
  documentation; verify configuration examples and original-ID-to-chunk explanations against adapter tests.

## 5. Execution scheduling and acknowledgment

- [ ] 5.1 [backend] Resolve one tracking context and acquire/release the execution guard around synchronization runs;
  remove empty-inventory fallback reconciliation; verify explicit context, missing evidence, and cancellation tests.
- [ ] 5.2 [backend] Schedule one executor-mediated cleanup phase per configured VectorDB node before batches,
  including zero-row ingestion; verify no unnecessary extraction/embedding execution and no per-batch duplicate cleanup.
- [ ] 5.3 [backend] Coordinate acknowledgment across configured destinations and preserve backlog on failures or no
  destinations; verify two-sink partial failure, retry, reappearance, and interrupted-run tests.
- [ ] 5.4 [backend] Integrate cleanup results into existing node/run reporting and failure policies without resetting
  deletion state in batch scheduling; verify processing, discovery, deleted-document, and deleted-chunk counts remain distinct.
- [ ] 5.5 [backend] Document deletion-only execution, destination retries, and same-context serialization in the
  existing flow configuration guide; verify the guide agrees with engine tests and configuration reference.

## 6. Integration verification

- [ ] 6.1 [backend] Add a filesystem-to-fake-VectorDB repeated-run scenario with 100 files and `max_files: 10`;
  verify ten incremental runs process all files once, complete discovery never selects more than ten, and deleted files
  lose all chunks in a later run. Use a lazy large-cardinality fake to verify discovery memory/selection behavior
  without creating ten million physical files.
- [ ] 6.2 [backend] Exercise forced ingestion plus deletion, empty source, no-new-document cleanup, retained backlog,
  and concurrent micro-batches end to end; verify outcomes for both orchestrator configurations and mocked sinks.
- [ ] 6.3 [backend] Verify CLI, library, and REST job execution preserve effective flags and tracking context using
  entrypoint tests; run the affected ingestion, incremental-store, VectorDB, and orchestration pytest suites.
- [ ] 6.4 [backend] Run `uv run ruff check --fix .` and `uv run mypy .`, inspect any generated edits, and rerun affected
  tests if fixes alter behavior; verify failures are resolved or identified as existing baseline issues.
- [ ] 6.5 [backend] Run `openspec validate synchronize-source-deletions-with-vectordb --strict`, review changed docs
  and relative links, and verify the implementation diff contains no frontend, dependency, or changelog changes.

## Workflow follow-up

- Review these planning artifacts before starting implementation with `openspec-apply-change`.
- If committing implementation, use signed-off commits and the repository's branch-scoped pre-commit workflow;
  never run pre-commit with `--all-files`.
- Archive only after implementation review and required checks pass; do not edit live specs directly.
