# Tasks

Layer for every task: [backend].

## 1. Projection

- [ ] 1.1 [backend] Add the optional `operator_config` argument to `VectorDBMetadataFetcher.project_mappable_features` and forward it to the Weaviate projection only. Verify: existing calls without the argument behave as before.
- [ ] 1.2 [backend] In `resource_metadata.py`, accept `operator_config` in `WeaviateResourceMetadata.project_mappable_features` and the module-level wrapper. With `add_sparse_vector` true and the `doc_column` feature present, return a copy of that feature with `mandatory_for_vector_db: True`; otherwise return what it returned before. Verify: the input mapping and its values are unchanged after the call.
- [ ] 1.3 [backend] Pass `operator_config` from `WeaviateResourceMetadata.fetch` and from `FlowEnrichmentService` (the `vectordb` branch) into the projection. Verify: the node's `available_features` and the metadata response agree.

## 2. Mapping completion

- [ ] 2.1 [backend] Add a static helper that appends the content mapping as described in design D3, and call it in `fetch` on the output of `_resolve_feature_mappings`, before the response is built and after the support verdict is computed. Verify: saved mappings are preserved in order; an existing content mapping or a mapping of the content feature blocks the append; repeating with the returned mappings is stable.
- [ ] 2.2 [backend] Resolve the target from the selected collection's searchable content property, falling back to `text`. Verify: an existing collection with a searchable `content` property gets `content`, one without gets `text`.

## 3. Tests

- [ ] 3.1 [backend] `tests/unit/operators/vectordb/test_weaviate_resource_metadata.py`: projection cases (BM25 on and off, configured `doc_column`, feature absent, input not mutated) and mapping cases (saved without content, `content -> body` preserved, mapping to `text` blocks the append, collection target, repeat is stable, `is_docpipe_supported_resource` unchanged).
- [ ] 3.2 [backend] `tests/unit/operators/vectordb/test_metadata_fetcher.py`: the router forwards `operator_config` to Weaviate, and the OpenSearch and Milvus projections are unchanged.
- [ ] 3.3 [backend] `tests/unit/core/flows/application/services/test_flow_enrichment_service.py`: the enrichment response for a Weaviate node with BM25 on carries `mandatory_for_vector_db: true` for the content feature and the content row in `feature_mappings`; with BM25 off it does not.

## 4. Validation

- [ ] 4.1 [backend] `uv run pytest tests/unit/operators/vectordb tests/unit/core/flows -q` passes, including the existing missing-content validation test.
- [ ] 4.2 [backend] `uv run ruff check --fix .` and `uv run mypy .` report nothing new.
- [ ] 4.3 [backend] `openspec validate require-weaviate-bm25-content-mapping --strict` passes.
- [ ] 4.4 [backend] Manual check against the local Weaviate container: enrich a node with BM25 on and saved mappings that lack content, and confirm the response carries the flag and the `content -> text` row; run the flow and confirm `text{count}` equals the object count.
