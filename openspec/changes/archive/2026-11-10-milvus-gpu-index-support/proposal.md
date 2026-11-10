# Proposal

## Why

The Milvus adapter only supports CPU dense, sparse and binary vector indexes. Milvus also provides GPU-accelerated index types (`GPU_CAGRA`, `GPU_IVF_FLAT`, `GPU_IVF_PQ`, `GPU_BRUTE_FORCE`) that give higher query throughput on large document collections. None of these can be selected today.

GPU indexes are an index-type concern only. The collection schema (`FLOAT_VECTOR`), wire format and ingestion path are the same as for CPU dense vectors.

## What Changes

- **New**: `MilvusVectorModes` (`dense`, `sparse`, `binary`, `gpu`) and the `vector_mode` provider option. When unset, the mode is inferred (`add_sparse_vector=true` -> `sparse`, `BIN_*` index -> `binary`, `GPU_*` index -> `gpu`, otherwise `dense`), so existing flows keep working.
- **New**: GPU index types `GPU_CAGRA`, `GPU_IVF_FLAT`, `GPU_IVF_PQ`, `GPU_BRUTE_FORCE` (`MilvusIndexTypes.ALL_GPU_TYPES`) with default parameters in `INDEX_DEFAULT_PARAMETERS`.
- **New**: `MilvusMetricTypes.GPU_VALID_METRICS` (`L2`, `IP`).
- **New**: Mode-aware, connection-free configuration validation (`MilvusIndexManager.validate_index_config`) for vector mode, index type, metric type and the `GPU_CAGRA` `graph_degree <= intermediate_graph_degree` constraint. `MilvusAdapter` runs it before connecting, so `/validate_flow` reports these errors even when Milvus is unreachable.
- **New**: `MilvusIndexManager.validate_vector_feature_types` rejects `vector_mode=gpu` when the only vector features are binary.
- **Changed**: `MilvusIndexManager.create_collection` drops the collection when index creation fails after the collection was created, so no index-less collection is left behind.
- **Changed**: `MilvusIndexManager` takes `vector_mode` instead of `add_sparse_vector`. `ADD_SPARSE_VECTOR` stays for backward compatibility and maps to `vector_mode="sparse"`.
- **Modified**: `docs/operators/vectordb/milvus.md` and `docs/reference/OPERATORS.md` document the new options and limits.
- **Added**: `sample_flows/vectordb/milvus_gpu_integration.json`.

## Capabilities

### New Capabilities

None. This extends the existing VectorDB operator Milvus adapter.

### Modified Capabilities

- `backend/vectordb-operator`: the Milvus adapter accepts `vector_mode` and GPU index types. Behavior of existing dense, sparse, hybrid and binary configurations is unchanged.

## Impact

- **Backend only.** No frontend, API route or domain model changes. `batch_processor.py`, `vectordb_operator.py` and `vectordb_utils.py` are unchanged.
- **Files changed**: `index_manager.py`, `adapter.py`, `config.py` (Milvus adapter), `operator_constants.py`, Milvus unit tests, `docs/operators/vectordb/milvus.md`, `docs/reference/OPERATORS.md`, `sample_flows/vectordb/milvus_gpu_integration.json`.
- **No breaking changes.** `vector_mode` defaults to the inferred mode, so existing flows behave as before.
- **Dependencies**: none. GPU indexes need a Milvus server built with GPU support (`milvusdb/milvus:<version>-gpu`); no client-side GPU is needed.
