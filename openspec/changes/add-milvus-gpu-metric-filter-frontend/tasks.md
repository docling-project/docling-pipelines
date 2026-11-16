# Tasks

## 1. GPU metric filtering

- [x] 1.1 Add `MILVUS_GPU_METRIC_VALUES` and `isMilvusGpuMode()` to `VectorDB/constants.ts`; verify with unit tests for `vector_mode: "gpu"`, `index_type: "GPU_CAGRA"` with no mode, explicit non-GPU mode overriding a `GPU_` index, and empty config
- [x] 1.2 Apply the GPU filter in `effectiveSimilarityOptions` in `VectorDBFeatureMappingTearsheet.tsx` (skip for binary-only features); verify tearsheet tests: GPU mode shows only `L2`/`IP`, `COSINE`/`BM25` absent, non-GPU config unchanged, binary-only still shows `HAMMING`/`JACCARD`
- [x] 1.3 Verify the metric resets to the first option when GPU mode is active and the saved metric is `COSINE`

## 2. Validation

- [x] 2.1 Run the VectorDB frontend unit tests, lint and typecheck from `frontend/` and verify they pass
- [x] 2.2 Run `openspec validate add-milvus-gpu-metric-filter-frontend --strict` and verify it passes

## Workflow follow-up

- Archive the change after review with `openspec archive add-milvus-gpu-metric-filter-frontend`.
