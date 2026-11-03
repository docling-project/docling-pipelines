# Spec Delta: backend/vectordb-operator

## MODIFIED Requirements

### Requirement: Vector dimension auto-detection
The operator SHALL inspect configured vector features in `available_features` and automatically detect vector dimensions from in-memory arrays or memory-mapped embedding files for all dense and binary vector columns. For binary vector columns the detected dimension SHALL be the number of bits (`len(bytes) * 8`), and rows holding empty byte strings SHALL be skipped.

#### Scenario: Dense embeddings dimension detection
- **WHEN** one or more dense embedding columns are present in `available_features`
- **THEN** the operator detects dimensions for each column and maps them to their respective target vector fields

#### Scenario: Binary embeddings dimension detection
- **WHEN** a binary vector column holds packed-bit `bytes` values (in memory or in a memory-mapped embedding file)
- **THEN** the detected dimension is the byte length of the first non-empty value multiplied by 8

#### Scenario: Empty byte strings are skipped
- **WHEN** the first rows of a binary vector column hold empty `bytes` values (for example chunks without an embedding)
- **THEN** dimension detection uses the first non-empty value instead of reporting a dimension of 0

#### Scenario: Dimension detection failure
- **WHEN** vector dimensions cannot be determined from the table or embedding metadata
- **THEN** the transform fails with node status `FAILED` and records failures for all input documents

### Requirement: Sparse and hybrid vector indexing
The operator SHALL support pure dense vectors, pure sparse vectors (BM25), pure binary vectors, dual dense-sparse hybrid vector configurations via `add_sparse_vector`, and multi-vector configurations combining dense and binary vectors.

#### Scenario: Pure sparse vector mode
- **WHEN** `add_sparse_vector` is enabled and no dense vector columns are configured
- **THEN** the operator creates sparse vector fields and indexes documents without requiring dense embeddings

#### Scenario: Hybrid dense and sparse vector mode
- **WHEN** `add_sparse_vector` is enabled and dense vector columns are configured
- **THEN** the operator indexes both dense vector embeddings and sparse text representations into the target vector store

#### Scenario: Pure binary vector mode
- **WHEN** a binary vector feature is available for Milvus
- **THEN** the operator creates a `BINARY_VECTOR` field and indexes the byte-packed embeddings using binary indexing algorithms

#### Scenario: Multi-vector hybrid binary and dense mode
- **WHEN** both binary vector and dense float vector features are available for Milvus
- **THEN** the operator creates a collection with both binary and float vector fields and indexes both representations for hybrid and two-stage retrieval

## ADDED Requirements

### Requirement: Binary vector field classification and flow validation
The operator SHALL decide whether a vector field is binary only from the type of its feature (`vector_binary` or `vector_type: "binary"`), never from `index_type` or `metric_type`, and flow validation SHALL reject combinations that cannot work before any collection is created.

#### Scenario: Field kind is decided by feature type, not index configuration
- **WHEN** a vector feature has type `vector` and `index_type` is a `BIN_*` index
- **THEN** the field is still created as `FLOAT_VECTOR`; the operator never infers binary from `index_type`, and fails with an invalid-configuration error if the collection has no binary field to use that index

#### Scenario: Flow validation rejects a binary index without a binary vector feature
- **WHEN** a flow is validated and the Milvus `index_type` is a `BIN_*` index while no upstream feature has type `vector_binary`
- **THEN** validation fails with an invalid-configuration error naming the `quantization` setting of the embeddings operator, before any collection is created

#### Scenario: Flow validation rejects binary vector features for OpenSearch
- **WHEN** a flow is validated and an OpenSearch VectorDB node receives an upstream feature of type `vector_binary` (for example from `EmbeddingsOperator` with `quantization` of `binary` or `ubinary`)
- **THEN** validation fails with an invalid-configuration error stating that binary vector features are not supported by OpenSearch, instead of silently creating a `text` field

### Requirement: Binary quantization of embeddings
`EmbeddingsOperator` SHALL support a node-level `quantization` setting (`none`, `binary`, `ubinary`) that converts float embeddings into packed 1-bit vectors and SHALL expose the resulting `embeddings` feature as `vector_binary`. The setting is read from the embeddings node configuration, not from `global_config`.

#### Scenario: Binary quantization types the embeddings feature
- **WHEN** `EmbeddingsOperator` is configured with `quantization` of `binary` or `ubinary` on its node
- **THEN** feature propagation exposes the embeddings feature as `vector_binary` so downstream VectorDB nodes create a `BINARY_VECTOR` field

#### Scenario: Quantized output format
- **WHEN** an embedding of dimension `d` is quantized
- **THEN** the output is a `bytes` value of `ceil(d / 8)` bytes using sign thresholding (`value > 0`) and `numpy.packbits`, and file-backed embeddings record the dimension in bits with dtype `packed_bits`

#### Scenario: Unsupported quantization value
- **WHEN** `quantization` is not one of `none`, `binary` or `ubinary`
- **THEN** the operator raises an invalid-configuration error listing the supported values

### Requirement: Milvus binary index and metric configuration
The Milvus adapter SHALL support binary vector index algorithms (`BIN_FLAT`, `BIN_IVF_FLAT`) and binary similarity metrics (`HAMMING`, `JACCARD`), which are the binary metrics supported by Milvus 2.6.

#### Scenario: Configured BIN_IVF_FLAT index with HAMMING distance
- **WHEN** `index_type="BIN_IVF_FLAT"` and `metric_type="HAMMING"` with custom `nlist` parameters are configured
- **THEN** the Milvus adapter creates the collection index using `BIN_IVF_FLAT` and `HAMMING` metric with the specified parameters

#### Scenario: Configured BIN_FLAT index with JACCARD metric
- **WHEN** `index_type="BIN_FLAT"` and `metric_type="JACCARD"` are configured
- **THEN** the Milvus adapter creates the collection index using exact binary flat scanning and the `JACCARD` similarity metric

#### Scenario: Dense index configured for a collection with a binary field
- **WHEN** `index_type` is a dense index (e.g. `HNSW`) and the collection contains a binary vector field
- **THEN** the dense field uses the configured index, metric and parameters and the binary field is indexed with `BIN_FLAT` and `HAMMING`

#### Scenario: Binary index configured for a mixed collection
- **WHEN** `index_type` is a `BIN_*` index and the collection contains both a binary and a dense vector field
- **THEN** the binary field uses the configured index, binary metric and parameters and the dense field is indexed with `HNSW` and `L2` defaults, and a warning is logged when configured dense settings were replaced

#### Scenario: Dense index with binary-only metric
- **WHEN** `index_type` is a dense index and `metric_type` is one of `HAMMING`, `JACCARD`
- **THEN** initialization fails with an invalid-configuration error

#### Scenario: Binary metric removed in Milvus 2.6
- **WHEN** `metric_type` is `TANIMOTO`, `SUBSTRUCTURE` or `SUPERSTRUCTURE`
- **THEN** validation fails with an invalid-configuration error before any collection is created

### Requirement: Milvus binary vector dimension and data format validation
The Milvus adapter SHALL enforce that binary vector dimensions represent total bit counts divisible by 8 and that document values are ingested as raw byte sequences.

#### Scenario: Valid binary vector dimension
- **WHEN** a binary vector field has a bit dimension divisible by 8 (e.g. 128, 256, 768, 1536)
- **THEN** the field schema is created with the exact bit dimension and byte payloads of length `dim / 8` are inserted

#### Scenario: Invalid binary vector dimension not divisible by 8
- **WHEN** a binary vector field configuration specifies a dimension not divisible by 8
- **THEN** collection creation fails with a validation error indicating binary vector dimensions must be multiples of 8

#### Scenario: Batch sizing with binary payloads
- **WHEN** documents carry `bytes` vector values
- **THEN** batch size estimation counts each value by its byte length so batches split in proportion to the real payload

### Requirement: Milvus Lite binary vector restriction enforcement
The Milvus adapter SHALL reject binary vector field creation and binary index types when running under Milvus Lite (`auth_type: "lite"`).

#### Scenario: Binary vector configured with Milvus Lite
- **WHEN** `auth_type="lite"` is configured alongside binary vector fields or binary index types (`BIN_FLAT`, `BIN_IVF_FLAT`)
- **THEN** adapter initialization or collection creation raises an invalid configuration exception stating that binary vectors are not supported by Milvus Lite
