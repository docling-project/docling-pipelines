# Proposal

## Why

The Milvus adapter now supports `vector_mode: "gpu"` and `GPU_*` index types (PR #507, issue #558). GPU indexes accept only the `L2` and `IP` metrics, but the VectorDB feature mapping tearsheet still offers `COSINE` and `BM25` for dense vectors. A user can pick an unsupported metric and only learns about it when flow validation fails.

## What Changes

- Filter the Milvus similarity metric dropdown in the VectorDB feature mapping tearsheet to `L2` and `IP` when `provider_config` selects GPU: `vector_mode` is `"gpu"`, or `index_type` starts with `GPU_`.
- Do not offer `BM25` in GPU mode, because the backend rejects `add_sparse_vector` together with a GPU vector mode.
- When the current metric is no longer offered, reset it to the first valid option (existing behavior for create-new resources).
- Binary-only features keep their `HAMMING` / `JACCARD` options unchanged.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `frontend/properties-panel`: the VectorDB feature mapping requirement gains contextual metric filtering for Milvus GPU mode.

## Impact

- **Frontend only**: `VectorDB/constants.ts`, `frontend/src/utils/vectordb.ts` and `VectorDBFeatureMappingTearsheet.tsx`, plus unit tests under `frontend/tests/unit/`.
- No backend, API, dependency, or i18n message changes (`L2` and `IP` labels already exist).

## Non-goals

- Dedicated UI controls for `vector_mode`, `index_type` or `index_parameters`; these stay in the Advanced JSON textarea.
- Disabling Milvus Lite or showing a GPU-build hint.
