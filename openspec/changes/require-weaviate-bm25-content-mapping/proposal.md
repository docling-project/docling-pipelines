# Proposal

## Why

With `add_sparse_vector` on, the Weaviate provider cannot run without a mapping for the content feature, because BM25 scores the mapped content property. Flow enrichment does not say so. It leaves the `content` feature optional (`mandatory_for_vector_db` is false), and for a node that already has saved mappings it returns those mappings unchanged. A client that reads the enrichment response, including the properties panel, therefore lets the user delete the content row or save mappings without it, and the failure appears only when the flow is validated or run. A collection can also end up with a `text` property that no mapping writes to, so BM25 matches nothing.

## What Changes

- Flow enrichment for a Weaviate `vectordb` node with `add_sparse_vector` true marks the content feature `mandatory_for_vector_db: true` in the node's `available_features`. With the flag off, the feature metadata is returned exactly as before.
- The same projection is used on both paths that build a node's feature metadata, so the node's `available_features` and the live metadata response agree.
- With the flag on, enrichment returns a content mapping in `feature_mappings` when the resolved mappings, including saved ones, do not contain one. Existing mappings and their target columns are preserved and no mapping is duplicated.
- No change to the adapter's run-time validation or to the write path.

**Layer:** backend-only. No REST route, DTO, or frontend change. The properties panel already derives the locked row and its warning from `mandatory_for_vector_db`, and it re-reads `feature_mappings` when the BM25 option is toggled.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `backend/vectordb-weaviate`: adds a requirement for how flow enrichment represents the content mapping in sparse (BM25) mode. This capability exists only as a delta in the in-flight change `add-weaviate-vectordb-adapter` until that change is archived (see design, Sequencing).

## Non-goals

- Changing how OpenSearch or Milvus enrichment projects features.
- Adding a Weaviate-specific rule to the frontend, or a save guard for an empty content column. That gap is generic to the mapping table and also affects the other mandatory rows.
- Changing run-time validation, the `sparse_embeddings` handling, or the default-mapping rules for a node without saved mappings.
- Persisting the flag on flows saved before this change. They are corrected the next time enrichment runs.

## Impact

- `src/docpipe/core/operators/vectordb/metadata_fetcher.py`: the router's `project_mappable_features` accepts the node's operator configuration.
- `src/docpipe/core/operators/vectordb/adapters/outbound/weaviate/resource_metadata.py`: the Weaviate projection and the mapping resolution.
- `src/docpipe/core/assets/flows/application/services/flow_enrichment_service.py`: passes the operator configuration to the projection.
- Tests: `tests/unit/operators/vectordb/test_weaviate_resource_metadata.py`, `test_metadata_fetcher.py`, `tests/unit/core/flows/application/services/test_flow_enrichment_service.py`.
- No new dependency and no API contract change. The response keys are unchanged.
