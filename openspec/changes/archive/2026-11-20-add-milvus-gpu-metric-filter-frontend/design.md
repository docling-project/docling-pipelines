# Design

## Context

`VectorDBFeatureMappingTearsheet` already derives `effectiveSimilarityOptions` with a `useMemo`: binary-only features give `HAMMING`/`JACCARD`, dense-only features give `L2`/`IP`/`COSINE`, and `BM25` is added when sparse is enabled. An effect resets the metric when it falls outside the options (create-new only). `parsedProviderConfig`, which holds `vector_mode` and `index_type`, is already a prop. See proposal.md for motivation.

The backend (`MilvusIndexManager`) accepts only `L2` and `IP` in GPU mode and infers GPU mode from `GPU_*` index types when `vector_mode` is unset.

## Goals / Non-Goals

**Goals:**
- Reuse the existing filtering memo; add one GPU rule.
- Mirror the backend GPU-mode inference so UI and validation agree.

**Non-Goals:**
- New `vector_mode` / `index_type` controls.
- Re-running enrichment when the Advanced JSON changes while the tearsheet is open.

## Decisions

- **Constants**: `MILVUS_GPU_METRIC_VALUES` sits beside the existing `MILVUS_DENSE_METRIC_VALUES` / `MILVUS_BINARY_METRIC_VALUES`, keeping provider rules as data. An explicit `vector_mode` wins; only an unset mode falls back to the `GPU_` prefix, matching `_resolve_vector_mode`.
- **GPU filter helper lives in `frontend/src/utils/vectordb.ts`**: `isMilvusGpuMode()` is a function, so it goes in utils rather than `constants.ts` (constants hold data only).
- **GPU filter applies unless features are binary-only**: binary-only keeps `HAMMING`/`JACCARD` (the backend rejects GPU with only binary features, so the user sees the backend message rather than an empty dropdown). Mixed and unknown feature sets are filtered to `L2`/`IP`, because the metric configures the dense field.
- **`BM25` dropped in GPU mode**: the backend rejects `add_sparse_vector` with an explicit non-sparse mode, and the dense field in a GPU-index hybrid collection needs `L2`/`IP`.
- **Alternative rejected**: reading `valid_values` from operator metadata. The backend `Literal` lists all metrics regardless of mode, so metadata cannot express the mode-dependent subset.

## Risks / Trade-offs

- [Edits to the Advanced JSON are only seen when the tearsheet reopens] -> `parsedProviderConfig` is re-read on each open; acceptable.
- [Saved metric `COSINE` on an existing GPU flow] -> reset to the first valid option for create-new; existing collections remain read-only as today.
