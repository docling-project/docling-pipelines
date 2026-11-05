# Tasks

## 1. Constants and config

- [x] 1.1 [backend] Add `QUANTIZATION`, `QUANTIZATION_PARAMETERS`, `USE_GPU`, `FALLBACK_TO_CPU` to `OperatorConstants.VectorDB` in `src/docpipe/core/constants/operator_constants.py`.
- [x] 1.2 [backend] Extend `MilvusConfig.index_type` with `HNSW_SQ`, `HNSW_PQ`, `HNSW_PRQ`, `GPU_CAGRA`, `GPU_IVF_FLAT`, `GPU_IVF_PQ`, `GPU_BRUTE_FORCE`, and add `quantization`, `quantization_parameters`, `use_gpu`, `fallback_to_cpu` fields.

## 2. `index_manager.py`

- [x] 2.1 [backend] Add GPU and quantized index types, `ALL_GPU_TYPES`, default parameters, `GPU_TO_CPU_FALLBACK_MAP`, `CPU_TO_GPU_UPGRADE_MAP`.
- [x] 2.2 [backend] Add `resolve_quantized_index_type()` and merge `quantization_parameters` only when quantization applies.
- [x] 2.3 [backend] Apply `use_gpu` after quantization; drop parameters that do not belong to the new index type (`filter_parameters_for_index_type()`).
- [x] 2.4 [backend] Reject GPU index types on Milvus Lite and `COSINE` on GPU indexes.
- [x] 2.5 [backend] Add `_validate_gpu_config()` enforcing `intermediate_graph_degree >= graph_degree` for `GPU_CAGRA`.
- [x] 2.6 [backend] Add opt-in `fallback_to_cpu`: retry `create_index` with the CPU equivalent when the server rejects a GPU index.
- [x] 2.7 [backend] Remove host GPU probing (no `torch`, `pynvml` or `nvidia-smi` usage).

## 3. `adapter.py`

- [x] 3.1 [backend] Read `quantization`, `quantization_parameters`, `use_gpu`, `fallback_to_cpu` from the adapter config and pass them to `MilvusIndexManager`.

## 4. Tests

- [x] 4.1 [backend] Cover GPU selection, `use_gpu` upgrade and downgrade, parameter filtering, COSINE rejection, CAGRA validation, opt-in fallback and quantization in `test_milvus_index_manager.py`.
- [x] 4.2 [backend] Cover adapter wiring in `test_milvus_adapter.py`.
- [x] 4.3 [backend] Remove `scripts/test_gpu_index_manager.py` (covered by pytest tests).

## 5. Documentation and samples

- [x] 5.1 [docs] Update `docs/operators/vectordb/milvus.md` and `docs/reference/OPERATORS.md`.
- [x] 5.2 [docs] Add `sample_flows/vectordb/milvus_gpu_integration.json` and ignore `docker/volumes/`.

## 6. Validation

- [ ] 6.1 [backend] Run `pytest tests/unit/operators/vectordb/ -v`.
- [ ] 6.2 [backend] Run `pre-commit run --from-ref origin/main --to-ref HEAD` after committing.
- [ ] 6.3 [backend] Verify on a Linux host with an NVIDIA GPU and a `-gpu` Milvus image.

## Workflow follow-up

- After the PR is approved, run `openspec archive milvus-gpu-index-support`.
