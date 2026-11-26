# Design

## Context

`add-document-set-data-card` makes `DocumentSet.data_card` the one system-maintained provenance record. A card has
`flows[] -> details.jobs[] -> runs[] -> operators[]`. For each run it lists the flow's upstream operators and its
downstream `vectordb` / `entity_store` sinks, each with allowlisted, credential-free details:

- `embeddings[]` entries: `provider`, `model_id`, `feature` (the source table column), `dimension_size`.
- `vectordb` entries: `derivative_store` with `name` (provider), `path` (index or collection), `add_sparse_vector`, and
  `feature_mappings` (the explicit `{feature_name, mapped_column_name}` items, or null).
- `entity_store` entries: `derivative_store` with `name` (backend), `path` (DuckDB file or Postgres schema),
  `table_prefix`.
- `propagate_source_acls`: true, false, or null (null only while no run has been recorded).

Operators within a run are ordered upstream to downstream, so an `embeddings` entry that feeds a `vectordb` entry
precedes it. The card records no hosts, credentials, or table names.

This change reads that card and nothing else. It adds no writer.

## Goals / Non-Goals

Goals: a deterministic, credential-free description of what was derived from a document set and where; a resolver port
for consumers; read-only REST views for one document set and for a library; `is_derivative_available` that tells the
truth.

Non-goals: see the proposal.

## DDD layers

```text
core/assets/derivatives/
  domain/
    models/derivative.py            DocumentSetDerivative, VectorStoreDerivative, EntityTableDerivative,
                                    EmbeddingSpec, ColumnMapping, CorrelationDetail, DerivativeConflict, AclState
                                    (dataclasses, no framework imports)
    ports/derivative_resolver.py    DerivativeResolverPort (ABC)  -- consumed by retrieval
    ports/data_card_source.py       DataCardSourcePort (ABC): get_card, get_document_set_name, list_document_set_ids
  application/
    services/derivative_resolution.py     DerivativeResolution (pure, staticmethods: card -> DocumentSetDerivative)
    services/derivative_query_service.py  DerivativeQueryService (implements DerivativeResolverPort)
  adapters/
    data_card_source_adapter.py     DataCardSourcePort over DataCardService, DocumentSetService, DocumentLibraryService
api/dto/derivative_dto.py, api/dto/derivative_mapper.py
api/routes/document_sets.py (one route), api/routes/document_libraries.py (one route + listing fields)
```

Rules respected: application never imports adapters; the factory in `dependencies.py` wires the adapter; routes return
DTOs only; pure helpers are `@staticmethod`; multi-parameter functions are keyword-only. The derivatives bounded
context depends on the document sets context only through `DataCardSourcePort`, so the data card service can change
without touching resolution.

## Decisions

### D1. Compute at read time, store nothing

The card already persists everything needed. Resolving on each request costs one card read per document set and avoids
a second copy that could drift from the card, a second writer, and a migration. A library view reads one card per
document set on the requested page. Libraries are paged (default 100, maximum 1000), so a request is bounded.

**Alternative rejected: persist a derivative record at flow completion** (the earlier version of this change). It
duplicated the card, needed a composite lifecycle observer and its own flow walk, and wrote into user-owned
`DocumentSet.metadata`, which `PATCH` replaces.

### D2. Latest run per flow, union, de-duplicate

`DerivativeResolution.resolve(*, card, ...)` works in four steps.

1. **Select runs.** For each flow in `card.flows`, take the run with the greatest `executed_at` across all of its jobs.
   A run whose timestamp does not parse sorts as the oldest. A flow with no runs contributes nothing.
2. **Collect stores.** From each selected run, collect `vectordb` entries that carry a `derivative_store` with a
   provider and path, and `entity_store` entries that carry a `derivative_store`.
3. **De-duplicate.** Order the collected stores by their run's `executed_at`, newest first. Vector stores are keyed by
   `(provider, path)`, entity stores by `(backend, path, table_prefix)`. The first (newest) occurrence wins.
4. **Report conflicts.** If a later occurrence of a vector store key has a different embedding `model_id` or
   `dimension_size` than the winner, add a `DerivativeConflict(provider, path, kind)` where `kind` is `embedding_model` or
   `embedding_dimension`. The conflict carries no model names, and the REST DTO shows only the kind and the provider.

Only the latest run per flow is used because earlier runs of the same flow describe the same flow definition at an
earlier time. Using all runs would resurrect stores that were later renamed or removed.

A downstream sink that was listed in the card but has not run yet is still returned. The resolver reports what the flow
declared, as the card does. Consumers must treat an unreachable store as unavailable.

### D3. Pairing a vector store with its embedding model

The card keeps `embeddings[]` and `derivative_store` in separate operator entries. For each selected `vectordb` entry
the resolver picks the embedding as follows.

1. If the entry's `feature_mappings` is non-empty, take the first `embeddings` entry of the same run whose `feature`
   equals the `feature_name` of a mapping item. That item's `mapped_column_name` is the vector column.
2. Otherwise (no mappings, or no match), take the nearest `embeddings` entry that precedes the `vectordb` entry in the
   run's `operators` order, that is, the last `embeddings` entry before it. The vector column is then unknown.
3. If the run has no `embeddings` entry, the store has no embedding and is returned with `embedding: null`. Retrieval
   cannot route a store without an embedding model, so it skips it.

When two embedding branches merge before a single `vectordb`, rule 1 picks the one the node maps, and rule 2 picks the
last listed. The other embedding is not represented. This is a documented limitation of one vector field per store.

### D4. Column mapping and correlation

`column_mapping` is derived only from explicit `feature_mappings`, and each key is `null` when it cannot be identified.
The resolver never invents index column names. Consumers apply the `vectordb` operator defaults for nulls, except
`allowed_users`, which has no default.

| Key | Taken from the mapping item whose `feature_name` is |
|---|---|
| `document_id` | `id` |
| `text` | `content` |
| `vector` | the paired embedding's `feature` |
| `sparse` | `sparse_embeddings` |
| `allowed_users` | `allowed_users` |

`correlatable` is false when explicit mappings exist and none maps `id`, and true otherwise. With no mappings the
default `id` to `document_id` applies, so the store is correlatable and `document_id` is `null` in the mapping (a
consumer uses the default).

`correlation_details` has one item when the document set has at least one correlatable vector store and at least one
retrievable entity table: `{vectorstore_column, entity_column: "id", rule: "id-prefix"}`, where `vectorstore_column` is
the mapped `document_id` column or `document_id` when unmapped. The rule means an entity row belongs to document `D`
when its `id` equals `D:<table>` or `D:<table>:<n>`, which is how `EntityStoreOperator` builds row ids. Correlation is
computed on read and not stored.

### D5. Entity tables

An `entity_store` entry resolves to `EntityTableDerivative(backend, schema, table_prefix, retrievable, database_path)`.
`schema` is set for Postgres. `retrievable` is false for a DuckDB store whose path is `:memory:`, because no other
process can query it, and true otherwise. Table names are decided by the curated entity keys at run time and are not in
the card, so they are not enumerated. A consumer that needs the names lists the tables under the prefix itself.
`database_path` stays in the domain object for such a consumer and is dropped by the DTO mapper (D8).

### D6. ACL state

`acl_state` is `protected` when the card's `propagate_source_acls` is true, `unprotected` when it is false, and
`unknown` when it is null or when the document set has no card. `acl_protected` is `acl_state != unprotected`, so it is
true for unknown. This is the fail-closed reading a consumer needs: a set whose provenance was never recorded is not
assumed to be open. A curator can state the truth by `PATCH`ing `propagate_source_acls` on the data card.

### D7. Pagination bookmark

Bookmark = urlsafe base64 of JSON `{"o": <offset>, "v": 1}`. Decoding failure, wrong version, a negative or non-integer
offset gives 400 `derivative_invalid_bookmark`. An offset beyond the end returns an empty page with `next` null. It is
not signed: it contains no secret and is only a position in the library's `document_set_ids` order. A document set that
disappears between pages shifts later pages by one; that is accepted for a read-only listing.

### D8. REST layer and redaction

- **Routes.** `GET /api/v1/document-sets/{document_set_id}/derivatives` and
  `GET /api/v1/document-libraries/{library_id}/derivatives`. Both use `get_current_user`. The library route tolerates
  and ignores `container_id` and `container_type`.
- **DTOs** are built from an explicit field list in `derivative_mapper.py`, so a new domain field is hidden by default.
  The DTO has no `database_path`, no hosts, and no connection fields; the card has none to begin with.
- **404/400.** The routes first resolve the asset through the existing services, so unknown IDs and malformed UUIDs map
  to the same errors as the neighbouring routes (`document_library_not_found`, `document_set_not_found`).
- **Library listing.** `GET /document-libraries/{id}/document-sets` already builds a dict per document set. It adds
  `is_derivative_available` (true when the resolved derivative has at least one vector store or entity table) and
  `propagate_source_acls` from the card, using the metadata value only when the card value is null. It calls the
  resolver once per set already being loaded, so the cost is one card read per listed set.

### D9. Error codes

Add `ErrorCode.DERIVATIVE_INVALID_BOOKMARK` and `DerivativeInvalidBookmarkException(DocpipeException, 400)`.

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| The card lacks a store (sibling-branch `vectordb`, a failed recording) | The view shows what the card holds, with `acl_state` `unknown` when nothing was recorded. The gap is owned by the data card change. Consumers may add their own explicit override. |
| A run that failed after `document_set` still lists its downstream sink | Documented (D2). The view reports declared stores, and a consumer treats an unreachable store as unavailable. |
| Two flows write one store with different embedding models | `conflicts` on the derivative, newest wins. |
| Several embedding branches feed one `vectordb` | Only one is represented (D3). Documented limitation. |
| Library view cost grows with library size | Paged to 1000, one card read per document set on the page. |
| Redaction regression | DTOs from an explicit field list, plus a test that fuzzes cards with secret-like values and path-like values and asserts none reaches the response. |
| `database_path` of an entity store reaches a client | Dropped in the mapper and covered by a redaction test. |
| `is_derivative_available` read cost on the listing | It reuses the card read per listed set. If this proves slow, caching is a follow-up. |

## Migration

None. Existing document sets have no card, or an empty one, and read as empty derivatives with `acl_state` `unknown`.
Rollback is a revert; nothing is stored.

## Open questions

None blocking. Assumed: D2 latest-run-per-flow selection, D3 pairing rules, D7 bookmark shape.
