# Proposal

## Why

The VectorDB backend lets users choose the vector index algorithm (Milvus `index_type`, OpenSearch `algorithm`), but the VectorDB feature-mapping tearsheet has no control for it. Users must hand-write the key in the **Advanced JSON** textarea, and several invalid combinations are only rejected at runtime, at index creation. The operator metadata is a flat `valid_values` list that does not say which values apply under Milvus Lite, GPU, binary, sparse, or a given OpenSearch engine, so a UI built on it today would have to duplicate backend rules. The tearsheet also derives its metric options from the **saved** `index_type` rather than the selection in the form, and offers `BM25` for the dense field, which the backend rejects.

Tracked in [issue #693](https://github.com/docling-project/docling-pipelines/issues/693).

**Layer:** full-stack. The backend gets additive operator metadata, a stricter `index_type` enum, stored index type in resource metadata, and a valid Milvus Lite default. The frontend gets a metadata-driven index-type / algorithm control in the tearsheet. There are no routing, BFF proxy, or Redux slice changes.

## What Changes

### Backend

- **Remove unusable sparse values.** `SPARSE_INVERTED_INDEX` and `SPARSE_WAND` are removed from the user-selectable `MilvusConfig.index_type` values. A parity test keeps the `Literal` in sync with `MilvusIndexTypes`.
- **Applicability metadata (additive).** The `providers.milvus` and `providers.opensearch` metadata gain an `applicability` block describing: Milvus index families and the metric types each allows, the Milvus Lite subset and default, which families need a binary feature, and the OpenSearch `engine` to allowed `algorithm` map. Existing `valid_values` lists are not changed.
- **Stored index type.** `stored_resource_metadata` gains `index_type` (Milvus `index_type`, OpenSearch `algorithm`), or `null` when unknown.
- **Milvus Lite default.** When `auth_type="lite"` and `index_type` is not set by the user, the backend resolves it to `FLAT`, so Lite works without an explicit key. An explicit invalid value is still rejected.
- **Validation messages.** Flow validation of OpenSearch `engine`/`algorithm` mismatches and Milvus index/metric/feature-type mismatches is confirmed to name the offending values, with tests where messages are missing or unclear.
- **Docs and tests.** Update `tests/unit/operators/vectordb/`, `docs/reference/OPERATORS.md`, `docs/operators/vectordb/vectordb_readme.md` and `docs/operators/vectordb/milvus.md`.

### Frontend

- **Data-driven control.** Add the config key, label and fallback values to `PROVIDER_CONFIG_MAP` as data, with no provider branching in components. Read `valid_values`, `default` and `applicability` from operator metadata.
- **Tearsheet dropdown.** A Carbon `Dropdown` for index type / algorithm. Editable for a new resource; a read-only `TextInput` showing the stored value for an existing resource. The value flows through the `onSave` payload and `handleSaveFeatureMappings`.
- **Context filtering.** Options follow the context: Lite offers `FLAT` only; binary-only features offer `BIN_*`; dense features offer CPU dense and GPU; OpenSearch `algorithm` follows the selected `engine` and resets when the engine changes.
- **Metric options from the form.** Metric options derive from the **selected index family in the form**, not saved config, reset to the first valid option when invalidated, and never include `BM25` for the dense field.
- **Tearsheet-managed key.** `index_type` / `algorithm` become tearsheet-managed. Flows that already hold the key in Advanced JSON pre-populate the dropdown with no data loss. A saved value not in the options shows as invalid and is not silently dropped.
- **Index parameters.** `index_parameters` is cleared (or a warning shown) when the index type changes. Editing parameters stays in Advanced JSON.
- **Mixed collections note** for dense + binary collections.
- **Strings and accessibility.** All new strings are in `*.messages.ts`; controls are keyboard operable with accessible labels.

### Carbon components

`Dropdown` (editable case), `TextInput` (read-only stored value), `InlineNotification` (invalid saved value and mixed-collection note), inside the existing `Tearsheet` form layout. No new layout pattern.

No **BREAKING** changes. Existing flows load, save and run unchanged.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `backend/vectordb-operator`: adds requirements for the index selection applicability metadata, the stored index type in resource metadata, the sparse index types being non-selectable, and the Milvus Lite default index type. These are new requirements with new names. The existing requirement "Vector store resource metadata and flow enrichment" is **not** modified here, because the in-flight change `add-weaviate-vectordb-adapter` already modifies it and a second modification would conflict at archive time.
- `frontend/properties-panel`: adds a requirement for index type / algorithm selection in the tearsheet, and modifies the existing "Milvus GPU mode similarity metric filtering" requirement so metric options follow the index family selected in the form, not saved config. The requirement "VectorDB feature mapping and backend configuration" is **not** modified here, for the same archive-conflict reason (the Weaviate change modifies it).

## Non-goals

- Weaviate UI. The panel does not support it yet, and its change deliberately keeps `index_type` / `index_parameters` in Advanced JSON.
- Editors for index parameters (`M`, `efConstruction`, `nlist`, and so on).
- Per-field index types and GPU capability detection.
- Changing the existing `valid_values` lists or the `metric_type` / `space_type` enums.
- Routing under `/ui`, BFF proxy routes, and Redux slices (none are touched).

## Impact

- **Backend:** `src/docpipe/core/operators/vectordb/adapters/outbound/milvus/{config.py,index_manager.py,resource_metadata.py,adapter.py}`, `.../opensearch/{config.py,resource_metadata.py}`, `src/docpipe/core/operators/vectordb/vectordb_operator.py` (provider schema assembly), `tests/unit/operators/vectordb/`, and the three docs files above. REST route `GET /api/v1/operators/metadata` returns the additive `applicability` block; the flow enrichment endpoint returns the extended `stored_resource_metadata`.
- **Frontend:** `frontend/src/components/PropertiesPanel/CustomPanels/VectorDB/{constants.ts,VectorDB.tsx,VectorDBFeatureMappingTearsheet.tsx,vectordb-enrichment.ts,*.messages.ts}`, `frontend/src/types/operator.ts`, `frontend/src/utils/vectordb.ts`, and the matching unit tests.
- **Dependencies:** none.
- **Coordination:** `add-weaviate-vectordb-adapter` edits the same VectorDB panel and `vectordb-operator` spec. Implementation must rebase on it; spec deltas are written to avoid archive conflicts.
