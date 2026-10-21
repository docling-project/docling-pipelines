# Proposal

## Why

Deduplication must admit content once per operator node in each job run across concurrent batches, while allowing separate branches and overlapping runs to process the same content independently. A single mutable latest-run record loses membership when runs overlap, and a job-wide registry without node identity incorrectly suppresses content needed by other branches.

## What Changes

- Give ededup its own storage port, factory, PostgreSQL model/adapter, and filesystem adapter outside `core/incremental_metadata`.
- **BREAKING configuration change:** use `ededup.storage` (with shared `global_storage` defaults) instead of `incremental_metadata.storage` for deduplication. Document explicit relocation of any existing service-specific settings.
- **BREAKING backend/API changes:** reject the legacy backend-only `filter` argument and remove `transform(..., file_name=...)`; direct callers use `transform(table)`. The UI does not expose a `filter` field. Callers supplying job/run context must also supply the node ID.

- Establish PostgreSQL admission records with job ID, run ID, node ID, content hash, and document ID, uniquely keyed by `(job_id, job_run_id, node_id, hash)`.
- Retain independent membership for each branch's ededup node. A sequential flow has one ededup node; separate branches after extraction can have their own nodes.
- Reduce each batch to one representative per hash, atomically insert candidates in bulk, and pass through only newly inserted hashes for that node and run.
- Retain independent run records after source deletion. Accept renamed documents in a new run with their current IDs; skip them in the same node/run when the hash is already registered.
- Persist admissions by default for pipeline execution. A committed admission remains after downstream failure, so a retry at the same node/run skips that content; a new run has independent membership.
- Move tests and documentation to the dedicated node-scoped ededup storage boundary, preserving filesystem compatibility and standalone local mode.

## Capabilities

### New Capabilities

- `backend/ededup-operator`: Atomic content admission per job, run, and operator node across batches, with independent branches, overlapping runs, and retained admission history.

### Modified Capabilities

None; the project has no existing Ededup operator specification to modify.

## Impact

Affected areas are `EdedupOperator`, a dedicated `core/operators/quality/ededup_storage/` package, configuration examples, ededup unit/integration tests, and operator/configuration documentation. Document shared-storage deployment requirements and concrete cleanup procedures for completed run scopes. Remove ededup methods and table ownership from incremental metadata. Reuse the current atomic admission algorithm and existing node-scoped data; no node-removal migration or new dependency is required. SQL remains behind a port, outside the operator's business logic. Existing PostgreSQL connections may be shared, but ededup initializes only its own table. Application source code has not yet been refactored to this boundary.

This change does not implement rename-output reuse, alter ingestion eligibility, add flow topology validation, change normalization, add registry garbage collection, deduplicate merged branch outputs automatically, or guarantee downstream success. Rename detection, completed-content history, orchestration hooks, and vector-store rename updates are deferred and preserved in `deferred_work/rename-handling/`. Filename-change examples test ordinary hash admission only.
