# Design

## Context

See [proposal.md](proposal.md) for motivation and scope, and [specs/backend/vectordb-weaviate/spec.md](specs/backend/vectordb-weaviate/spec.md) for the requirement.

**Current behavior.**

- `FlowEnrichmentService` builds a `vectordb` node's `available_features` by calling `VectorDBMetadataFetcher.project_mappable_features(adapter_name, available_features)`. The call does not receive the node's operator configuration.
- The Weaviate projection only drops the sparse-vector feature. The content feature keeps `mandatory_for_vector_db: false`, so a client cannot tell that BM25 needs it.
- `WeaviateResourceMetadata.fetch` projects features again with the same signature, then resolves `feature_mappings` in `_resolve_feature_mappings`: saved mappings first, then the live collection schema, then `compute_default_feature_mappings`. Rule 5 of the defaults maps `content` to `text` in BM25 mode, but the saved-mappings and live-schema branches return without it.
- The adapter's `_mapping_problems` rejects `add_sparse_vector` without a content mapping, using `WeaviateIndexManager.is_content_mapping` (feature or column named `content` or `text`). This is the run-time guard and stays as it is.

**Constraints.**

- The shared upstream feature map is reused by other nodes. It must not be mutated.
- `project_mappable_features` is shared by three providers. OpenSearch and Milvus behavior must not change.
- Saved mappings are user data. Enrichment may add to them but must not rewrite or reorder them.

## Decisions

### D1. Projection receives the operator configuration

`VectorDBMetadataFetcher.project_mappable_features` gains an optional keyword `operator_config: dict[str, Any] | None = None`. The Weaviate projection, both `WeaviateResourceMetadata.project_mappable_features` and the module-level wrapper, takes the same optional argument. The OpenSearch and Milvus projections are not touched, so the router passes `operator_config` only to Weaviate. `FlowEnrichmentService` passes `node_feature_result["operator_config"]`, and `WeaviateResourceMetadata.fetch` passes its own `operator_config`. Both paths use the same function, so `available_features` on the node and in the live metadata agree.

The content feature name is `operator_config["doc_column"]`, default `content`, the same lookup `_default_feature_mappings_from_features` and `VectorDBOperator` use. `add_sparse_vector` is read from the node's top level, as `fetch` already does.

### D2. Copy on write

When `add_sparse_vector` is true and the content feature is present, the projection returns a new dict with a shallow copy of that feature's metadata and `mandatory_for_vector_db: True`. Other entries are the original objects, and the input mapping is never written to. When the flag is off, or the feature is absent, the projection returns exactly what it returned before.

The sparse-vector feature is still dropped in both modes.

### D3. Completing saved and live-schema mappings

`_resolve_feature_mappings` is left as it is. A new static helper in `resource_metadata.py` runs on its result in `fetch`:

1. If `add_sparse_vector` is false, or the content feature is not in the projected features, return the mappings unchanged.
2. If any mapping satisfies `WeaviateIndexManager.is_content_mapping`, or the content feature already has a mapping to any column, return the mappings unchanged. The first test keeps enrichment equivalent to run-time validation; the second means an explicit user mapping such as `content -> body` is never duplicated or rewritten.
3. Otherwise return a new list: the original mappings in order, followed by `{feature_name: <content feature>, mapped_column_name: <target>}`.

The target is the selected collection's searchable content property when it has one (`content` or `text`, as `_content_property` already resolves), and `text` otherwise. Because both names satisfy `is_content_mapping`, the appended target can never collide with a column another feature already uses.

Running the helper last covers every branch: saved mappings, live schema with no content property, and defaults. For defaults it is a no-op, because rule 5 already maps the content feature. A second enrichment with the returned mappings as input takes step 2 and returns them unchanged, which gives the idempotence scenario.

The `is_docpipe_supported_resource` verdict is computed from the mappings before completion, so it does not change for any existing collection. Completion only changes `feature_mappings`.

### D4. Interaction with the properties panel

`buildVectorDBEnrichmentFlow` in the frontend clears saved `feature_mappings` before every enrichment request and patches `add_sparse_vector` at the node's top level. The panel therefore receives backend defaults or live-schema mappings, and Rule 5 already supplies the content row there. What it gains from this change is `mandatory_for_vector_db: true` on the content feature, which it already turns into a locked row with a warning.

The saved-mapping completion in D3 mainly serves clients that send saved mappings: the REST API, the Python API and tooling. It is deliberately in the backend so that every client sees the same contract.

### D5. Layer boundaries

All changes are in the adapter's read-only metadata module, the metadata router, and the application service that calls it. No port, domain model, DTO or route changes. The write path (`adapter.py`, `index_manager.py`, `batch_processor.py`) is untouched.

## Alternatives considered

- **Frontend-only lock for Weaviate.** Rejected: it would not help non-UI clients and would add a provider-specific rule to a provider-agnostic panel.
- **Set the flag on the shared feature map.** Rejected: the map is shared, and the flag is valid only for a Weaviate node with BM25 on.
- **Always mark content mandatory for Weaviate.** Rejected: without BM25 the content mapping is optional, and the metadata should not claim otherwise.
- **Rewrite saved mappings that violate the content rule, such as moving a mapped content feature to `text`.** Rejected: the mapping is user data, and run-time validation already reports it.

## Risks and trade-offs

- **Sequencing.** `backend/vectordb-weaviate` exists in `openspec/specs/` only after `add-weaviate-vectordb-adapter` is archived. This change adds one requirement to that capability. Archive it after `add-weaviate-vectordb-adapter`, or, if it must go first, expect the archive to create the capability with only this requirement and the other change to merge into it. Neither order breaks validation, because both deltas use `ADDED Requirements`.
- **Flows saved earlier** do not carry the flag until enrichment runs again. Run-time validation still protects them.
- **A mapped content feature with a non-content target** (for example `body -> body` when `doc_column` is `body`) is left as the user wrote it and still fails run-time validation. Enrichment does not guess a replacement.
- **Signature change.** The new argument is optional, so existing callers and tests keep working.

## Test strategy

Behavior is asserted on the returned contract, not on internals:

- Projection: flag set only with BM25 on, content feature copied, input mapping and its values unchanged, the configured `doc_column`, the content feature absent, OpenSearch and Milvus unchanged.
- Mappings: saved mappings without content get one appended row; `content -> body` is preserved; a mapping to `text` or `content` blocks the append; the live-schema target is used when the collection has a searchable content property; repeating the call with its own output is stable; BM25 off returns saved mappings unchanged.
- Enrichment response: for a Weaviate node with BM25 on, the node's `available_features` and the metadata `feature_mappings` carry both the flag and the content row.
- Validation: the existing adapter test for the missing content mapping keeps passing.
