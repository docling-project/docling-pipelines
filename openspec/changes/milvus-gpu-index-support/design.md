# Design

## Context

See `proposal.md` for motivation. The Milvus adapter is self-contained in `src/docpipe/core/operators/vectordb/adapters/outbound/milvus/`. The key files are:

- `index_manager.py` — `MilvusIndexManager`, `MilvusIndexTypes`, `MilvusMetricTypes`, `INDEX_DEFAULT_PARAMETERS`
- `adapter.py` — `MilvusAdapter` (wires config → client + index_manager + batch_processor)
- `config.py` — `MilvusConfig` (Pydantic, user-facing)
- `operator_constants.py` — `OperatorConstants.VectorDB.*` string constants

Currently, `MilvusIndexManager` takes an `add_sparse_vector: bool` parameter to switch between dense and sparse modes. All `self.add_sparse_vector` checks inside the class implement conditional logic that would need yet another boolean for each new mode (GPU, binary). GPU index types (`GPU_CAGRA`, `GPU_IVF_FLAT`, `GPU_IVF_PQ`, `GPU_BRUTE_FORCE`) are entirely absent from the type registry, default parameter table, and `MilvusConfig` validation.

## Goals / Non-Goals

**Goals:**
- Replace `add_sparse_vector` with a `vector_mode` enum (`dense`, `sparse`, `binary`, `gpu`) inside `MilvusIndexManager`, deriving internal `_is_sparse`, `_is_gpu`, `_is_binary` flags from it.
- Retain `add_sparse_vector` for backward compatibility at the adapter layer — `MilvusAdapter._resolve_vector_mode()` maps the legacy flag to the new enum.
- Add GPU index type constants and defaults.
- Add mode-aware index-type and metric-type validation.
- Add `GPU_CAGRA`-specific graph-degree constraint check.
- No GPU detection, no CPU fallback, no quantization abstraction, no search parameters — all explicitly out of scope.

**Non-Goals:**
- Any change to `MilvusBatchProcessor`, `VectorDBOperator`, domain models, or OpenSearch.
- GPU detection or automatic CPU fallback logic.
- New Python package dependencies.

## Decisions

### 1. `MilvusVectorModes` class in `index_manager.py`

**Decision**: Introduce `MilvusVectorModes` alongside `MilvusIndexTypes` and `MilvusMetricTypes`. Modes: `DENSE = "dense"`, `SPARSE = "sparse"`, `BINARY = "binary"`, `GPU = "gpu"`, `ALL_MODES = [DENSE, SPARSE, BINARY, GPU]`.

**Why over a plain string or Literal**: Mirrors the existing `MilvusIndexTypes` / `MilvusMetricTypes` pattern used throughout the file. Keeps the valid-modes list authoritative in one place.

### 2. Replace `add_sparse_vector` with `vector_mode` in `MilvusIndexManager.__init__`

**Decision**: Change the `add_sparse_vector: bool = False` parameter to `vector_mode: str = MilvusVectorModes.DENSE`. Derive internal flags:

```python
self._is_sparse: bool = vector_mode == MilvusVectorModes.SPARSE
self._is_gpu: bool    = vector_mode == MilvusVectorModes.GPU
self._is_binary: bool = vector_mode == MilvusVectorModes.BINARY
```

All existing `self.add_sparse_vector` references in the class body become `self._is_sparse`.

**Why single `vector_mode` over three booleans**: The three modes are mutually exclusive; using a mode string (validated upfront) is easier to extend and eliminates illegal states.

### 3. GPU index types and defaults

**Decision**: Add to `MilvusIndexTypes`:
- `GPU_CAGRA = "GPU_CAGRA"`, `GPU_IVF_FLAT = "GPU_IVF_FLAT"`, `GPU_IVF_PQ = "GPU_IVF_PQ"`, `GPU_BRUTE_FORCE = "GPU_BRUTE_FORCE"`
- `ALL_GPU_TYPES: ClassVar[list[str]] = [GPU_CAGRA, GPU_IVF_FLAT, GPU_IVF_PQ, GPU_BRUTE_FORCE]`
- Include `ALL_GPU_TYPES` in `ALL_TYPES`.

Add to `INDEX_DEFAULT_PARAMETERS`:
- `GPU_CAGRA`: `{"intermediate_graph_degree": 64, "graph_degree": 32, "build_algo": "IVF_PQ", "cache_dataset_on_device": False}`
- `GPU_IVF_FLAT`: `{"nlist": 1024}`
- `GPU_IVF_PQ`: `{"nlist": 1024, "m": 16, "nbits": 8}`
- `GPU_BRUTE_FORCE`: `{}`

Add to `MilvusMetricTypes`:
- `GPU_VALID_METRICS: ClassVar[list[str]] = [L2, IP]`

### 4. Mode-aware validation sequence in `MilvusIndexManager.__init__`

**Decision**: Run validators in this order: `_validate_vector_mode()` → `_validate_index_type()` → `_validate_metric_type()` → `_validate_gpu_config()` (only when `_is_gpu`).

- `_validate_vector_mode()`: rejects unknown modes with a `DocpipeException(status_code=400)`.
- `_validate_index_type()` (mode-aware):
  - `_is_sparse` → skip (existing behaviour)
  - `_is_gpu` → must be in `ALL_GPU_TYPES`; if not → `DocpipeException(status_code=400)`
  - `_is_binary` → must be in `ALL_BINARY_TYPES` (currently empty, validated as future-safe no-op)
  - else (dense) → existing check against `ALL_DENSE_TYPES` and Lite restriction
- `_validate_metric_type()` (mode-aware):
  - `_is_sparse` → skip (existing behaviour)
  - `_is_gpu` → must be in `GPU_VALID_METRICS` (L2, IP); COSINE → `DocpipeException(status_code=400)`
  - else → existing check against `ALL_TYPES`
- `_validate_gpu_config()`: for `GPU_CAGRA`, if `graph_degree > intermediate_graph_degree` → `DocpipeException(status_code=400)`. Uses merged params (defaults + user overrides) via `_get_index_parameters()`.

### 5. `_resolve_vector_mode()` in `adapter.py`

**Decision**: Add a `@staticmethod _resolve_vector_mode(config: dict) -> str` that implements this resolution order:
1. If `vector_mode` key present → return it directly (MilvusIndexManager validates it).
2. Elif `add_sparse_vector=True` → return `"sparse"`.
3. Else → return `"dense"`.

`MilvusAdapter.__init__` calls this, passes the result to `MilvusIndexManager(vector_mode=...)`, and also derives the `add_sparse_vector` boolean to pass unchanged to `MilvusBatchProcessor`.

**Why keep `add_sparse_vector` on the batch processor**: `MilvusBatchProcessor` is out of scope; it still needs the boolean for its sparse insert path. Computing it from `vector_mode == "sparse"` is a one-liner at the adapter layer.

### 6. `MilvusConfig.index_type` Literal expansion

**Decision**: Expand the `Literal[...]` to include `"GPU_CAGRA"`, `"GPU_IVF_FLAT"`, `"GPU_IVF_PQ"`, `"GPU_BRUTE_FORCE"`. No other config fields change.

### 7. `operator_constants.py` additions

**Decision**: Add under `OperatorConstants.VectorDB`:
- `VECTOR_MODE: Final[str] = "vector_mode"`
- `VECTOR_MODE_DEFAULT: Final[str] = "dense"`

These mirror the existing `ADD_SPARSE_VECTOR` / `ADD_SPARSE_VECTOR_DEFAULT` constants in the same block.

## Risks / Trade-offs

- **Risk**: Callers that instantiate `MilvusIndexManager` directly with `add_sparse_vector` will break.
  - **Mitigation**: The only caller is `MilvusAdapter.__init__`. Update it. No other files pass `add_sparse_vector` to `MilvusIndexManager`.
- **Risk**: Existing tests that pass `add_sparse_vector=True` to `MilvusIndexManager` will fail.
  - **Mitigation**: Update `test_milvus_index_manager.py` to pass `vector_mode="sparse"` instead. This is the only test file that constructs `MilvusIndexManager` directly.

## Migration Plan

No data migration required — schema and wire format are unchanged. All existing flow JSON configurations remain valid: `add_sparse_vector` is still accepted by `MilvusAdapter` and resolved internally. The change is entirely additive from a user perspective.

## Open Questions

None.
