# Spec Delta

## Purpose

Extends the VectorDB operator specification for the Milvus vector store adapter to add:
- A `vector_mode` configuration parameter that replaces the `add_sparse_vector` boolean as the mode-selection mechanism, while retaining `add_sparse_vector` for backward compatibility.
- GPU-accelerated index types (`GPU_CAGRA`, `GPU_IVF_FLAT`, `GPU_IVF_PQ`, `GPU_BRUTE_FORCE`) selectable via `vector_mode="gpu"`.
- Mode-aware index type and metric type validation enforcing GPU-specific metric restrictions.
- A GPU_CAGRA-specific configuration constraint.

## MODIFIED Requirements

### Requirement: Sparse and hybrid vector indexing

The operator SHALL support pure dense vectors, pure sparse vectors (BM25), dual dense-sparse hybrid vector configurations, and GPU-accelerated dense vector indexing. The active mode SHALL be determined by the `vector_mode` parameter (`"dense"`, `"sparse"`, `"binary"`, `"gpu"`). When `vector_mode` is absent, the adapter SHALL derive the mode from `add_sparse_vector` for backward compatibility: `add_sparse_vector=True` maps to `vector_mode="sparse"`, otherwise `vector_mode="dense"`.

#### Scenario: Pure sparse vector mode via vector_mode
- **WHEN** `vector_mode="sparse"` is configured (or `add_sparse_vector=True` with no `vector_mode`)
- **THEN** the operator creates sparse vector fields and indexes documents without requiring dense embeddings, identically to the previous behavior

#### Scenario: Hybrid dense and sparse vector mode via vector_mode
- **WHEN** `vector_mode="sparse"` is configured and dense vector columns are present
- **THEN** the operator indexes both dense vector embeddings and sparse text representations into the target collection

#### Scenario: GPU-accelerated dense indexing
- **WHEN** `vector_mode="gpu"` is configured with a GPU index type (`GPU_CAGRA`, `GPU_IVF_FLAT`, `GPU_IVF_PQ`, or `GPU_BRUTE_FORCE`)
- **THEN** the adapter creates the collection with the requested GPU index type and its configured or default index parameters

#### Scenario: Dense mode (default)
- **WHEN** neither `vector_mode` nor `add_sparse_vector` is specified
- **THEN** the adapter defaults to `vector_mode="dense"` and uses a CPU dense index type (default `HNSW`)

## ADDED Requirements

### Requirement: Milvus GPU index type and metric validation

The Milvus adapter SHALL enforce that GPU index types are only accepted in `vector_mode="gpu"`, and that GPU indexes are restricted to the L2 and IP similarity metrics. COSINE and BM25 metrics SHALL be rejected for GPU mode.

#### Scenario: GPU mode rejects CPU index types
- **WHEN** `vector_mode="gpu"` is configured with a non-GPU index type (e.g. `HNSW`, `IVF_FLAT`)
- **THEN** the adapter raises a `DocpipeException` (status 400) listing the supported GPU index types

#### Scenario: GPU mode rejects COSINE metric
- **WHEN** `vector_mode="gpu"` is configured with `metric_type="COSINE"`
- **THEN** the adapter raises a `DocpipeException` (status 400) stating that GPU indexes support only L2 and IP

#### Scenario: Unknown vector_mode is rejected
- **WHEN** an unrecognized `vector_mode` value is provided
- **THEN** the adapter raises a `DocpipeException` (status 400) listing the supported modes

### Requirement: GPU_CAGRA graph-degree constraint

When `GPU_CAGRA` index type is configured, the adapter SHALL validate that `graph_degree` is less than or equal to `intermediate_graph_degree`. If this constraint is violated, the adapter SHALL raise a `DocpipeException` (status 400) before attempting collection creation.

#### Scenario: GPU_CAGRA graph_degree exceeds intermediate_graph_degree
- **WHEN** `index_parameters` for `GPU_CAGRA` specifies `graph_degree > intermediate_graph_degree`
- **THEN** the adapter raises a `DocpipeException` (status 400) identifying the violated constraint

#### Scenario: GPU_CAGRA valid parameters accepted
- **WHEN** `index_parameters` for `GPU_CAGRA` specifies `graph_degree <= intermediate_graph_degree`
- **THEN** the adapter accepts the configuration and proceeds to collection creation
