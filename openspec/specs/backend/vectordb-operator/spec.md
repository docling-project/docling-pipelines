# backend/vectordb-operator Specification

## Purpose
The VectorDB operator ingests vectorized chunk embeddings and document metadata from PyArrow tables into supported vector database backends (OpenSearch, Milvus). It supports dense, sparse, and hybrid vector indexing, automatic embedding dimension detection, index/collection lifecycle management, schema validation, stale chunk cleanup, flow enrichment resource introspection, and detailed execution failure metrics.

## Requirements

### Requirement: Operator table and metadata contract
The VectorDB operator SHALL accept a PyArrow table containing a document ID/hash column, chunked text, and vector embedding columns. It SHALL return the input table with execution metadata reporting processed documents, failed document details, indexed chunk counts, and node execution status.

#### Scenario: Successful table transform
- **WHEN** a valid PyArrow table with document IDs, chunks, and embeddings is transformed
- **THEN** the operator indexes the documents into the configured vector store and returns the table with `status="SUCCEEDED"` and `processed_docs` count matching unique input document IDs

#### Scenario: Empty input table
- **WHEN** an empty PyArrow table is provided to the operator
- **THEN** the operator returns the empty table immediately with zero processed documents without issuing database index requests

#### Scenario: Missing required document ID column
- **WHEN** the input table lacks the configured document ID/hash column
- **THEN** the operator logs an error, marks node status as `FAILED`, and returns the table without indexing

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

### Requirement: Index and collection lifecycle management
The operator SHALL manage the target vector store index or collection lifecycle automatically during transform, creating the index/collection when absent and validating schema compatibility when present, without exposing a user-configurable `create_index` option. When legacy configurations provide `create_index`, the operator SHALL log a deprecation warning and proceed with automatic index lifecycle handling.

#### Scenario: Index creation when absent
- **WHEN** the target index or collection does not exist at transform time
- **THEN** the operator creates the index or collection with detected vector dimensions and feature mappings before inserting documents

#### Scenario: Schema validation on existing index
- **WHEN** the target index or collection already exists at transform time
- **THEN** the operator validates the existing schema against detected dimensions and feature mappings without recreating the index

#### Scenario: Index creation disabled
- **WHEN** `create_index` is provided in operator configuration
- **THEN** the operator logs a deprecation warning that `create_index` is deprecated and proceeds with automatic index lifecycle handling

#### Scenario: Index creation or schema validation failure
- **WHEN** index creation or schema validation raises an exception
- **THEN** all unique documents in the batch are recorded as failed with the error reason, `processed_docs` is set to 0, and node status is marked `FAILED`

### Requirement: Stale primary key cleanup
The operator SHALL identify existing document primary keys in the vector database for the file IDs being processed and delete stale chunks prior to inserting updated document chunks.

#### Scenario: Re-indexing updated document
- **WHEN** a document with an existing file ID is indexed with new chunks
- **THEN** any preexisting chunks associated with that file ID that are not part of the new chunk set are deleted from the vector database

### Requirement: Batch document indexing and error isolation
The operator SHALL index documents in batches according to configured batch size, aggregating chunk-level failures and associating them with their corresponding parent document IDs.

#### Scenario: Partial chunk indexing failure
- **WHEN** specific chunks fail during bulk indexing
- **THEN** the parent documents of the failed chunks are recorded in metadata as failed documents, and successful documents are recorded in `processed_docs`

### Requirement: Operator metadata and parameter introspection
The operator SHALL expose its configurable parameters, defaults, and data types via `get_metadata()` for API introspection without including `create_index`.

#### Scenario: Operator metadata query
- **WHEN** `GET /api/v1/operators/metadata` is called
- **THEN** the metadata response includes parameter definitions for provider, doc ID column, vector dimensions, and sparse vector settings, and excludes `create_index`

### Requirement: Vector store resource metadata and flow enrichment
The vector database adapters SHALL provide live resource introspection for flow enrichment endpoints, retrieving available indices/collections, existing schema definitions, and resolving default feature mappings.

#### Scenario: Live resources discovered during enrichment
- **WHEN** flow feature enrichment is requested for a vectordb node with valid connection configuration
- **THEN** available indices or collections are fetched from the vector store and returned in `available_resources`

#### Scenario: Selected resource schema and feature mapping resolution
- **WHEN** an existing index or collection name is selected in provider config
- **THEN** its schema is retrieved in `selected_resource_schema` and feature mappings are aligned with the incoming available features

#### Scenario: Unreachable vector store during enrichment
- **WHEN** the vector database is unreachable or connection fails during enrichment
- **THEN** an empty fallback metadata structure is returned without raising an unhandled exception or breaking flow enrichment

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
The Milvus adapter SHALL reject binary vector field creation and binary index types when running under Milvus Lite (`auth_type: "lite"`), and flow validation SHALL reject a binary vector feature for Lite whatever the configured `index_type` is.

#### Scenario: Binary index type configured with Milvus Lite
- **WHEN** `auth_type="lite"` is configured alongside a binary index type (`BIN_FLAT`, `BIN_IVF_FLAT`)
- **THEN** adapter initialization raises an invalid configuration exception stating that binary vectors are not supported by Milvus Lite

#### Scenario: Binary vector feature with Milvus Lite and a dense index type
- **WHEN** `auth_type="lite"` is configured with `FLAT` and an upstream embeddings operator sets `quantization` to `binary` or `ubinary`
- **THEN** flow validation fails with an invalid configuration exception stating that binary vector features are not supported by Milvus Lite

### Requirement: Soft-deleted document chunk cleanup
When running in an incremental flow with soft-deleted documents present in the incremental metadata repository, the VectorDB operator SHALL resolve all soft-deleted source document IDs to their stored chunk primary keys across configured vector backends (OpenSearch, Milvus) and delete those chunks. If chunk deletion fails, the operator SHALL unmark the soft-deleted records in the incremental repository and fail the operator execution step.

#### Scenario: Soft-deleted source documents chunks removed from vector store
- **WHEN** the VectorDB operator executes and soft-deleted document IDs are present in the incremental repository
- **THEN** all stored chunk primary keys corresponding to those source document IDs are identified and deleted from the vector store

#### Scenario: VectorDB deletion failure triggers unmark rollback
- **WHEN** deleting chunks for soft-deleted documents fails in the vector store
- **THEN** the operator unmarks the soft-deleted records in the incremental metadata repository and raises an exception marking the node status as `FAILED`
