# Tasks

## 1. Incremental Metadata Store and Service

- [x] 1.1 [backend] Add `unmark_soft_deleted_docs` and `purge_soft_deleted_docs` methods to `IncrementalMetadataStore` port and verify interface definitions
- [x] 1.2 [backend] Implement `unmark_soft_deleted_docs` and `purge_soft_deleted_docs` in `FilesystemIncrementalStore` with file lock safety and verify with unit tests
- [x] 1.3 [backend] Implement `unmark_soft_deleted_docs` and `purge_soft_deleted_docs` in `PostgresIncrementalStore` with transaction safety and verify with unit tests
- [x] 1.4 [backend] Update `IncrementalUpdateService` with `unmark_soft_deleted_docs`, `purge_soft_deleted_docs`, and updated `process_ingested_docs` logic; verify with unit tests

## 2. VectorDB Operator Deletion Cleanup

- [x] 2.1 [backend] Update `VectorDBOperator` to query soft-deleted documents from `IncrementalUpdateService`, resolve chunk IDs, and delete them from the vector store
- [x] 2.2 [backend] Add rollback error handling in `VectorDBOperator` to unmark soft-deleted documents in incremental store if vector store deletion fails
- [x] 2.3 [backend] Verify `VectorDBOperator` deletion and rollback behavior with unit tests

## 3. Orchestration Engine Lifecycle Integration

- [x] 3.1 [backend] In `AbstractOrchestrator._finalize_dag_flow`, trigger `purge_soft_deleted_docs` upon successful flow completion
- [x] 3.2 [backend] In `AbstractOrchestrator.execute_flow`, when zero documents are ingested but soft-deleted documents are pending, ensure downstream output operators run their cleanup step
- [x] 3.3 [backend] Verify end-to-end orchestration flow execution with unit tests

## 4. Verification and Validation

- [x] 4.1 [backend] Run all incremental metadata, vectordb, and orchestrator unit tests to ensure all tests pass cleanly
