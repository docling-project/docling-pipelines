# Design

## Context

See [proposal.md](proposal.md) for motivation and scope, and [specs/backend/vectordb-weaviate/spec.md](specs/backend/vectordb-weaviate/spec.md) for the requirement.

**Current behavior.**

- `FlowEnrichmentService` builds a `vectordb` node's `available_features` by calling `VectorDBMetadataFetcher.project_mappable_features(adapter_name, available_features)`. The call does not receive the node's operator configuration.
- The Weaviate projection only drops the sparse-vector feature. The content feature keeps `mandatory_for_vector_db: false`, so a client cannot tell that BM25 needs it.
- `WeaviateResourceMetadata.fetch` projects features again with the same signature, then resolves `feature_mappings` in `_resolve_feature_mappings`: saved mappings first, then the live collection schema, then `compute_default_feature_mappings`. Rule 5 of the defaults maps `content` to `text` in BM25 mode, but the saved-mappings and live-schema branches return without it.
- The adapter's `_mapping_problems` rejects `add_sparse_vector` without a content mapping, using `WeaviateIndexManager.is_content_mapping` (feature or column named `content` or `text`). Before this change the predicate looked only at names, so `content -> ""` satisfied it although a blank column writes nothing (see D5).

**Constraints.**

- The shared upstream feature map is reused by other nodes. It must not be mutated.
- `project_mappable_features` is shared by three providers. OpenSearch and Milvus behavior must not change.
- Saved mappings are user data. Enrichment may add to them but must not rewrite or reorder them.

## Decisions

### D1. Projection receives the operator configuration

`VectorDBMetadataFetcher.project_mappable_features` gains an optional keyword `operator_config: dict[str, Any] | None = None`. The Weaviate projection, both `WeaviateResourceMetadata.project_mappable_features` and the module-level wrapper, takes the same optional argument. The OpenSearch and Milvus projections are not touched, so the router passes `operator_config` only to Weaviate. `FlowEnrichmentService` passes `node_feature_result["operator_config"]`, and `WeaviateResourceMetadata.fetch` passes its own `operator_config`. Both paths use the same function, so `available_features` on the node and in the live metadata agree.

The content feature name is `operator_config["doc_column"]`, default `content`, the same lookup `_default_feature_mappings_from_features` and `VectorDBOperator` use. `add_sparse_vector` is read from the node's top level, as `fetch` already does.

### D2. Mandatory features and copy on write

When `add_sparse_vector` is true, the projection computes the set of features that supply the BM25 text:

1. the source features of the node's saved mappings that satisfy `WeaviateIndexManager.is_content_mapping` (feature or column named `content` or `text`) and are present in the projected features; or, when there are none,
2. the `doc_column` feature, when present.

For each feature in that set the projection returns a shallow copy of its metadata with `mandatory_for_vector_db: True`. Other entries are the original objects and the input mapping is never written to. This ties the flag to the same predicate the adapter uses at run time, so the row that is locked is the row that satisfies validation: `title -> text` locks `title`, and `content` stays optional. Several qualifying mappings lock each of their sources.

With the flag off, or when the set is empty, the projection returns exactly what it returned before. The sparse-vector feature is still dropped in both modes.

### D3. Completing saved and live-schema mappings

`_resolve_feature_mappings` is left as it is. A new static helper in `resource_metadata.py` runs on its result in `fetch`:

1. If `add_sparse_vector` is false, or the content feature is not in the projected features, return the mappings unchanged.
2. If any mapping satisfies `WeaviateIndexManager.is_content_mapping`, or the content feature already has a mapping to any column, return the mappings unchanged. In the first case the mapped source is already the mandatory feature (D2). The first test keeps enrichment equivalent to run-time validation; the second means an explicit user mapping such as `content -> body` is never duplicated or rewritten.
3. Otherwise return a new list: the original mappings in order, followed by `{feature_name: <content feature>, mapped_column_name: <target>}`.

The target is the selected collection's searchable content property when it has one (`content` or `text`, as `_content_property` already resolves), and `text` otherwise. Because both names satisfy `is_content_mapping`, the appended target can never collide with a column another feature already uses.

Running the helper last covers every branch: saved mappings, live schema with no content property, and defaults. For defaults it is a no-op, because rule 5 already maps the content feature. A second enrichment with the returned mappings as input takes step 2 and returns them unchanged, which gives the idempotence scenario.

The `is_docpipe_supported_resource` verdict is computed from the mappings before completion, so it does not change for any existing collection. Completion only changes `feature_mappings`.

### D4. Interaction with the properties panel

`buildVectorDBEnrichmentFlow` clears saved `feature_mappings` before every enrichment request and patches `add_sparse_vector` at the node's top level. The response therefore holds backend defaults or live-schema mappings, and Rule 5 already supplies the content row there. Because the request carries no saved mappings, the flagged feature is `doc_column`.

What the panel does with the response depends on the moment:

- **After the user selects a collection or toggles BM25**, the tearsheet builds its rows from the response only. The content row is present and locked, which is the case this change fixes.
- **On opening the tearsheet**, `buildTableRows` uses the node's own saved rows whenever there are any, and takes only descriptions and mandatory flags from the response. For a saved BM25 flow that lacks a content row, the response flags `content` and returns a `content -> text` mapping, but no row is shown for it and Save writes the saved rows again. This change alone does not repair that case in the panel.

The saved flow is still protected at validation and run time by the adapter's existing check. Showing a missing mandatory row on open would be a generic panel change that applies to every provider and every mandatory feature. It is out of scope here (proposal, Non-goals) and is handled by the separate frontend change `require-mapped-vectordb-mandatory-features`, which also blocks Save while a mandatory feature has no mapped column.

The saved-mapping completion in D3 serves clients that read `feature_mappings` from the response and apply it: the REST API, the Python API and tooling. It is in the backend so that those clients see one contract.

### D5. Blank target columns

A mapping with an empty or whitespace-only target column writes no property, so BM25 would match nothing. `WeaviateIndexManager.is_content_mapping` returns false for such a mapping. This one predicate is shared by the adapter's run-time guard, the projection (D2) and the completion helper (D3), so the three stay equivalent:

- Run time: `content -> ""` no longer satisfies the guard, so validation reports the existing "mapping for the content feature is required" message. No new message, no new code path.
- Projection: a blank content row does not count as a saved content mapping, so the `doc_column` feature is the one marked mandatory.
- Completion: step 2 of D3 no longer treats a blank row as blocking. If the content feature has a blank-column row and no other mapping carries content, that row is replaced in place by the content mapping (same position, same target rule), and any further blank rows of the content feature are dropped so no second mapping appears. A non-blank mapping of the content feature, or any non-blank content-carrying mapping, still blocks the change, so `content -> body` stays as written.

The write path already skips mappings with an empty feature or column when it builds properties, so no write-path change is needed.

### D6. Layer boundaries

All changes are in the adapter's read-only metadata module, the metadata router, and the application service that calls it. No port, domain model, DTO or route changes. The write path (`adapter.py`, `index_manager.py`, `batch_processor.py`) is untouched.

## Alternatives considered

- **Frontend-only lock for Weaviate.** Rejected: it would not help non-UI clients and would add a provider-specific rule to a provider-agnostic panel.
- **Set the flag on the shared feature map.** Rejected: the map is shared, and the flag is valid only for a Weaviate node with BM25 on.
- **Always mark content mandatory for Weaviate.** Rejected: without BM25 the content mapping is optional, and the metadata should not claim otherwise.
- **Rewrite saved mappings that violate the content rule, such as moving a mapped content feature to `text`.** Rejected: the mapping is user data, and run-time validation already reports it.

## Risks and trade-offs

- **Sequencing.** `backend/vectordb-weaviate` exists in `openspec/specs/` only after `add-weaviate-vectordb-adapter` is archived. This change adds one requirement to that capability. Archive it after `add-weaviate-vectordb-adapter`, or, if it must go first, expect the archive to create the capability with only this requirement and the other change to merge into it. Neither order breaks validation, because both deltas use `ADDED Requirements`.
- **Flows saved earlier** do not carry the flag until enrichment runs again, and the panel does not add a missing content row to saved rows on open (D4). Run-time validation still protects them.
- **A mapped content feature with a non-content target** (for example `body -> body` when `doc_column` is `body`) is left as the user wrote it and still fails run-time validation. Enrichment does not guess a replacement.
- **Signature change.** The new argument is optional, so existing callers and tests keep working.

## Test strategy

Behavior is asserted on the returned contract, not on internals:

- Projection: flag set only with BM25 on, the mandatory feature copied, input mapping and its values unchanged, the configured `doc_column`, a saved `title -> text` locking `title` and leaving `content` unchanged, several qualifying mappings, the content feature absent, OpenSearch and Milvus unchanged.
- Blank column: `is_content_mapping` is false for an empty or whitespace column; the guard rejects `content -> ""`; completion fills it in place and keeps the other rows; a blank row next to a real content mapping is left alone.
- Mappings: saved mappings without content get one appended row; `content -> body` is preserved; a mapping to `text` or `content` blocks the append; the live-schema target is used when the collection has a searchable content property; repeating the call with its own output is stable; BM25 off returns saved mappings unchanged.
- Enrichment response: for a Weaviate node with BM25 on, the node's `available_features` and the metadata `feature_mappings` carry both the flag and the content row.
- Validation: the existing adapter test for the missing content mapping keeps passing.
