# Design: Retain Deleted Documents Sync and Cleanup

## Context

When running pipelines with `retain_deleted_docs: false`, source documents previously tracked in the incremental metadata store that are no longer returned during discovery must be cleaned up across downstream output stores (e.g. VectorDB chunk indices in OpenSearch/Milvus), and their metadata state finalized.

See `proposal.md` for motivation and background.

## Goals / Non-Goals

**Goals:**
- Provide atomic soft-deletion lifecycle in `IncrementalMetadataStore` port and adapters (`FilesystemIncrementalStore`, `PostgresIncrementalStore`).
- Implement `unmark_soft_deleted_docs` for failure rollback and `purge_soft_deleted_docs` for successful post-run cleanup.
- Integrate target vector store chunk cleanup in `VectorDBOperator` for soft-deleted documents with error rollback.
- Trigger `purge_soft_deleted_docs` on successful pipeline termination in `AbstractOrchestrator._finalize_dag_flow`.
- Handle cases where zero new documents are ingested but soft-deleted documents are pending cleanup.

**Non-Goals:**
- Re-architecting source connector listing/discovery algorithms or enumerating full source metadata trees.
- Modifying `force_ingest: true` behavior.
- Altering external REST API schemas or canvas UI components.

## Decisions

### Decision 1: Incremental Store Operations for Soft Deletion Lifecycle
- **Rationale**: Manage soft deletion state directly in the existing `IncrementalMetadataStore` interface (`domain/ports/incremental_metadata_store.py`) and adapters (`FilesystemIncrementalStore`, `PostgresIncrementalStore`), rather than introducing an out-of-band sync table.
- **Methods Added**:
  - `unmark_soft_deleted_docs(*, job_id: str, doc_ids: list[str] | None = None)`: Sets `deleted = False` for specified or all soft-deleted records of `job_id`.
  - `purge_soft_deleted_docs(*, job_id: str)`: Hard-deletes all records where `deleted == True` for `job_id`.
- **Alternatives Considered**: Creating temporary indexed parquet tables per run. Rejected to avoid sync history complexity and extra disk I/O.

### Decision 2: Target VectorDB Chunk Cleanup During Operator Transform
- **Rationale**: Output operators (VectorDB) know their chunk primary key schema and query mechanisms. During execution, `VectorDBOperator` queries `incremental_service.get_soft_deleted_doc_ids(job_id=self.job_id)`, resolves matching chunk PKs via `adapter.get_chunk_ids_for_documents(soft_deleted_ids)`, and deletes them via `adapter.delete_documents_by_ids()`.
- **Failure Rollback**: If chunk deletion raises an exception, the operator catches it, invokes `incremental_service.unmark_soft_deleted_docs(job_id=self.job_id)`, and re-raises `FlowExecutionFailedException` to fail the run.

### Decision 3: Post-Execution Purge on Pipeline Success
- **Rationale**: Once the full DAG completes and reaches terminal `ExecutionStatus.SUCCEEDED` (in `AbstractOrchestrator._finalize_dag_flow`), the orchestrator triggers `incremental_service.purge_soft_deleted_docs(job_id=self.job_id)`.
- **Alternatives Considered**: Purging immediately in the ingest step. Rejected because downstream operators need soft-deleted IDs to delete target chunks first.

## Risks / Trade-offs

- **[Risk]** Empty ingestion batch with pending soft deletions might skip downstream nodes.
  - **Mitigation**: When `ingested_table.num_rows == 0`, check if soft-deleted doc IDs exist. If present, pass an empty table to downstream output operators to ensure chunk cleanup runs.
- **[Risk]** Partial vector chunk deletion failure could leave inconsistent metadata state.
  - **Mitigation**: Unmark soft-deleted documents in metadata store on any vector store deletion failure and mark the job run status as `FAILED`.
