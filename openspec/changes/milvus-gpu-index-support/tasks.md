# Tasks

## 1. Constants — `operator_constants.py`

- [ ] 1.1 [backend] Add `VECTOR_MODE: Final[str] = "vector_mode"` and `VECTOR_MODE_DEFAULT: Final[str] = "dense"` constants to `OperatorConstants.VectorDB` in `src/docpipe/core/constants/operator_constants.py`, immediately below the existing `ADD_SPARSE_VECTOR` / `ADD_SPARSE_VECTOR_DEFAULT` pair. Verify: `grep -n "VECTOR_MODE" src/docpipe/core/constants/operator_constants.py` shows both new constants.

## 2. `index_manager.py` — types, defaults, and `MilvusIndexManager`

- [ ] 2.1 [backend] Add `MilvusVectorModes` class to `index_manager.py` with `DENSE = "dense"`, `SPARSE = "sparse"`, `BINARY = "binary"`, `GPU = "gpu"`, and `ALL_MODES: ClassVar[list[str]]`. Verify: the class appears above `MilvusMetricTypes`.

- [ ] 2.2 [backend] Add GPU index type constants to `MilvusIndexTypes`: `GPU_CAGRA`, `GPU_IVF_FLAT`, `GPU_IVF_PQ`, `GPU_BRUTE_FORCE`; add `ALL_GPU_TYPES: ClassVar[list[str]]`; extend `ALL_TYPES` to include `ALL_GPU_TYPES`. Verify: `len(MilvusIndexTypes.ALL_TYPES) == 13`.

- [ ] 2.3 [backend] Add `GPU_VALID_METRICS: ClassVar[list[str]] = [L2, IP]` to `MilvusMetricTypes`. No new metric type values — this is a validation subset constant only. Verify: attribute exists and equals `["L2", "IP"]`.

- [ ] 2.4 [backend] Add default parameters for the four GPU index types to `INDEX_DEFAULT_PARAMETERS`: `GPU_CAGRA: {"intermediate_graph_degree": 64, "graph_degree": 32, "build_algo": "IVF_PQ", "cache_dataset_on_device": False}`, `GPU_IVF_FLAT: {"nlist": 1024}`, `GPU_IVF_PQ: {"nlist": 1024, "m": 16, "nbits": 8}`, `GPU_BRUTE_FORCE: {}`. Verify: all four keys exist in the dict.

- [ ] 2.5 [backend] Replace `add_sparse_vector: bool = False` parameter with `vector_mode: str = MilvusVectorModes.DENSE` in `MilvusIndexManager.__init__`. Derive `self._is_sparse`, `self._is_gpu`, `self._is_binary` from it. Replace all `self.add_sparse_vector` references in the class body with `self._is_sparse`. Verify: no remaining reference to `self.add_sparse_vector` exists in `index_manager.py`.

- [ ] 2.6 [backend] Add `_validate_vector_mode()` to `MilvusIndexManager`: raises `DocpipeException(status_code=400, error_code=ErrorCode.OPERATOR_CONFIGURATION_INVALID)` when `vector_mode` is not in `MilvusVectorModes.ALL_MODES`. Call it first in `__init__` before the existing validators. Verify: passing `vector_mode="bad"` raises `DocpipeException`.

- [ ] 2.7 [backend] Make `_validate_index_type()` mode-aware: skip when `_is_sparse` (preserve existing behaviour); check against `ALL_GPU_TYPES` when `_is_gpu` (raise `DocpipeException` on mismatch); fall through to existing `ALL_DENSE_TYPES` / Lite restriction for dense mode. Verify: `vector_mode="gpu"` + `index_type="HNSW"` raises `DocpipeException`.

- [ ] 2.8 [backend] Make `_validate_metric_type()` mode-aware: skip when `_is_sparse` (preserve existing behaviour); check against `GPU_VALID_METRICS` (L2, IP) when `_is_gpu` (raise `DocpipeException` on COSINE or BM25); preserve existing check for dense/binary. Verify: `vector_mode="gpu"` + `metric_type="COSINE"` raises `DocpipeException`.

- [ ] 2.9 [backend] Add `_validate_gpu_config()` to `MilvusIndexManager`: called at end of `__init__` only when `_is_gpu`; for `GPU_CAGRA`, reads merged params via `_get_index_parameters()` and raises `DocpipeException(status_code=400)` when `graph_degree > intermediate_graph_degree`. Verify: `GPU_CAGRA` with `{"graph_degree": 64, "intermediate_graph_degree": 32}` raises; with `{"graph_degree": 32, "intermediate_graph_degree": 64}` does not.

## 3. `config.py` — Literal expansion

- [ ] 3.1 [backend] Expand `MilvusConfig.index_type` `Literal[...]` to include `"GPU_CAGRA"`, `"GPU_IVF_FLAT"`, `"GPU_IVF_PQ"`, `"GPU_BRUTE_FORCE"`. Verify: `MilvusConfig(collection_name="x", index_type="GPU_CAGRA")` parses without error; `MilvusConfig(collection_name="x", index_type="GPU_FAKE")` raises `ValidationError`.

## 4. `adapter.py` — `_resolve_vector_mode` and wiring

- [ ] 4.1 [backend] Add `@staticmethod _resolve_vector_mode(config: dict) -> str` to `MilvusAdapter` implementing the resolution order: `vector_mode` key present → return it; `add_sparse_vector=True` → return `"sparse"`; else → return `"dense"`. Verify: unit test covers all three branches.

- [ ] 4.2 [backend] In `MilvusAdapter.__init__`, call `_resolve_vector_mode(adapter_config)` and store the result; pass it as `vector_mode=` to `MilvusIndexManager`. Compute `add_sparse_vector = (resolved_mode == "sparse")` and pass it to `MilvusBatchProcessor` unchanged. Update the initialization log line to include the resolved mode. Verify: sparse mode flows that previously passed `add_sparse_vector=True` still construct without error.

## 5. Tests — `test_milvus_index_manager.py`

- [ ] 5.1 [backend] Replace all `add_sparse_vector=True` keyword arguments passed to `MilvusIndexManager(...)` in existing tests with `vector_mode="sparse"`. Verify: `pytest tests/unit/operators/vectordb/test_milvus_index_manager.py -v` passes with no changes to test assertions.

- [ ] 5.2 [backend] Update `TestIndexTypes.test_all_index_types_defined` to assert the four GPU constants exist and `len(MilvusIndexTypes.ALL_TYPES) == 13`. Update `TestMetricTypes.test_all_metric_types_defined` to assert `GPU_VALID_METRICS` exists with length 2 and `ALL_TYPES` still has length 4. Update `TestIndexTypes.test_default_parameters_for_all_types` to cover all 13 types. Verify: updated assertions pass.

- [ ] 5.3 [backend] Add `TestGPUMode` test class to `test_milvus_index_manager.py` with the following tests:
  - `test_gpu_mode_initialization` — `vector_mode="gpu"` + `index_type="GPU_CAGRA"` + `metric_type="L2"` constructs without error.
  - `test_gpu_mode_rejects_cpu_index_type` — `vector_mode="gpu"` + `index_type="HNSW"` raises `DocpipeException`.
  - `test_gpu_mode_rejects_cosine_metric` — `vector_mode="gpu"` + `metric_type="COSINE"` raises `DocpipeException`.
  - `test_gpu_cagra_graph_degree_constraint_violated` — `GPU_CAGRA` with `graph_degree > intermediate_graph_degree` raises `DocpipeException`.
  - `test_gpu_cagra_valid_custom_parameters` — `GPU_CAGRA` with `graph_degree <= intermediate_graph_degree` constructs without error.
  - `test_gpu_default_parameters_all_types` — all four GPU index types have entries in `INDEX_DEFAULT_PARAMETERS`.
  - `test_unknown_vector_mode_rejected` — `vector_mode="bad_mode"` raises `DocpipeException`.
  Verify: `pytest tests/unit/operators/vectordb/test_milvus_index_manager.py -v` shows all new tests passing.

## 6. Documentation

- [ ] 6.1 [docs] Update `docs/reference/OPERATORS.md`: add `vector_mode` to the VectorDB Milvus parameters table (type: string, default: `dense`, values: `dense | sparse | binary | gpu`); list the four GPU index types under supported `index_type` values; add a note that GPU mode restricts `metric_type` to `L2` or `IP`; add a backward-compatibility note explaining `add_sparse_vector=True` maps to `vector_mode="sparse"`. Verify: the updated section renders correctly in Markdown.

## 7. Validation

- [ ] 7.1 [backend] Run `pytest tests/unit/operators/vectordb/ -v` and confirm all tests pass with no new failures.

- [ ] 7.2 [backend] Run `pre-commit run --files src/docpipe/core/operators/vectordb/adapters/outbound/milvus/index_manager.py src/docpipe/core/operators/vectordb/adapters/outbound/milvus/adapter.py src/docpipe/core/operators/vectordb/adapters/outbound/milvus/config.py src/docpipe/core/constants/operator_constants.py tests/unit/operators/vectordb/test_milvus_index_manager.py docs/reference/OPERATORS.md` and confirm ruff, detect-secrets, and all other hooks pass.

## Workflow follow-up

- After all tasks pass and PR is approved, run `openspec archive milvus-gpu-index-support` to merge the spec delta into `openspec/specs/backend/vectordb-operator/`.
