# Design

## Context

See `proposal.md` for motivation. Current state that constrains the approach:

- **Metadata pipeline.** `VectorDBOperator._get_vectordb_provider_schemas` builds each provider's metadata with `OperatorUtils.model_schema_to_docpipe(schema=<Config>.model_json_schema())`. That translator forwards a fixed set of keys (`enum` becomes `valid_values`, plus `default`, `description`, ranges), so Pydantic cannot carry an `applicability` block. The frontend reads `valid_values` and `default` from `operatorMetadata.vectordb.providers[provider].properties[key]` (see `VectorDB.tsx` for `metric_type`, `space_type`, `engine`).
- **Rules live in one place.** Index, metric, Lite and feature-type rules are enforced only in `MilvusIndexManager` (`_validate_index_type`, `_validate_metric_type`, `_validate_dense_config_for_hybrid`) and, for OpenSearch, in `ENGINE_ALGORITHM_SUPPORT` (`opensearch/index_manager.py`). `MilvusIndexTypes` and `MilvusMetricTypes` already group the types into dense, GPU, sparse and binary lists.
- **Defaults.** `MilvusAdapter` reads `index_type` from `adapter_config` with a default of `HNSW` (`DEFAULT_INDEX_TYPE`), and `MilvusConfig.index_type` also defaults to `HNSW`. `vector_mode` is inferred from `index_type` when unset.
- **Resource metadata.** `MilvusResourceMetadata._stored_metadata` and `OpenSearchResourceMetadata._stored_metadata` return only `vector_similarity` and `dimension_size`. The Milvus schema already carries `index_info.index_type` per field. OpenSearch stores `engine` and `algorithm` in the index `_meta` and the `knn_vector` field's `method.name`. `VectorDBMetadataFetcher._empty_result` is the shared fallback. Weaviate returns the same two keys.
- **Tearsheet.** `effectiveSimilarityOptions` in `VectorDBFeatureMappingTearsheet.tsx` filters metrics from the saved `parsedProviderConfig` via `isMilvusGpuMode`. `VectorDB.tsx` excludes `algorithm` and `index_type` from `tearsheetManagedKeys` on purpose, so they appear in Advanced JSON.
- **In-flight overlap.** `add-weaviate-vectordb-adapter` MODIFIES "Vector store resource metadata and flow enrichment" (backend) and "VectorDB feature mapping and backend configuration" (frontend). This change must not modify either.

## Goals / Non-Goals

**Goals:**
- One source of truth for index applicability in the backend, exposed as additive metadata and consumed by the UI as data.
- No UI-reachable combination fails at index creation.
- Existing flows, `valid_values` and defaults keep working.

**Non-Goals:**
- Changing the validators in `MilvusIndexManager` or OpenSearch beyond message clarity (B5). The metadata describes the rules; it does not replace enforcement.
- A generic applicability engine for all operators. Only the VectorDB providers get the block.
- Weaviate, index parameter editors, per-field index types, GPU capability detection (see proposal Non-goals).

## Decisions

### D1. Applicability is a separate additive `applicability` block, built from the adapter constants

Add the block to the provider metadata after `model_schema_to_docpipe` returns, inside `_get_vectordb_provider_schemas`, using a small static method per adapter config module (for example `MilvusConfig.applicability()` and `OpenSearchConfig.applicability()`) that reads `MilvusIndexTypes`, `MilvusMetricTypes`, `LITE_SUPPORTED_DENSE_TYPES` and `ENGINE_ALGORITHM_SUPPORT`.

Shape (Milvus):

```json
{
  "index_families": [
    {"id": "cpu_dense", "index_types": ["FLAT", "..."], "metric_types": ["L2", "IP", "COSINE"], "feature_types": ["vector"]},
    {"id": "gpu",       "index_types": ["GPU_CAGRA", "..."], "metric_types": ["L2", "IP"], "feature_types": ["vector"]},
    {"id": "binary",    "index_types": ["BIN_FLAT", "BIN_IVF_FLAT"], "metric_types": ["HAMMING", "JACCARD"], "feature_types": ["vector_binary"]}
  ],
  "lite": {"index_types": ["FLAT"], "default": "FLAT"}
}
```

Shape (OpenSearch): `{"engine_algorithms": {"faiss": ["hnsw", "ivf"], "lucene": ["hnsw"], "nmslib": ["hnsw"], "jvector": ["hnsw"]}}`.

Why: the constants the validators already use become the single source, so metadata and enforcement cannot drift. A parity test (D6) pins it.

Alternatives considered:
- *Extend `_to_docpipe` to forward a `json_schema_extra` key.* Generic, but it changes a shared translator used by every operator for one provider's need, and `json_schema_extra` is already used for `sensitive`.
- *Duplicate the rules in the frontend.* Rejected by the issue: it is exactly the drift problem.
- *Replace `valid_values` with a structured list.* Breaking for every consumer.

### D2. Remove sparse types from the `Literal`, keep them in `MilvusIndexTypes`

Delete `SPARSE_INVERTED_INDEX` and `SPARSE_WAND` from `MilvusConfig.index_type`. Keep `MilvusIndexTypes.ALL_SPARSE_TYPES` because the adapter still uses `SPARSE_INVERTED_INDEX` for the sparse field. The parity test asserts `set(get_args(index_type Literal)) == set(ALL_DENSE + ALL_GPU + ALL_BINARY)`.

Why: the sparse field never reads the user-configured value, so exposing it only creates a failure path. An existing flow that set a sparse value already fails today in `_validate_index_type`, so rejection earlier is not a behavior regression.

### D3. Milvus Lite default is resolved in the backend adapter, metadata default stays `HNSW`

In `MilvusAdapter.__init__`, when `auth_type == "lite"` and `index_type` is absent from `adapter_config`, use `FLAT`. The Pydantic default stays `HNSW`, so `valid_values`/`default` are unchanged. This needs care: because `MilvusConfig` is validated with its default, the code must look at the **raw** `adapter_config` and the raw `provider_config` during validation, not the model-filled value, to know whether the user set the key. Validation (`VectorDBOperator.validate` and the early `validate_vector_index_config` path) uses the same rule.

The UI preselects `FLAT` from `applicability.lite.default` and writes it explicitly, so saved flows from the UI are explicit and API/CLI flows still work without the key.

Why backend: fixes API and CLI users, not only the UI, and keeps one rule. Alternative (UI-only) leaves the Lite failure for every non-UI flow.

### D4. Stored index type is a third key in `stored_resource_metadata`

`_stored_metadata` in both providers returns `index_type` alongside the existing two. Milvus reads `index_info.index_type` of the same field it already uses for the metric. OpenSearch reads `_meta.algorithm`, falling back to the first `knn_vector` field's `method.name`. Fallbacks, including `VectorDBMetadataFetcher._empty_result`, return `None`.

Why: the frontend type and enrichment normalization already expect a fixed shape, and existing resources already expose this in the schema. Weaviate keeps returning two keys; the frontend treats a missing `index_type` as `null`, and the backend requirement is scoped to Milvus and OpenSearch.

### D5. Frontend: one data-driven control, filter logic in a pure helper

Add `indexTypeKey` and `indexTypeLabel` to `PROVIDER_CONFIG_MAP` (`index_type` / `algorithm`), plus fallback values. Put the option filtering and metric derivation in a pure, unit-testable helper in `frontend/src/utils/vectordb.ts`:

```text
getIndexTypeOptions({provider, applicability, authType, featureTypes, engine}) -> string[]
getMetricOptions({provider, applicability, indexType, featureTypes, validValues}) -> string[]
```

Option filtering also honors an explicit `provider_config.vector_mode` (the backend rejects an index type outside the configured mode), but never to the point of leaving no option for the mapped features. When the selected index type is not a valid option, the metric options fall back to `isMilvusGpuMode(parsedProviderConfig)` so saved configs keep their current behavior.

The tearsheet holds `indexType` in local state (like `engine` and `similarityMetric`), initialised from `parsedProviderConfig`, and `effectiveSimilarityOptions` is computed from that state instead of `isMilvusGpuMode(parsedProviderConfig)`. `isMilvusGpuMode` stays for the pre-selection case in the MODIFIED requirement.

Component hierarchy (inside the existing tearsheet form):

```text
VectorDBFeatureMappingTearsheet
 +- resource ComboBox (existing)
 +- metric Dropdown / read-only TextInput (existing, options now from form index family)
 +- engine Dropdown / read-only TextInput (existing, OpenSearch)
 +- index type / algorithm Dropdown | read-only TextInput  (NEW)
 +- InlineNotification: invalid saved value, parameters reset, mixed collection (NEW)
```

No provider `if` in components: label, key and fallbacks come from `cfg`; family logic reads `applicability`. There is no Redux or API client change. The existing flow is: tearsheet `onSave` payload gains `indexType`, `handleSaveFeatureMappings` writes `cfg.indexTypeKey` into `provider_config` through `mergeProviderConfig` and `controller.updatePropertyValue`.

SCSS: reuse the existing tearsheet form classes; no new SCSS module is expected. Any added spacing uses Carbon tokens.

### D6. Parity tests tie metadata, enum and validators together

Backend tests: (1) the `Literal` equals dense + GPU + binary; (2) every `(index_type, metric_type)` pair allowed by `applicability` passes `MilvusIndexManager` validation and every pair outside it fails; (3) every OpenSearch `(engine, algorithm)` in the map passes and the complement fails. These cover the acceptance criterion that no selectable combination fails at creation.

### D7. Tearsheet-managed keys and saved values

Remove `algorithm` / `index_type` from the exclusion filter in `VectorDB.tsx` so `tearsheetManagedKeys` equals `resourceSpecificKeys`, and update the stale comments in `VectorDB.tsx` and `constants.ts`. A saved value outside the offered options is kept in state, shown as invalid with `invalid`/`invalidText`, and blocks save until corrected; it is never overwritten silently. For an existing resource the stored value is displayed and the saved config value is left untouched.

### D8. `index_parameters` handling: clear with a notice

On a user-initiated index type change with non-empty `index_parameters`, the save payload removes `index_parameters` and the tearsheet shows an inline notice. Warning-only was rejected: stale `HNSW` parameters sent to `IVF_FLAT` would fail at creation, which breaks the acceptance criterion.

## Risks / Trade-offs

- **Metadata and validator drift** -> single source from constants plus the D6 parity tests.
- **Archive conflict with `add-weaviate-vectordb-adapter`** -> only ADDED requirements with new names, and one MODIFIED requirement the other change does not touch. Rebase implementation on that change before editing `VectorDB.tsx` and the tearsheet. Re-run `openspec validate --strict` after it archives.
- **Raw-vs-defaulted config for the Lite default (D3)** -> the "set vs unset" check is unit-tested at the adapter entry point, including an explicit `HNSW` on Lite (still rejected) and an unset key on Lite (resolves to `FLAT`). If a caller ever passes the model-dumped config (with the `HNSW` default filled in), Lite would still fail; the test covers the real `provider_config` path used by the operator.
- **Existing flows with a sparse `index_type`** -> they already fail at runtime; they now fail at validation with the accepted values listed. Noted in the changelog entry by maintainers, not by this change.
- **`BM25` in the metric list** -> the backend accepts `BM25` only when no dense feature is indexed with the configured metric (`_validate_dense_field_config` runs only when a `vector` feature exists). So `BM25` is dropped when a dense feature is mapped, and kept for binary-only collections with sparse on, which an existing test already pins. With no vector feature known, the list is unchanged.
- **Existing binary collection with a dense saved index** -> mixed-collection fallbacks stay backend behavior; the UI only shows the note.
- **GPU types offered without capability detection** -> accepted, matching the existing spec (the adapter never probes local hardware); the Lite filter is the only deployment-based filter.

## Migration Plan

No data migration. Additive metadata and an extra `stored_resource_metadata` key. Rollout order: backend first (metadata, enum, stored index type, Lite default), then frontend. The frontend falls back to static values when `applicability` is absent, so a new frontend against an old backend still works. Rollback is a revert of either side.
