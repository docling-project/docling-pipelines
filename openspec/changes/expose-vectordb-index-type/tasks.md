# Tasks

Layer tags: [backend], [frontend], [both]. Rebase on `add-weaviate-vectordb-adapter` before starting group 4 (it edits the same panel files).

## 1. Backend enum, metadata and parity [backend]

- [x] 1.1 Remove `SPARSE_INVERTED_INDEX` and `SPARSE_WAND` from `MilvusConfig.index_type` in `milvus/config.py` and update its description. Verify with a test that sparse values fail `MilvusConfig.model_validate` and that the Milvus `index_type` `valid_values` equal the 13 dense, GPU and binary types
- [x] 1.2 Add a parity test asserting the `index_type` `Literal` equals `MilvusIndexTypes.ALL_DENSE_TYPES + ALL_GPU_TYPES + ALL_BINARY_TYPES`. Verify it fails when a type is added to one side only
- [x] 1.3 Add `applicability()` static methods to the Milvus and OpenSearch config modules, built from `MilvusIndexTypes`, `MilvusMetricTypes`, `LITE_SUPPORTED_DENSE_TYPES` and `ENGINE_ALGORITHM_SUPPORT`. Verify with unit tests on the exact family, metric, Lite and engine-map contents
- [x] 1.4 Attach the block under `providers.milvus` / `providers.opensearch` in `VectorDBOperator._get_vectordb_provider_schemas`. Verify `get_metadata()` includes it and that every other attribute's `valid_values` and `default` match a snapshot taken before the change, except the Milvus `index_type` values
- [x] 1.5 Add combination parity tests: every `(index_type, metric_type)` pair allowed by `applicability` passes `MilvusIndexManager` validation and every pair outside it fails; every OpenSearch `(engine, algorithm)` in the map passes `_validate_engine_algorithm` and the complement fails. Verify `pytest tests/unit/operators/vectordb -k "applicability or parity"` passes

## 2. Backend Milvus Lite default and validation messages [backend]

- [x] 2.1 In `MilvusAdapter.__init__`, resolve an unset `index_type` to `FLAT` when `auth_type == "lite"`. Verify tests: Lite with no key builds and validates, Lite with explicit `HNSW` still fails naming `FLAT`, non-Lite with no key still uses `HNSW`
- [x] 2.2 Review the OpenSearch engine/algorithm and Milvus index/metric/feature-type error messages (B5). Where a message omits the offending values or the accepted alternatives, add them. Verify with tests that assert each message names the values and the alternatives for the four mismatch scenarios in the spec
- [x] 2.3 Verify flow validation end to end for the spec scenarios in "Index configuration mismatches are reported by flow validation" through `VectorDBOperator.validate`, with Milvus mocked unreachable. Verify no client is created

## 3. Backend stored index type [backend]

- [x] 3.1 Add `index_type` to `MilvusResourceMetadata._stored_metadata` (from the dense field's `index_info.index_type`) and to `OpenSearchResourceMetadata._stored_metadata` (`_meta.algorithm`, then `method.name` fallback). Verify with unit tests for existing resource, missing index info, and missing mapping
- [x] 3.2 Add `index_type: None` to the empty and fallback `stored_resource_metadata` shapes in `metadata_fetcher.py` and both providers' initial values. Verify the unreachable-store test returns the three keys
- [x] 3.3 Confirm the enrichment API DTO passes the extra key through unchanged and Weaviate output is untouched. Verify with an API-level test or schema inspection of the enrichment response
- [x] 3.4 Update `docs/reference/OPERATORS.md`, `docs/operators/vectordb/vectordb_readme.md` and `docs/operators/vectordb/milvus.md` for the new enum, the `applicability` metadata, the stored `index_type` and the Lite default. Verify links resolve and no section is added that the operator-readme rules forbid

## 4. Frontend data layer [frontend]

- [x] 4.1 Extend `stored_resource_metadata` with `index_type: string | null` in `frontend/src/types/operator.ts` and default it to `null` in `vectordb-enrichment.ts` when absent. Verify with `vectordb-enrichment.test.ts` cases for present, absent and `null`
- [x] 4.2 Add `indexTypeKey`, `indexTypeLabel` and fallback values for both providers to `PROVIDER_CONFIG_MAP` in `constants.ts`, and update the stale comments there. Verify `getProviderConfig` tests and that no component branches on provider name for the new control
- [x] 4.3 Add pure helpers `getIndexTypeOptions` and `getMetricOptions` to `frontend/src/utils/vectordb.ts`, driven by `applicability` with static fallbacks. Verify `vectordb.test.ts` covers Lite, binary-only, dense with and without sparse, GPU, explicit `vector_mode`, binary-only with sparse keeping `BM25`, OpenSearch per engine, and missing metadata
- [x] 4.4 Read `applicability` and index `valid_values` from operator metadata in `VectorDB.tsx` and pass them to the tearsheet as props. Verify `VectorDB.test.tsx` for metadata present and metadata absent

## 5. Frontend tearsheet control [frontend]

- [x] 5.1 Add the index type / algorithm `Dropdown` (new resource) and read-only `TextInput` (existing resource with stored value) to `VectorDBFeatureMappingTearsheet.tsx`, with local state initialised from the saved config. Verify tearsheet tests for both modes and for an existing resource with `null` stored value
- [x] 5.2 Derive `effectiveSimilarityOptions` from the form's selected index family and remove `BM25` from the dense options. Reset the metric to the first valid option when the family changes. Verify tests for CPU, GPU, binary, change-before-save, and sparse on
- [x] 5.3 Filter OpenSearch algorithm options by the selected engine and reset the algorithm on engine change. Verify tests for each engine and the reset
- [x] 5.4 Show an invalid state with inline text for a saved value not in the options, block save until fixed, and never drop the value silently. Verify tests for pre-populate, invalid saved value and unchanged save
- [x] 5.5 Clear `index_parameters` and show a notice on index type change; show the mixed dense and binary note. Verify tests for parameters present, absent, mixed and single-kind features
- [x] 5.6 Pass `indexType` through the `onSave` payload and `handleSaveFeatureMappings`, make `index_type` / `algorithm` tearsheet-managed in `VectorDB.tsx` (including the comments), and keep other `provider_config` keys. Verify `VectorDB.test.tsx` that the key is absent from Advanced JSON, present in the saved config, and that unrelated keys survive
- [x] 5.7 Add all strings to `VectorDBFeatureMappingTearsheet.messages.ts` and run `npm run extract:messages`. Verify the catalogue diff contains only the new messages and a keyboard-only test (focus, open, select) and label/`invalidText` association assertions pass

## 6. Spec alignment and final validation [both]

- [x] 6.1 Re-read the three spec deltas against the implemented behavior and fix any scenario that does not match. Verify `openspec validate expose-vectordb-index-type --strict` passes
- [x] 6.2 Run backend checks: `uv run ruff check --fix .`, `uv run mypy .`, `uv run pytest tests/unit/operators/vectordb`. Verify all pass with no new warnings
- [x] 6.3 Run frontend checks in `frontend/`: `npm run lint`, TypeScript compilation, `npm run build` and the VectorDB unit tests. Verify all pass and no hex or px literals were added to SCSS
- [x] 6.4 Manual check with a Milvus Lite and an OpenSearch flow: select each offered index type and metric, validate, and create the index. Verify no UI-reachable combination fails at creation, and that an existing flow with `index_type` in Advanced JSON loads with the dropdown pre-populated
  - Verified against real servers: Milvus Lite (`FLAT` x `L2`/`IP`/`COSINE`, unset default, `HNSW` rejected), Milvus standalone v2.6.16 (all 25 CPU dense and binary index type and metric pairs created, stored `index_type` read back for `IVF_SQ8`, `DISKANN`, `BIN_IVF_FLAT`) and OpenSearch 2.14 (all 8 engine and algorithm pairs behave as `applicability` states).
  - Not run by hand: GPU index types (no GPU host; covered by parity tests) and the browser walk-through. The Advanced JSON pre-population case is covered by unit tests.

## Workflow follow-up

- Run `pre-commit run --from-ref origin/main --to-ref HEAD` after committing with `git commit -s`.
- Archive the change after review. If `add-weaviate-vectordb-adapter` archives first, re-run strict validation before archiving this one.
