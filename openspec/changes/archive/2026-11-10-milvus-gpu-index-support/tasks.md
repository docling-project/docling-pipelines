# Tasks

## 1. Constants and config

- [x] 1.1 [backend] Add `VECTOR_MODE` and `VECTOR_MODE_DEFAULT` to `OperatorConstants.VectorDB` in `src/docpipe/core/constants/operator_constants.py`; keep `ADD_SPARSE_VECTOR`.
- [x] 1.2 [backend] Extend `MilvusConfig` with `vector_mode` and the GPU `index_type` values.

## 2. `index_manager.py`

- [x] 2.1 [backend] Add `MilvusVectorModes`, GPU index types, `ALL_GPU_TYPES`, `GPU_VALID_METRICS` and GPU default parameters.
- [x] 2.2 [backend] Replace `add_sparse_vector` with `vector_mode` and derive `_is_sparse`, `_is_gpu`, `_is_binary`.
- [x] 2.3 [backend] Add static, connection-free `validate_index_config` with mode-aware `_validate_vector_mode`, `_validate_index_type`, `_validate_metric_type` and `_validate_gpu_config`.
- [x] 2.4 [backend] Reject GPU index types on Milvus Lite and `COSINE` on GPU indexes.
- [x] 2.5 [backend] Reject `vector_mode=gpu` when the only vector features are binary (`validate_vector_feature_types`).
- [x] 2.6 [backend] Drop the collection when index creation (sparse or dense) fails after the collection was created.
- [x] 2.7 [backend] Validate the dense field's index type, metric and `GPU_CAGRA` parameters in hybrid (sparse + dense) collections; coerce numeric-string `GPU_CAGRA` degrees.

## 3. `adapter.py`

- [x] 3.1 [backend] Add `_resolve_vector_mode` (rejects `add_sparse_vector=true` with a non-sparse `vector_mode`), pass `vector_mode` to `MilvusIndexManager`, and call `validate_index_config` before connecting.

## 4. Tests

- [x] 4.1 [backend] Cover GPU mode, mode-aware validation, CAGRA validation, per-collection-kind index resolution and drop-on-failure in `test_milvus_index_manager.py`.
- [x] 4.2 [backend] Cover adapter wiring in `test_milvus_adapter.py`.
- [x] 4.3 [backend] Cover `/validate_flow` GPU checks without a Milvus connection in `tests/unit/core/orchestrator/test_milvus_gpu_flow_validation.py`.

## 5. Documentation and samples

- [x] 5.1 [docs] Update `docs/operators/vectordb/milvus.md` and `docs/reference/OPERATORS.md`.
- [x] 5.2 [docs] Add `sample_flows/vectordb/milvus_gpu_integration.json`.

## 6. Validation

- [x] 6.1 [backend] Run `pytest tests/unit/operators/vectordb/ tests/unit/core/orchestrator/ -v`.
- [x] 6.2 [backend] Run `pre-commit run --from-ref origin/main --to-ref HEAD` after committing.

## Follow-up

- Not part of this change: verify on a Linux host with an NVIDIA GPU and a `-gpu` Milvus image. Tracked in Open Questions in `design.md` and in the Acceptance Criteria of issue #558.
