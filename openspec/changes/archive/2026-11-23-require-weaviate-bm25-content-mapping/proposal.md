# Proposal

## Why

With `add_sparse_vector` on, the Weaviate provider cannot run without a mapping for the content feature, because BM25 scores the mapped content property. Flow enrichment does not say so. It leaves the `content` feature optional (`mandatory_for_vector_db` is false), and for a node that already has saved mappings it returns those mappings unchanged. A client that reads the enrichment response, including the properties panel, therefore lets the user delete the content row or save mappings without it, and the failure appears only when the flow is validated or run. A collection can also end up with a `text` property that no mapping writes to, so BM25 matches nothing.

## What Changes

- Flow enrichment for a Weaviate `vectordb` node with `add_sparse_vector` true marks `mandatory_for_vector_db: true` on the feature that supplies the BM25 text in the node's `available_features`: the source of a saved mapping that carries content (for example `title` in `title -> text`), otherwise the `doc_column` feature. With the flag off, the feature metadata is returned exactly as before.
- The same projection is used on both paths that build a node's feature metadata, so the node's `available_features` and the live metadata response agree.
- With the flag on, enrichment returns a content mapping in `feature_mappings` when the resolved mappings, including saved ones, do not contain one. Existing mappings and their target columns are preserved and no mapping is duplicated.
- A content mapping counts only when its target column is non-empty. A saved content row with a blank column is filled in place with the same target a missing row would get, and the adapter's run-time validation rejects it instead of accepting it.
- No change to the write path.

**Layer:** backend-only. No REST route, DTO, or frontend change. The properties panel derives the locked row and its warning from `mandatory_for_vector_db` for rows it shows, and it takes `feature_mappings` from the response when a collection is selected or BM25 is toggled. On opening the mapping tearsheet it shows the node's own saved rows when it has any, so a saved flow that lacks the content row does not gain it from this change alone (see design, D4).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `backend/vectordb-weaviate`: adds a requirement for how flow enrichment represents the content mapping in sparse (BM25) mode. This capability exists only as a delta in the in-flight change `add-weaviate-vectordb-adapter` until that change is archived (see design, Sequencing).

## Non-goals

- Changing how OpenSearch or Milvus enrichment projects features.
- Adding a Weaviate-specific rule to the frontend, or a save guard for an empty content column. That gap is generic to the mapping table and also affects the other mandatory rows.
- Changing the `sparse_embeddings` handling or the default-mapping rules for a node without saved mappings. Run-time validation changes only for the blank-column case above.
- Persisting the flag on flows saved before this change. The next enrichment response carries it, and run-time validation still rejects a flow without content.
- Making the properties panel add a missing mandatory row to saved mappings on open. The same check would also stop Save when a mandatory row has a blank column, which the panel currently omits silently. Both are generic panel behaviors, not specific to Weaviate, and are handled by a separate frontend change (`require-mapped-vectordb-mandatory-features`).

## Impact

- `src/docpipe/core/operators/vectordb/metadata_fetcher.py`: the router's `project_mappable_features` accepts the node's operator configuration.
- `src/docpipe/core/operators/vectordb/adapters/outbound/weaviate/resource_metadata.py`: the Weaviate projection and the mapping resolution.
- `src/docpipe/core/operators/vectordb/adapters/outbound/weaviate/index_manager.py` and `adapter.py`: `WeaviateIndexManager.is_content_mapping` ignores a blank feature name or column, and the property builder skips blank-feature rows.
- `src/docpipe/core/assets/flows/application/services/flow_enrichment_service.py`: passes the operator configuration to the projection.
- Tests: `tests/unit/operators/vectordb/test_weaviate_resource_metadata.py`, `test_metadata_fetcher.py`, `tests/unit/core/flows/application/services/test_flow_enrichment_service.py`.
- No new dependency and no API contract change. The response keys are unchanged.
