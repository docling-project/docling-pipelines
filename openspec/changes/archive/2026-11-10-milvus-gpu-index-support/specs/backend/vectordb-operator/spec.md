# Spec Delta

## Purpose

Extends the VectorDB operator specification for the Milvus adapter with the `vector_mode` option and GPU index types.

## ADDED Requirements

### Requirement: Milvus vector mode

The Milvus adapter SHALL accept `vector_mode` with the values `dense`, `sparse`, `binary` and `gpu`. When `vector_mode` is not provided, the adapter SHALL resolve it from `add_sparse_vector` (`true` -> `sparse`), then from `index_type` (`BIN_*` -> `binary`, `GPU_*` -> `gpu`), and otherwise use `dense`.

#### Scenario: Explicit vector mode
- **WHEN** `vector_mode="gpu"` is configured
- **THEN** the adapter uses the GPU mode regardless of `add_sparse_vector`

#### Scenario: Legacy sparse flag
- **WHEN** `vector_mode` is unset and `add_sparse_vector=true`
- **THEN** the adapter resolves `vector_mode="sparse"`

#### Scenario: Conflicting sparse flag
- **WHEN** `add_sparse_vector=true` is configured together with a `vector_mode` other than `sparse`
- **THEN** the adapter raises a `DocpipeException` (status 400, `OPERATOR_CONFIGURATION_INVALID`)

#### Scenario: Unknown vector mode
- **WHEN** `vector_mode` is not one of `dense`, `sparse`, `binary`, `gpu`
- **THEN** the adapter raises a `DocpipeException` (status 400, `OPERATOR_CONFIGURATION_INVALID`)

### Requirement: Milvus GPU index types

The Milvus adapter SHALL accept the index types `GPU_CAGRA`, `GPU_IVF_FLAT`, `GPU_IVF_PQ` and `GPU_BRUTE_FORCE` in `vector_mode="gpu"` for standalone and remote Milvus deployments. The adapter SHALL NOT probe the host running the pipeline for a GPU and SHALL NOT change an explicitly configured index type based on local hardware.

#### Scenario: GPU index type is sent to the server as configured
- **WHEN** `vector_mode="gpu"` and `index_type="GPU_CAGRA"` are configured
- **THEN** the collection index is created with `GPU_CAGRA` and its default or configured parameters, regardless of the GPU hardware on the pipeline host

#### Scenario: CPU index type rejected in GPU mode
- **WHEN** `vector_mode="gpu"` is configured with `index_type="HNSW"`
- **THEN** the adapter raises a `DocpipeException` (status 400) listing the supported GPU index types

#### Scenario: GPU index type rejected for Milvus Lite
- **WHEN** a GPU index type is configured with `auth_type="lite"`
- **THEN** the adapter raises a `DocpipeException` (status 400) stating that GPU indexes are not supported by Milvus Lite

### Requirement: Milvus GPU metric and parameter validation

The adapter SHALL validate vector mode, index type, metric type and GPU parameters before connecting to Milvus, so the errors are also reported by flow validation when Milvus is unreachable.

#### Scenario: GPU index rejects COSINE
- **WHEN** `vector_mode="gpu"` is configured with `metric_type="COSINE"`
- **THEN** the adapter raises a `DocpipeException` (status 400, `OPERATOR_CONFIGURATION_INVALID`) suggesting `IP` on normalized vectors or `L2`

#### Scenario: GPU_CAGRA graph degree constraint violated
- **WHEN** `index_type="GPU_CAGRA"` is configured with `graph_degree` greater than `intermediate_graph_degree` after merging defaults and user parameters
- **THEN** the adapter raises a `DocpipeException` (status 400, `OPERATOR_CONFIGURATION_INVALID`)

#### Scenario: GPU_CAGRA non-integer parameter
- **WHEN** `graph_degree` or `intermediate_graph_degree` is neither an integer nor a numeric string
- **THEN** the adapter raises a `DocpipeException` (status 400, `OPERATOR_CONFIGURATION_INVALID`); numeric strings such as `"64"` are compared as integers

#### Scenario: GPU_CAGRA valid parameters accepted
- **WHEN** `index_type="GPU_CAGRA"` is configured with `graph_degree` less than or equal to `intermediate_graph_degree`
- **THEN** the adapter accepts the configuration

#### Scenario: Flow validation without a Milvus connection
- **WHEN** a flow with an invalid configuration is validated and Milvus is not reachable
- **THEN** validation reports the configuration error and no Milvus client is created

### Requirement: Milvus GPU indexes by collection kind

GPU indexes SHALL apply only to dense `FLOAT_VECTOR` fields. Each vector field SHALL be indexed according to its own data type.

#### Scenario: Dense-only collection
- **WHEN** `vector_mode="gpu"` and every vector feature is a dense float vector
- **THEN** each vector field is indexed with the configured GPU index type and metric

#### Scenario: Binary-only collection
- **WHEN** `vector_mode="gpu"` and the only vector features are binary vectors
- **THEN** flow validation fails with a `DocpipeException` stating that GPU indexes only apply to dense float vectors

#### Scenario: Mixed dense and binary collection
- **WHEN** `vector_mode="gpu"` and the collection has both dense and binary vector features
- **THEN** the dense field uses the configured GPU index and the binary field uses `BIN_FLAT` with `HAMMING`

#### Scenario: Sparse-only collection
- **WHEN** `vector_mode="sparse"` and no dense vector feature is present
- **THEN** the GPU, binary and dense index checks are skipped and the sparse field uses `SPARSE_INVERTED_INDEX` with `BM25`

#### Scenario: Hybrid dense and sparse collection
- **WHEN** `vector_mode="sparse"` and a dense vector feature is present
- **THEN** the sparse field uses `SPARSE_INVERTED_INDEX` with `BM25`, and flow validation checks that the configured `index_type` is a CPU dense or GPU index type, that the `metric_type` is valid for that index family, and the `GPU_CAGRA` parameters

#### Scenario: Hybrid collection with invalid dense settings
- **WHEN** `vector_mode="sparse"`, a dense vector feature is present and `index_type="GPU_CAGRA"` is configured with `metric_type="COSINE"` (or `index_type` is not a dense or GPU index type)
- **THEN** flow validation fails with a `DocpipeException` (status 400, `OPERATOR_CONFIGURATION_INVALID`)

#### Scenario: Hybrid collection on Milvus Lite
- **WHEN** `vector_mode="sparse"`, a dense vector feature is present, `auth_type="lite"` and `index_type` is a GPU type or a CPU dense type other than `FLAT`
- **THEN** flow validation fails with a `DocpipeException` (status 400) stating that the index type is not supported by Milvus Lite

#### Scenario: Collection already exists
- **WHEN** the target collection already exists
- **THEN** the collection is not recreated and `vector_mode` and `index_type` are not applied to or compared with its existing indexes; only vector dimensions are validated

### Requirement: Milvus collection cleanup after index failure

When index creation fails after the collection was created, the adapter SHALL drop the collection so that no collection without an index remains.

#### Scenario: Index creation fails
- **WHEN** `create_index` (the sparse or the dense index) fails after `create_collection` succeeded
- **THEN** the adapter drops the collection and raises a `DocpipeException` carrying the original error

#### Scenario: Collection creation fails
- **WHEN** `create_collection` itself fails
- **THEN** no drop is attempted

#### Scenario: Cleanup drop fails
- **WHEN** dropping the collection also fails
- **THEN** the drop failure is logged and the original index error is still raised
