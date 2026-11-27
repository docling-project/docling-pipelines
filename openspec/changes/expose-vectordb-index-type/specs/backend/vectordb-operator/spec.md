# Spec Delta

## ADDED Requirements

### Requirement: Sparse index types are not selectable for Milvus
The Milvus `index_type` provider setting SHALL accept only index types that can be used for a dense, GPU or binary vector field. `SPARSE_INVERTED_INDEX` and `SPARSE_WAND` SHALL NOT be accepted, because the sparse field always uses a fixed `SPARSE_INVERTED_INDEX` with `BM25`.

#### Scenario: Sparse index type rejected at schema validation
- **WHEN** a Milvus `provider_config` sets `index_type` to `SPARSE_INVERTED_INDEX` or `SPARSE_WAND`
- **THEN** flow validation fails with an error naming `index_type` and listing the accepted values

#### Scenario: Operator metadata omits sparse index types
- **WHEN** `GET /api/v1/operators/metadata` is called
- **THEN** the Milvus `index_type` `valid_values` contain `FLAT`, `IVF_FLAT`, `IVF_SQ8`, `IVF_PQ`, `HNSW`, `DISKANN`, `AUTOINDEX`, `GPU_CAGRA`, `GPU_IVF_FLAT`, `GPU_IVF_PQ`, `GPU_BRUTE_FORCE`, `BIN_FLAT`, `BIN_IVF_FLAT` and no sparse type

#### Scenario: Accepted values match the supported dense, GPU and binary types
- **WHEN** the accepted `index_type` values are compared with the dense, GPU and binary index types the Milvus adapter supports
- **THEN** the two sets are identical, so a supported type is never unselectable and an unsupported type is never selectable

#### Scenario: Hybrid collection still uses the fixed sparse index
- **WHEN** `add_sparse_vector=true` is configured with a valid dense `index_type`
- **THEN** the sparse field is still indexed with `SPARSE_INVERTED_INDEX` and `BM25`

### Requirement: Index selection applicability metadata
The operator metadata SHALL describe when each Milvus `index_type` and OpenSearch `algorithm` applies, in an additive `applicability` block under the matching `providers` entry. The existing `valid_values` and `default` of every attribute SHALL NOT change.

#### Scenario: Milvus index families and metrics
- **WHEN** `GET /api/v1/operators/metadata` is called
- **THEN** `providers.milvus.applicability` lists the families `cpu_dense` (`FLAT`, `IVF_FLAT`, `IVF_SQ8`, `IVF_PQ`, `HNSW`, `DISKANN`, `AUTOINDEX`; metrics `L2`, `IP`, `COSINE`), `gpu` (`GPU_CAGRA`, `GPU_IVF_FLAT`, `GPU_IVF_PQ`, `GPU_BRUTE_FORCE`; metrics `L2`, `IP`) and `binary` (`BIN_FLAT`, `BIN_IVF_FLAT`; metrics `HAMMING`, `JACCARD`)

#### Scenario: Binary family requires a binary feature
- **WHEN** the metadata is read
- **THEN** the `binary` family is marked as requiring an upstream feature of type `vector_binary`, and the `cpu_dense` and `gpu` families as applying to features of type `vector`

#### Scenario: Milvus Lite subset and default
- **WHEN** the metadata is read
- **THEN** `providers.milvus.applicability` states that `auth_type` `lite` allows only `FLAT` and defaults to `FLAT`

#### Scenario: OpenSearch engine to algorithm map
- **WHEN** the metadata is read
- **THEN** `providers.opensearch.applicability` maps `faiss` to `hnsw` and `ivf`, and `lucene`, `nmslib` and `jvector` to `hnsw` only

#### Scenario: Existing metadata is unchanged
- **WHEN** the metadata is read before and after this change
- **THEN** every existing attribute keeps the same `valid_values` and `default`, except the Milvus `index_type` `valid_values`, which lose the two sparse types

#### Scenario: Applicability matches the adapter validation
- **WHEN** an `index_type`, `metric_type` or `algorithm` combination is allowed by the `applicability` block for a given context
- **THEN** flow validation of the same combination reports no index-related error

### Requirement: Stored index type in resource metadata
For the Milvus and OpenSearch providers, `stored_resource_metadata` returned by flow enrichment SHALL include an `index_type` entry holding the index algorithm of an existing resource, or `null` when it cannot be determined. For Milvus it is the index type of the dense vector field; for OpenSearch it is the stored `algorithm`.

#### Scenario: Existing Milvus collection
- **WHEN** enrichment selects an existing Milvus collection whose dense vector field has an index of type `IVF_FLAT`
- **THEN** `stored_resource_metadata.index_type` is `IVF_FLAT`

#### Scenario: Existing OpenSearch index
- **WHEN** enrichment selects an existing OpenSearch index created with the `ivf` algorithm
- **THEN** `stored_resource_metadata.index_type` is `ivf`

#### Scenario: Index type unknown
- **WHEN** the selected resource has no readable index information, or no resource is selected
- **THEN** `stored_resource_metadata.index_type` is `null` and the existing `vector_similarity` and `dimension_size` entries are unaffected

#### Scenario: Unreachable vector store
- **WHEN** the vector store is unreachable during enrichment
- **THEN** the fallback `stored_resource_metadata` includes `index_type` as `null`

### Requirement: Milvus Lite default index type
When `auth_type` is `lite` and the user did not set `index_type`, the Milvus adapter SHALL use `FLAT`, so a Lite deployment works without an explicit index type. An explicitly set `index_type` SHALL be honored and validated as before.

#### Scenario: Lite without an index type
- **WHEN** a Milvus `provider_config` has `auth_type="lite"` and no `index_type`
- **THEN** flow validation passes and the collection index is created with `FLAT`

#### Scenario: Lite with an explicit unsupported index type
- **WHEN** `auth_type="lite"` and `index_type="HNSW"` are both set explicitly
- **THEN** flow validation fails with an error stating that `HNSW` is not supported by Milvus Lite and that `FLAT` is

#### Scenario: Non-Lite default is unchanged
- **WHEN** `auth_type` is not `lite` and `index_type` is not set
- **THEN** the index type is `HNSW` as before

### Requirement: Index configuration mismatches are reported by flow validation
Flow validation SHALL report an OpenSearch `engine`/`algorithm` mismatch and a Milvus index type that does not fit its metric type, deployment or upstream feature types, naming the offending values and the accepted alternatives, before any index or collection is created.

#### Scenario: OpenSearch algorithm not supported by the engine
- **WHEN** an OpenSearch node sets `engine="lucene"` and `algorithm="ivf"`
- **THEN** validation fails with an error naming both values and stating that `lucene` supports only `hnsw`

#### Scenario: Milvus index type with an incompatible metric
- **WHEN** a Milvus node sets a GPU `index_type` with `metric_type="COSINE"`, or a binary `index_type` with `metric_type="L2"`
- **THEN** validation fails with an error naming the index type, the metric and the metrics the index family accepts

#### Scenario: Milvus index type with an unsupported deployment or feature set
- **WHEN** a Milvus node sets a `BIN_*` index with no upstream `vector_binary` feature, or a GPU or non-`FLAT` index with `auth_type="lite"`
- **THEN** validation fails with an error naming the index type and the reason

#### Scenario: Valid selection from the applicability metadata
- **WHEN** a Milvus or OpenSearch node uses an `index_type` / `algorithm` and metric offered by the `applicability` block for its context
- **THEN** flow validation reports no error for that combination
