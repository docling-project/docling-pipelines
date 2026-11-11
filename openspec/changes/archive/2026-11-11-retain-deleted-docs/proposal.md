# Proposal: Retain Deleted Documents Sync and Cleanup

## Why

In incremental processing workflows, documents that are deleted from the upstream data source (e.g. S3, Box, Google Drive, filesystem) can leave stale records in downstream target stores (such as OpenSearch, Milvus, and incremental metadata tracking repositories). When `retain_deleted_docs: false` is configured, users expect deleted source files to have their associated downstream representations (such as vector chunks) cleanly removed, and tracking state finalized.

Previous discussions explored full source enumeration and external sync history streams, but a simpler, more robust, and architecturally cleaner approach was selected: integrate soft-deletion tracking directly into the incremental metadata store and perform deletion cleanup in target output operators (such as VectorDB) during flow execution, followed by a post-execution purge of soft-deleted records when the run succeeds, or rollback unmarking if target cleanup fails.

## What Changes

- **Incremental Metadata Store & Service**:
  - Add `unmark_soft_deleted_docs(*, job_id: str, doc_ids: list[str] | None = None)` to revert soft-deleted flags on failure rollback.
  - Add `purge_soft_deleted_docs(*, job_id: str)` to hard-delete records marked `deleted == True` once a flow run completes successfully.
  - In `process_ingested_docs`: Only mark soft-deleted documents when `retain_deleted_docs: false` and `force_ingest: false`.
- **VectorDB Operator Cleanup**:
  - In `VectorDBOperator.transform()` (or execution lifecycle): Query soft-deleted source document IDs for the current job run.
  - Resolve soft-deleted source document IDs to their stored chunk IDs in the vector store (OpenSearch, Milvus) via `adapter.get_chunk_ids_for_documents()` and delete them via `adapter.delete_documents_by_ids()`.
  - On cleanup failure: Unmark the soft-deleted records in the incremental store and fail the operator step / job run with `ExecutionStatus.FAILED`.
- **Flow Orchestration Lifecycle**:
  - In `AbstractOrchestrator` (`_finalize_dag_flow` / completion handling): When a flow completes with `ExecutionStatus.SUCCEEDED` (or non-terminal/non-failed completion), call `incremental_service.purge_soft_deleted_docs(job_id=self.job_id)`.
  - When all ingested documents are skipped or zero new documents are ingested but soft-deleted documents exist, ensure target cleanup operators are executed to clean up deleted documents rather than completely bypassing target stores.
- **Unchanged Behavior (`force_ingest: true`)**:
  - `force_ingest: true` behavior remains unchanged: incremental eligibility checks are bypassed and existing incremental metadata for the job is cleared.

## Non-goals

- Full source metadata inventory enumeration or uncapped listing across source connectors (Box, S3, Google Drive, OneDrive/SharePoint).
- Intermediate temporary sync history disk streams or secondary tracking databases.
- Modifying `force_ingest` behavior or participating in deletion sync when `force_ingest: true`.
- Frontend UI changes (existing toggle `retain_deleted_docs` in `global_config` remains unchanged).

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `backend/flow-execution-engine`: Add soft-deletion marking during ingest, output operator invocation for pending deletions when zero documents are ingested, post-execution purge of soft-deleted records on success, and failure rollback handling.
- `backend/vectordb-operator`: Add cleanup of soft-deleted source documents by resolving and deleting all associated chunk IDs from the target vector store, with failure rollback unmarking in the incremental metadata store.

## Impact

- **Affected Layers**: Backend only (`src/docpipe/core/incremental_metadata/`, `src/docpipe/core/operators/vectordb/`, `src/docpipe/core/orchestration/`).
- **APIs**: No REST API schema modifications.
- **Dependencies**: No new external dependencies.
