# Tasks

The first implementation and rename separation were verified. Storage ownership is now being refactored; tasks 1-4 are reopened to verify the new boundary. Completed separation work in group 5 remains preserved.

## 1. Dedicated storage boundary and operator contract

- [x] 1.1 Create the dedicated `ededup_storage` port and factory, move admission ownership out of the incremental port/adapters, and switch the operator to the dedicated factory while retaining node identity; complete any gaps in shared-context validation. Verify operator/shared-store tests cover stable node IDs across workers, independent branch nodes, same-node A/B/A run interleaving, independent jobs, missing node ID rejection, partial context rejection, and standalone behavior.
- [x] 1.2 Preserve batch normalization, first-row selection, row identity, output order/schema, and skipped metadata. Verify tests cover duplicate hashes, repeated document IDs with distinct hashes, empty tables, one bulk port call, propagated store failures, and same-node replay after downstream failure.
- [x] 1.3 Update `docs/operators/quality/ededup_readme.md` and `docs/reference/OPERATORS.md` to explain node-scoped membership, independent branches after extraction, no automatic deduplication of merged outputs, same-node retry behavior after downstream failure, rejected legacy `filter`/`file_name` call forms, and required node context. Document same-node/same-run rename skips versus new-run acceptance in each branch; verify links and consistency with tests. Do not update `CHANGELOG.md` as part of the PR.

- [x] 1.4 Implement `ededup.storage` configuration precedence over `global_storage` and filesystem defaults without reading incremental settings; verify missing/invalid configs, independent service overrides, common PostgreSQL environment settings, and base-directory handling. Update configuration examples and document moving existing service-specific settings to ededup in `docs/reference/GLOBAL_CONFIG.md`.
- [x] 1.5 Add import/lifecycle regression tests proving the operator and ededup adapters do not import or initialize incremental storage, and incremental initialization does not create ededup records; verify the boundary tests and existing incremental suite pass.

## 2. PostgreSQL admission and compatibility

- [x] 2.1 Move the five-column PostgreSQL model and adapter into `ededup_storage`; initialize only the ededup table and retain and job/node/run/hash uniqueness; verify or complete atomic bounded bulk inserts with conflict-ignore and returned hashes. Test fresh schema shape, mixed existing/new hashes, unchanged winner IDs, source-deletion retention, and same-run versus new-run rename behavior at different nodes.
- [x] 2.2 Verify existing node-scoped registry compatibility without migrations: add or extend disposable-schema tests for reopening records at multiple nodes, independent memberships and document IDs, repeated/concurrent initialization, and preservation of unrelated incremental metadata.
- [x] 2.3 Extend `tests/integration/test_ededup_postgres.py` for independent processes submitting opposite-order overlapping hash sets to the same node, independent branch nodes, overlapping runs, and rollback after the first chunk. Verify one winner per job/run/node/hash and no partial admissions on failure against real PostgreSQL.
- [x] 2.4 Document dedicated PostgreSQL configuration, unique-key scope, bulk transaction behavior, and retention in the existing operator documentation and references. Include concrete SQL cleanup for completed run scopes and verify documentation matches the database tests. Do not update the Unreleased changelog or introduce a node-removal migration.

## 3. Filesystem compatibility

- [x] 3.1 Move filesystem admission into `ededup_storage` with no incremental-store inheritance; retain job/node/run partitioning, locking, and atomic replacement. Complete tests for same-node cross-instance concurrency, independent branch nodes and runs, retained metadata, and renamed documents within and between runs.
- [x] 3.2 Verify reopening existing node-scoped files preserves every membership and representative document ID without consolidation or reset. Test multiple nodes and independent jobs/runs using temporary directories.
- [x] 3.3 Reconcile filesystem documentation with node-scoped behavior; document the persistent filesystem default, shared-directory deployment requirement, and safe cleanup of a completed run's Parquet and lock files. Verify independent configuration defaults and standalone behavior are clear.

## 4. Integrated verification

- [x] 4.1 Activate the project venv and run relevant operator and incremental metadata unit suites plus PostgreSQL integration tests using `DOCPIPE_TEST_POSTGRES_DSN` for a disposable database. Verify independent storage lifecycle/configuration, branch independence, overlapping runs, ordinary hash admission under changed filenames, and registry compatibility; report missing database access as blocked verification rather than counting skipped tests as a pass.
- [x] 4.2 Run applicable lint/type checks and strict OpenSpec validation, inspect the final diff for unrelated changes, and verify changed documentation links. Before pushing, run `pre-commit run --from-ref origin/main --to-ref HEAD` (or the actual PR base for stacked branches) and distinguish pre-existing failures from this change.

## 5. Ededup-only separation

- [x] 5.1 Preserve deferred rename handling and verify its restoration patch reconstructs the pre-split files.
- [x] 5.2 Remove rename-only source, configuration, docs, and tests from active changes; verify no dangling rename-reuse imports or configuration references remain.
- [x] 5.3 Run ededup-only unit and real PostgreSQL tests, lint/type checks, documentation-link checks, and strict OpenSpec validation after separation.
