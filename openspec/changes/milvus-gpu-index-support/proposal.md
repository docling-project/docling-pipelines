# Proposal

## Why

The Milvus adapter only supports CPU dense, sparse and binary vector indexes. Milvus also provides GPU-accelerated index types (`GPU_CAGRA`, `GPU_IVF_FLAT`, `GPU_IVF_PQ`, `GPU_BRUTE_FORCE`) and quantized HNSW variants (`HNSW_SQ`, `HNSW_PQ`, `HNSW_PRQ`) that give higher query throughput or lower memory use on large document collections. None of these can be selected today.

## What Changes

- **New**: GPU index types `GPU_CAGRA`, `GPU_IVF_FLAT`, `GPU_IVF_PQ`, `GPU_BRUTE_FORCE` in `MilvusIndexTypes` (`ALL_GPU_TYPES`), included in `ALL_DENSE_TYPES` and `ALL_TYPES`, with default parameters in `INDEX_DEFAULT_PARAMETERS`.
- **New**: Quantized HNSW index types `HNSW_SQ`, `HNSW_PQ`, `HNSW_PRQ` with default parameters.
- **New**: `MilvusConfig` fields `quantization` (`SQ8`, `PQ`, `PRQ`, `NONE`), `quantization_parameters`, `use_gpu` and `fallback_to_cpu`, forwarded from `MilvusAdapter` to `MilvusIndexManager`. Constants `QUANTIZATION`, `QUANTIZATION_PARAMETERS`, `USE_GPU`, `FALLBACK_TO_CPU` added to `OperatorConstants.VectorDB`.
- **New**: `MilvusIndexManager.resolve_quantized_index_type()` maps a base index type and `quantization` to the quantized index type.
- **New**: `use_gpu=True` upgrades a CPU index (applied after quantization is resolved) to its GPU equivalent; `use_gpu=False` downgrades a GPU index to its CPU equivalent. Index parameters that belong to the previous index type are dropped.
- **New**: Opt-in `fallback_to_cpu`. When enabled and the Milvus server rejects a GPU index during index creation, the index is created with the CPU equivalent instead.
- **New**: Config-time validation: GPU indexes reject the `COSINE` metric; `GPU_CAGRA` requires `intermediate_graph_degree >= graph_degree`; GPU index types are rejected for Milvus Lite.
- **Modified**: `docs/operators/vectordb/milvus.md` and `docs/reference/OPERATORS.md` document the new options, GPU prerequisites and limits.
- **Added**: `sample_flows/vectordb/milvus_gpu_integration.json`.

## Capabilities

### New Capabilities

None. This extends the existing VectorDB operator Milvus adapter.

### Modified Capabilities

- `backend/vectordb-operator`: the Milvus adapter accepts GPU and quantized index types and the new configuration fields. Behavior of existing dense, sparse, hybrid and binary configurations is unchanged.

## Impact

- **Backend only.** No frontend, API route or domain model changes.
- **Files changed**: `index_manager.py`, `adapter.py`, `config.py` (Milvus adapter), `operator_constants.py`, `tests/unit/operators/vectordb/test_milvus_index_manager.py`, `tests/unit/operators/vectordb/test_milvus_adapter.py`, `docs/operators/vectordb/milvus.md`, `docs/reference/OPERATORS.md`, `sample_flows/vectordb/milvus_gpu_integration.json`, `.gitignore`.
- **No breaking changes.** All new fields default to unset or `false`, so existing flows behave as before.
- **Dependencies**: none. GPU indexes need a Milvus server built with GPU support (`milvusdb/milvus:<version>-gpu`); no client-side GPU is needed.
