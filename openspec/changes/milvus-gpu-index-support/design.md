# Design

## Context

See `proposal.md`. The Milvus adapter lives in `src/docpipe/core/operators/vectordb/adapters/outbound/milvus/`: `config.py` (`MilvusConfig`), `adapter.py` (`MilvusAdapter`) and `index_manager.py` (`MilvusIndexManager`, `MilvusIndexTypes`, `INDEX_DEFAULT_PARAMETERS`).

Index building happens on the Milvus server, not on the host running the pipeline.

## Goals / Non-Goals

**Goals**
- Allow GPU and quantized index types to be selected in `provider_config`.
- Fail early with a clear `DocpipeException` for invalid GPU configurations.
- Never silently change an explicitly requested index type.

**Non-Goals**
- Probing the pipeline host for a GPU. It says nothing about the Milvus server.
- Query-time search parameters. The VectorDB operator only ingests.
- Changes to `MilvusBatchProcessor`, `VectorDBOperator`, domain models or the OpenSearch adapter.

## Decisions

### 1. Index type resolution order in `MilvusIndexManager.__init__`

1. `resolve_quantized_index_type(base_index_type, quantization)`. `quantization_parameters` are merged into `index_parameters` only if quantization changed the index type (or the type is already a quantized type). Otherwise a warning is logged and both are ignored.
2. `use_gpu`:
   - `True` and not already a GPU type: map through `CPU_TO_GPU_UPGRADE_MAP` (`HNSW` -> `GPU_CAGRA`, `IVF_FLAT` -> `GPU_IVF_FLAT`, `IVF_PQ` and `HNSW_PQ` -> `GPU_IVF_PQ`, `FLAT` -> `GPU_BRUTE_FORCE`). A type without a mapping raises a 400 `DocpipeException`.
   - `False` and a GPU type: map through `GPU_TO_CPU_FALLBACK_MAP`.
3. Milvus Lite rejects GPU index types.
4. Validators: metric type, GPU metric (no `COSINE`), index type, `_validate_gpu_config()`.

Upgrading after quantization means `use_gpu=True` works with `quantization` (for example `HNSW` + `PQ` -> `GPU_IVF_PQ`).

### 2. Parameter hygiene on index type changes

`filter_parameters_for_index_type()` keeps only parameters valid for the target type (its defaults plus `INDEX_EXTRA_PARAMETER_KEYS`, for example `adapt_for_cpu` for `GPU_CAGRA`). It is used by `use_gpu` switches and the CPU fallback, and a warning lists the dropped keys.

### 3. No client-side GPU detection; opt-in server-driven fallback

The adapter does not call `torch`, `pynvml` or `nvidia-smi`. A GPU index type is sent to the server as configured.

`fallback_to_cpu` (default `false`): if `client.create_index` raises and the configured type is a GPU type, the manager switches to the CPU equivalent through `_apply_cpu_fallback()` and retries once. `gpu_fallback_triggered` and `gpu_fallback_reason` record what happened. Other failures are not retried.

### 4. Validation

- `_validate_gpu_metric_type()`: GPU index types reject `COSINE`. It runs on the configured type, independent of hardware.
- `_validate_gpu_config()`: for `GPU_CAGRA`, merged parameters must satisfy `intermediate_graph_degree >= graph_degree`.

### 5. CAGRA default parameter type

`cache_dataset_on_device` defaults to the string `"false"`, matching the Milvus documentation.

## Risks / Trade-offs

- **Server-side failure is the only signal that a GPU index is unsupported.** With `fallback_to_cpu=false`, the user sees the Milvus error. This is intentional.
- **Fallback happens after the collection exists.** `create_collection` creates the collection and then the index, so a retry reuses the collection. If the retry also fails, the collection is left behind; this is the existing behavior for any index failure.
- **Real GPU behavior is not covered by unit tests.** Verification on a GPU host with a `-gpu` Milvus image is a follow-up.

## Migration Plan

None. Schema and wire format are unchanged and all new fields are optional.

## Open Questions

None.
