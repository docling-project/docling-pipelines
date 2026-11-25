# Tasks

Layer for every task: [backend].

## 1. Projection

- [x] 1.1 [backend] Add the optional `operator_config` argument to `VectorDBMetadataFetcher.project_mappable_features` and forward it to the Weaviate projection only. Verify: existing calls without the argument behave as before.
- [x] 1.2 [backend] In `resource_metadata.py`, accept `operator_config` in `WeaviateResourceMetadata.project_mappable_features` and the module-level wrapper. With `add_sparse_vector` true, return copies with `mandatory_for_vector_db: True` of the sources of saved content-carrying mappings, or of the `doc_column` feature when there are none (design D2); otherwise return what it returned before. Verify: the input mapping and its values are unchanged after the call, and a saved `title -> text` locks `title` and not `content`.
- [x] 1.3 [backend] Pass `operator_config` from `WeaviateResourceMetadata.fetch` and from `FlowEnrichmentService` (the `vectordb` branch) into the projection. Verify: the node's `available_features` and the metadata response agree.

## 2. Mapping completion

- [x] 2.1 [backend] Add a static helper that appends the content mapping as described in design D3, and call it in `fetch` on the output of `_resolve_feature_mappings`, before the response is built and after the support verdict is computed. Verify: saved mappings are preserved in order; an existing content mapping or a mapping of the content feature blocks the append; repeating with the returned mappings is stable.
- [x] 2.2 [backend] Resolve the target from the selected collection's searchable content property, falling back to `text`. Verify: an existing collection with a searchable `content` property gets `content`, one without gets `text`.

## 2b. Blank target column

- [x] 2b.1 [backend] In `WeaviateIndexManager.is_content_mapping`, return false when the feature name or the column is empty or whitespace-only (design D5). Verify: the adapter guard rejects `content -> ""` and `"" -> text` with the existing message, and `content -> text` is still accepted.
- [x] 2b.2 [backend] In the completion helper, fill a blank-column row of the content feature in place instead of treating it as mapped, dropping any further blank rows of that feature. Verify: the row keeps its position, other mappings are unchanged, a non-blank content mapping still blocks, and repeating is stable.

## 3. Tests

- [x] 3.1 [backend] `tests/unit/operators/vectordb/test_weaviate_resource_metadata.py`: projection cases (BM25 on and off, configured `doc_column`, saved `title -> text`, several qualifying mappings, feature absent, input not mutated) and mapping cases (saved without content, blank content column filled in place, blank feature name does not block the append and the completed mappings pass adapter validation, blank row beside a real content mapping untouched, `content -> body` preserved, mapping to `text` blocks the append, collection target, repeat is stable, `is_docpipe_supported_resource` unchanged).
- [x] 3.2 [backend] `tests/unit/operators/vectordb/test_metadata_fetcher.py`: the router forwards `operator_config` to Weaviate, and the OpenSearch and Milvus projections are unchanged.
- [x] 3.3 [backend] `tests/unit/core/flows/application/services/test_flow_enrichment_service.py`: the enrichment response for a Weaviate node with BM25 on carries `mandatory_for_vector_db: true` for the content feature and the content row in `feature_mappings`; with BM25 off it does not.

## 4. Validation

- [x] 4.1 [backend] `uv run pytest tests/unit/operators/vectordb tests/unit/core/flows -q` passes, including the existing missing-content validation test.
- [x] 4.2 [backend] `uv run ruff check --fix .` and `uv run mypy .` report nothing new.
- [x] 4.3 [backend] `openspec validate require-weaviate-bm25-content-mapping --strict` passes.
- [x] 4.4 [backend] Manual check against the local Weaviate container: enrich a node with BM25 on and saved mappings that lack content, and confirm the response carries the flag and the `content -> text` row; run the flow and confirm `text{count}` equals the object count.
