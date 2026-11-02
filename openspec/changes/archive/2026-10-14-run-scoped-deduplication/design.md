# Design

## Context

See the [proposal](proposal.md) for motivation and [requirements](specs/backend/ededup-operator/spec.md) for the behavioral contract. The working tree already contains atomic bulk admissions, node-scoped PostgreSQL and filesystem storage, and concurrency tests. The active changes contain ededup only. Rename-reuse code, configuration, documentation, and tests are preserved separately in `deferred_work/rename-handling/` for later work.

`EdedupOperator` normalizes content, selects candidate rows, calls its dedicated storage port, and filters by returned hashes. PostgreSQL keys the `hashes` table by job, node, run, and `hash_value` in the `ededup_registry` schema; filesystem scopes also include node identity under the `ededup_registry` directory. The factory defaults to filesystem; configured PostgreSQL supports distributed workers.

## Goals / Non-Goals

**Goals:** Separate ededup admission storage from incremental metadata ownership and configuration. Retain independent branch membership and independent overlapping runs, with atomic admission across workers executing the same node. Verify existing behavior and complete missing tests and documentation.

**Non-Goals:** Changing normalization, ingestion eligibility, downstream completion semantics, rename-output reuse, backend defaults, retention policy, or flow validation. A sequential flow has one ededup node; the multiple-node use case is branching after extraction. No new run-wide lock is introduced. Rename-reuse coordination is deferred and absent from the active implementation.

## Decisions

### Operator-owned storage boundary

Keep `quality/ededup.py` and its public import path. Add sibling package `quality/ededup_storage/` with:

- `ports/ededup_store.py`: `EdedupStore` ABC exposing atomic `check_and_register_hashes`, accepting job, node, run, and hash-to-document candidates and returning committed admissions.
- `adapters/postgres_store.py` and `adapters/models.py`: ededup-only engine lifecycle, table model, initialization, and bulk admission.
- `adapters/filesystem_store.py`: ededup registry files and locking only.
- `factory.py`: backend selection, lazy instance lifetime, and dependency construction; expose the port to the operator.

The operator hashes and filters rows; it never imports concrete store adapters or executes SQL. The dedicated stores must not subclass incremental stores, instantiate the incremental factory, initialize `inc_update_metadata`, or read source modification/deletion records. They may reuse general PostgreSQL connection utilities and generic filesystem helpers without sharing incremental service ownership.

Move the existing admission methods and model rather than duplicating implementations. Remove them from the incremental port and adapters. Keep unrelated incremental behavior and fixes unchanged. A source-deletion integration test may explicitly use both stores to prove independence; production ededup must not depend on the incremental store. A dedicated package fits the neighboring operator port/adapter structure without changing the public operator import.

### Independent configuration

Use the existing `DOCPIPE_CONFIG_PATH` file discovery, but resolve ededup settings from `ededup.storage`, then `global_storage`, then the filesystem default. Merge connection/config defaults with explicit ededup values taking precedence. Unsupported backend values and invalid configuration fail explicitly. Do not read `incremental_metadata` settings or `DOCPIPE_INCREMENTAL_BASE_DIR` to select or construct the ededup store.

PostgreSQL continues to accept the common `DOCPIPE_POSTGRES_*` connection environment variables. Filesystem uses its own `config.base_dir` and defaults to the common data root, storing only `ededup_registry/`. The PostgreSQL adapter creates only the `hashes` table in the configured schema (default `ededup_registry`), never the incremental table. Existing data under the former `dedup_registry` defaults is not automatically migrated; PostgreSQL users can explicitly configure the old schema, while filesystem users must move the registry directory.

For installations with service-specific incremental storage settings, copy the required connection/schema or base-directory values into `ededup.storage` before rollout. No implicit fallback to incremental configuration is added: it would keep the lifecycle coupling the separation is intended to remove. Keeping `global_storage` defaults is shared infrastructure configuration, not dependence on incremental metadata.

Example dedicated configuration:

```yaml
ededup:
  storage:
    type: postgresql
    config:
      postgres:
        schema: incremental_metadata
```

The example uses the dedicated ededup registry namespace. Tests must also use an ededup-only schema and prove `inc_update_metadata` is never created.

### One row per job/run/node/hash

Retain `node_id` in the model, storage port, and operator call. Keep physical column name `hash_value` for conceptual `hash`. Store five fields: `job_id`, `job_run_id`, `node_id`, `hash_value`, and `doc_id`. The first four define uniqueness; their ordering in the existing primary key need not change. Document ID is metadata and is not part of uniqueness.

Workers executing the same flow node use its stable node ID, not a per-worker ID. Separate branch nodes have distinct IDs, so both can accept the same hash. A latest-run row keyed only by job/hash loses history during overlapping runs. Omitting node identity incorrectly makes one branch suppress another; both alternatives are rejected.

### Branches, runs, and renames

For job J1/run R1, branches A and B each admit H once under their own node IDs. Later batches at A skip H regardless of B's activity. Concurrent branches may choose different source documents with identical normalized content; no cross-branch winner coordination is needed. Merging outputs does not automatically remove duplicates between branches.

For the same node, run A accepts H, overlapping run B accepts H independently, and a later batch in A still skips H. Other jobs also remain independent.

A filename change that yields a new document ID leaves H unchanged. In a new run each branch can accept it and save the new ID, preserving earlier records. In the same node/run, an existing H causes a skip without updating the winning ID. Another branch can accept it if H is new to that node. These rules apply only to documents that reach deduplication; source metadata updates in vector stores and embedding reuse are separate behavior.

### Atomic bulk admission

Keep sorted candidate hashes and bounded chunks (currently 1,000 records), with all chunks in one transaction. Use `INSERT ... ON CONFLICT DO NOTHING RETURNING hash_value` against the existing job/node/run/hash key. Return accepted hashes only after commit; on failure roll back the whole call and propagate the error. Sorting overlapping sets consistently reduces deadlock risk.

Unique-key enforcement coordinates competing workers. A separate search or application-managed admission lock is unnecessary. Retain existing initialization advisory locking for concurrent table creation. Conflicts never overwrite the winning document ID.

### Operator and backend compatibility

Preserve normalization, first-row selection within a batch, row-based filtering, output order/schema, and skipped metadata. Require job, run, and node identity for shared admission. Preserve local state when both job/run context values are absent. SQL remains in a dedicated ededup PostgreSQL adapter behind the `EdedupStore` port and `EdedupStoreFactory`.

Reject the legacy `filter` configuration argument explicitly; it was backend-only and has no UI field. Direct callers use `transform(table)`; the `file_name` keyword is no longer supported. A caller that supplies job and run context must also supply the flow node ID. Keep these as explicit compatibility breaks in operator documentation and the PR description.

Keep filesystem job/node/run scopes, file locking, and atomic replacement. Filesystem concurrency applies only to workers sharing the same directory; it does not replace PostgreSQL for distributed workers without shared storage. Preserve the admission method signature on `EdedupStore` and explicit unsupported-backend errors. Custom ededup adapters register with `EdedupStoreFactory`; incremental-only adapters no longer implement admission methods.

Pipeline execution uses the persistent filesystem registry by default unless another `ededup.storage` backend is configured. Filesystem records are scoped to the SHA-256 filename for the JSON-encoded `[job_id, node_id, job_run_id]` tuple under `ededup_registry/`; PostgreSQL records use the corresponding columns in the configured schema. There is no automatic run cleanup. Document manual scope cleanup only after all workers for that run stop, including PostgreSQL predicates and filesystem file/lock removal, and warn that deletion allows the same run to admit those hashes again.

### Admission is not successful processing

A committed admission remains after downstream failure. Retrying at the same node/run skips that hash; a new run can retry independently. Across concurrent batches, whichever transaction admits first wins; within a batch, the first row is the candidate.

## Risks / Trade-offs

- Two branches can retain different source IDs for identical content -> document that winners are independent and nondeterministic across concurrent batches.
- Merged branch outputs can contain the same content -> make clear that branch deduplication is not a merge policy; automatic cross-branch deduplication is outside scope.
- Registry size grows with unique content per node and run -> retain records as agreed; garbage collection is outside scope and must not remove active membership.
- Failure after commit can leave an admission without downstream output -> preserve admission-only semantics and test same-node retry and new-run recovery behavior.
- Much of the implementation already exists uncommitted -> verify it against scenarios before marking tasks complete, and preserve deferred rename-reuse changes outside active source paths.

## Compatibility and Rollout

Move configuration explicitly as described above before switching the operator to the new factory. Settings under `incremental_metadata.storage` are not implicitly migrated; copy the needed settings to `ededup.storage`. Existing data under the former `dedup_registry` PostgreSQL namespace or legacy `ededup_hashes` tables/folders is not automatically migrated or read. Users retaining the old PostgreSQL registry can configure schema `dedup_registry`; filesystem registry data must be moved into the new `ededup_registry` directory under the same base directory. No node-removal or record-consolidation migration is required for node-scoped data already in the current registry. Verify fresh initialization and reopening populated registries, including concurrent PostgreSQL initialization. Use disposable schemas/directories for validation. Rollback of the code relocation uses the previous factory/settings against the same registry; do not delete or reset admission data. The deferred rename restoration patch targets the pre-refactor layout and must be reconciled when that work resumes; retain its snapshot unchanged.

## Validation

Add configuration precedence and import-boundary tests. Prove dedup works without an incremental service, creates no incremental table/directory, and ignores incremental service-specific settings. Conversely, initializing incremental metadata must not create an ededup table. Re-run the existing behavioral suites through the new factory and adapters.

Cover same-node concurrency across independent processes, different branch nodes accepting independently, stable node IDs across workers, A/B/A run interleaving, independent jobs, and unchanged winner IDs. Verify same-run rename skips, new-run renamed IDs in each branch, source-deletion retention, existing registry reopening, full rollback after the first insert chunk, missing context, empty tables, repeated document IDs, and skipped metadata. Use `DOCPIPE_TEST_POSTGRES_DSN` and the disposable-schema fixture; skipped database tests do not establish concurrency correctness.
