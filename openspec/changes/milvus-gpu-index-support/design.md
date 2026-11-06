# Design

## Context

See `proposal.md`. The Milvus adapter lives in `src/docpipe/core/operators/vectordb/adapters/outbound/milvus/`: `config.py` (`MilvusConfig`), `adapter.py` (`MilvusAdapter`) and `index_manager.py` (`MilvusIndexManager`, `MilvusVectorModes`, `MilvusIndexTypes`, `INDEX_DEFAULT_PARAMETERS`).

Index building happens on the Milvus server, not on the host running the pipeline.

## Goals / Non-Goals

**Goals**
- Allow GPU index types to be selected through an explicit `vector_mode`.
- Fail early, including during flow validation without a Milvus connection, with a clear `DocpipeException` for invalid configurations.
- Never silently change an explicitly requested index type.

**Non-Goals**
- Probing the pipeline host for a GPU. It says nothing about the Milvus server.
- Automatic CPU fallback, `use_gpu` switching and HNSW quantization. These were removed to keep the change focused on GPU index support.
- Query-time search parameters. The VectorDB operator only ingests.
- Changes to `MilvusBatchProcessor`, `VectorDBOperator`, domain models or the OpenSearch adapter.

## Decisions

### 1. `vector_mode` resolution

`MilvusAdapter._resolve_vector_mode`: explicit `vector_mode`, else `add_sparse_vector=true` -> `sparse`, else inferred from `index_type` (`MilvusVectorModes.infer_from_index_type`), else `dense`. The batch processor keeps receiving the derived `add_sparse_vector` boolean.

### 2. Connection-free validation

`MilvusIndexManager.validate_index_config` is a static method running `_validate_vector_mode`, `_validate_index_type`, `_validate_metric_type` and `_validate_gpu_config`. `MilvusIndexManager.__init__` calls it, and `MilvusAdapter.__init__` calls it before `MilvusClient` connects. Flow validation instantiates the operator (and so the adapter), therefore these errors surface in `/validate_flow` even when Milvus is not reachable.

### 3. Mode-aware validation

| Mode | Index types | Metrics |
|---|---|---|
| `dense` | `ALL_DENSE_TYPES` (Lite: `FLAT`) | `L2`, `IP`, `COSINE` |
| `gpu` | `ALL_GPU_TYPES` (not on Lite) | `L2`, `IP` |
| `binary` | `ALL_BINARY_TYPES` (not on Lite) | `HAMMING`, `JACCARD` |
| `sparse` | `SPARSE_INVERTED_INDEX` is used for the sparse field; checks skipped | not applicable |

`GPU_CAGRA` additionally requires `graph_degree <= intermediate_graph_degree` after merging defaults with `index_parameters`.

### 4. Behavior per collection kind

GPU indexes apply only to dense `FLOAT_VECTOR` fields. Fields are indexed by their own data type:

- **Dense only**: every vector field uses the configured GPU (or CPU) index.
- **Binary only**: binary fields use `BIN_*`. `vector_mode=gpu` with only binary features is rejected by `validate_vector_feature_types`, because a GPU index would never be used.
- **Mixed dense + binary**: dense fields use the configured index, binary fields use `BIN_FLAT`/`HAMMING` (a warning is logged when the configured dense settings are overridden for a binary field).
- **Sparse only**: `vector_mode=sparse` skips the GPU and binary feature checks. The sparse field uses `SPARSE_INVERTED_INDEX`/`BM25`.
- **Hybrid (dense + sparse)**: the sparse field keeps `SPARSE_INVERTED_INDEX`/`BM25`; the dense field uses the configured dense index.

### 5. Cleanup after index failure

`create_collection` records whether `client.create_collection` succeeded. If a later step (sparse or dense `create_index`) fails, the collection is dropped best-effort (`_drop_partial_collection`). A failed drop is logged and never masks the original error.

### 6. CAGRA default parameter type

`cache_dataset_on_device` defaults to the string `"false"`, matching the Milvus documentation.

## Risks / Trade-offs

- **Server-side failure is the only signal that a server lacks GPU support.** The user sees the Milvus error and the partially created collection is dropped.
- **Real GPU behavior is not covered by unit tests.** Verification on a GPU host with a `-gpu` Milvus image is a follow-up.
- **`vector_mode` inference.** Flows that only set `index_type: GPU_*` or `BIN_*` keep working because the mode is inferred; an explicit conflicting `vector_mode` is rejected.

## Migration Plan

None. Schema and wire format are unchanged and `vector_mode` is optional.

## Open Questions

None.
