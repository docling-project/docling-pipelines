# backend/vectordb-operator Spec Delta

## ADDED Requirements

### Requirement: Soft-deleted document chunk cleanup
When running in an incremental flow with soft-deleted documents present in the incremental metadata repository, the VectorDB operator SHALL resolve all soft-deleted source document IDs to their stored chunk primary keys across configured vector backends (OpenSearch, Milvus) and delete those chunks. If chunk deletion fails, the operator SHALL unmark the soft-deleted records in the incremental repository and fail the operator execution step.

#### Scenario: Soft-deleted source documents chunks removed from vector store
- **WHEN** the VectorDB operator executes and soft-deleted document IDs are present in the incremental repository
- **THEN** all stored chunk primary keys corresponding to those source document IDs are identified and deleted from the vector store

#### Scenario: VectorDB deletion failure triggers unmark rollback
- **WHEN** deleting chunks for soft-deleted documents fails in the vector store
- **THEN** the operator unmarks the soft-deleted records in the incremental metadata repository and raises an exception marking the node status as `FAILED`
