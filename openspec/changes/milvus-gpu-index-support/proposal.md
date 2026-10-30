# Proposal

## Why

The Milvus adapter currently only supports CPU-based dense, sparse, and hybrid vector indexes. Milvus provides GPU-accelerated index types (`GPU_CAGRA`, `GPU_IVF_FLAT`, `GPU_IVF_PQ`, `GPU_BRUTE_FORCE`) that deliver significantly higher throughput and lower query latency for large-scale document datasets, but they are absent from the adapter entirely. Additionally, the current `add_sparse_vector` boolean does not scale as a mode-selection mechanism: it conflates sparse indexing with dense indexing in a single flag, making it impossible to extend to GPU or binary modes without adding more ad-hoc booleans.

## What Changes

- **New**: `MilvusVectorModes` class in `index_manager.py` with modes `dense`, `sparse`, `binary`, and `gpu`, plus `ALL_MODES`.
- **New**: GPU index type constants added to `MilvusIndexTypes`: `GPU_CAGRA`, `GPU_IVF_FLAT`, `GPU_IVF_PQ`, `GPU_BRUTE_FORCE`, collected in `ALL_GPU_TYPES`. Included in the existing `ALL_TYPES` list.
- **New**: `GPU_VALID_METRICS` on `MilvusMetricTypes` (L2 and IP only — Milvus GPU indexes do not support COSINE).
- **New**: Default index parameters for all four GPU index types in `INDEX_DEFAULT_PARAMETERS`.
- **New**: `VECTOR_MODE` and `VECTOR_MODE_DEFAULT` constants in `operator_constants.py`.
- **Modified**: `MilvusIndexManager.__init__` replaces the `add_sparse_vector` parameter with `vector_mode`. Internal `_is_sparse`, `_is_gpu`, and `_is_binary` flags are derived from the mode.
- **New**: `_validate_vector_mode()`, updated `_validate_index_type()` (mode-aware), updated `_validate_metric_type()` (mode-aware), and `_validate_gpu_config()` (GPU_CAGRA graph-degree constraint) added to `MilvusIndexManager`.
- **Modified**: All `self.add_sparse_vector` references inside `index_manager.py` replaced with `self._is_sparse` — no behavioral change for existing sparse/dense/hybrid users.
- **Modified**: `adapter.py` adds `_resolve_vector_mode()` to resolve `vector_mode` from config (with backward-compat mapping from legacy `add_sparse_vector=True → vector_mode="sparse"`). Passes `vector_mode` to `MilvusIndexManager`; continues passing the computed `add_sparse_vector` boolean to `MilvusBatchProcessor` unchanged.
- **Modified**: `MilvusConfig.index_type` Literal expanded to include the four GPU index type strings.
- **New**: Unit tests in `test_milvus_index_manager.py` covering GPU initialization, invalid CPU index in GPU mode, COSINE rejection for GPU, GPU_CAGRA constraint, valid custom GPU_CAGRA parameters, GPU default parameters, and unknown mode rejection. Existing index-type and metric-type count assertions updated.
- **Modified**: `docs/reference/OPERATORS.md` updated with `vector_mode`, GPU index types, GPU metric restrictions, and backward compatibility note.

## Capabilities

### New Capabilities

None. GPU index support is a direct extension of the existing VectorDB operator's Milvus adapter; it does not introduce a new independently observable system capability.

### Modified Capabilities

- `backend/vectordb-operator`: The VectorDB operator's Milvus adapter gains a new `vector_mode` configuration parameter and supports GPU-accelerated index types. The behavioral contract for existing dense, sparse, and hybrid modes is unchanged. The `add_sparse_vector` parameter is retained for backward compatibility.

## Impact

- **Backend only** — no frontend, API route, or domain model changes.
- **Files changed**: `src/docpipe/core/operators/vectordb/adapters/outbound/milvus/index_manager.py`, `adapter.py`, `config.py`; `src/docpipe/core/constants/operator_constants.py`; `tests/unit/operators/vectordb/test_milvus_index_manager.py`; `docs/reference/OPERATORS.md`.
- **Files unchanged**: `batch_processor.py`, `vectordb_operator.py`, `vectordb_utils.py`, domain models, OpenSearch adapter.
- **No breaking changes** for existing flow configurations using `add_sparse_vector`, `index_type`, or `metric_type`.
- **Dependency**: No new Python packages required. GPU index types are already supported by `pymilvus`; GPU execution requires a Milvus deployment built with GPU support and appropriate CUDA drivers on the Milvus server — not the client.
