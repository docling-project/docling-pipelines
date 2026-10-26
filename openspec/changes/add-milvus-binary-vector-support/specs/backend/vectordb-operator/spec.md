# Spec Delta: backend/vectordb-operator

## MODIFIED Requirements

### Requirement: Sparse and hybrid vector indexing
The operator SHALL support pure dense vectors, pure sparse vectors (BM25), pure binary vectors, and multi-vector hybrid configurations combining dense, binary, and sparse vectors.

#### Scenario: Pure sparse vector mode
- **WHEN** `add_sparse_vector` is enabled and no dense vector columns are configured
- **THEN** the operator creates sparse vector fields and indexes documents without requiring dense embeddings

#### Scenario: Hybrid dense and sparse vector mode
- **WHEN** `add_sparse_vector` is enabled and dense vector columns are configured
- **THEN** the operator indexes both dense vector embeddings and sparse text representations into the target vector store

#### Scenario: Pure binary vector mode
- **WHEN** binary vector fields or binary quantization is configured for Milvus
- **THEN** the operator creates binary vector fields with `BINARY_VECTOR` data type and indexes byte-packed embeddings using binary indexing algorithms

#### Scenario: Multi-vector hybrid binary and dense mode
- **WHEN** both binary vector and dense float vector columns are configured for Milvus
- **THEN** the operator creates a collection with both binary and float vector fields and indexes both representations for hybrid and two-stage retrieval

## ADDED Requirements

### Requirement: Milvus binary index and metric configuration
The Milvus adapter SHALL support binary vector index algorithms (`BIN_FLAT`, `BIN_IVF_FLAT`) and binary similarity metrics (`HAMMING`, `JACCARD`, `TANIMOTO`, `SUBSTRUCTURE`, `SUPERSTRUCTURE`).

#### Scenario: Configured BIN_IVF_FLAT index with HAMMING distance
- **WHEN** `index_type="BIN_IVF_FLAT"` and `metric_type="HAMMING"` with custom `nlist` parameters are configured
- **THEN** the Milvus adapter creates the collection index using `BIN_IVF_FLAT` and `HAMMING` metric with the specified parameters

#### Scenario: Configured BIN_FLAT index with JACCARD metric
- **WHEN** `index_type="BIN_FLAT"` and `metric_type="JACCARD"` are configured
- **THEN** the Milvus adapter creates the collection index using exact binary flat scanning and the `JACCARD` similarity metric

### Requirement: Milvus binary vector dimension and data format validation
The Milvus adapter SHALL enforce that binary vector dimensions represent total bit counts divisible by 8 and that document values are ingested as raw byte sequences.

#### Scenario: Valid binary vector dimension
- **WHEN** a binary vector field has a bit dimension divisible by 8 (e.g. 128, 256, 768, 1536)
- **THEN** the field schema is created with the exact bit dimension and byte payloads of length `dim / 8` are inserted

#### Scenario: Invalid binary vector dimension not divisible by 8
- **WHEN** a binary vector field configuration specifies a dimension not divisible by 8
- **THEN** collection creation fails with a validation error indicating binary vector dimensions must be multiples of 8

### Requirement: Milvus Lite binary vector restriction enforcement
The Milvus adapter SHALL reject binary vector field creation and binary index types when running under Milvus Lite (`auth_type: "lite"`).

#### Scenario: Binary vector configured with Milvus Lite
- **WHEN** `auth_type="lite"` is configured alongside binary vector fields or binary index types (`BIN_FLAT`, `BIN_IVF_FLAT`)
- **THEN** adapter initialization or collection creation raises an invalid configuration exception stating that binary vectors are not supported by Milvus Lite
