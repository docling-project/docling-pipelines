# Proposal

## Why

`add-document-set-data-card` gives every document set a provenance record: which flows and runs wrote it, which
embedding model and vector index its chunks went to, and where its entity tables live. The card is a log of *runs*. It
is nested by flow, job, and run, it can hold several flows that disagree, and each vector store's embedding model sits
in a different operator entry than the store itself. Nobody can read "where is this document set's searchable data, and
how do I query it" straight off the card.

Document sets and document libraries are the assets people actually work with, and today neither tells them what was
derived from them. The `is_derivative_available` field on the document sets of a library exists but is read from
user-owned `metadata`, so it is always `null` unless someone set it by hand. The planned retrieval service
(`add-retrieval-service`) also needs a resolved, credential-free answer per document set, without walking cards itself.

This change turns the data card into that answer, for one document set and for a whole library, and exposes it over
REST. It builds on the data card only: it records nothing, it adds no operator or orchestrator hook, and it stores no
second copy of the facts.

**Layer:** backend-only. No frontend, routing, BFF, or Redux changes.

**Depends on:** `add-document-set-data-card` (the card model, its recording, and the facts this change reads:
`derivative_store`, `feature_mappings`, `embeddings[].provider`, `add_sparse_vector`, entity store location, and the
three-state `propagate_source_acls`). **Used by:** `add-retrieval-service` and `add-retrieval-agent`, through
`DerivativeResolverPort`.

## What Changes

- **Derivative domain model** (pure Python, no framework imports): `DocumentSetDerivative` with `vector_stores`,
  `entity_tables`, `correlation_details`, `acl_state`, `acl_protected`, descriptive hints (`purpose`, `summary`,
  `language`), and `conflicts`. It is computed from a document set's card at read time. Nothing is persisted.
- **`DerivativeResolverPort`** (domain port) and **`DerivativeQueryService`** (application). The service reads the card
  through a small `DataCardSourcePort`, so the derivatives code never imports document set internals or adapters.
  The retrieval service depends on the resolver port only.
- **Resolution rules**, one deterministic function from card to derivatives:
  - take the latest run of each flow, union their `vectordb` and `entity_store` entries, and return each store once;
  - pair each vector store with its embedding model by the recorded `feature_mappings`, or, with no mappings, by the
    nearest preceding `embeddings` entry;
  - turn `feature_mappings` into a `column_mapping` (document id, text, vector, sparse, `allowed_users` columns) and a
    `correlatable` flag;
  - report `conflicts` when one store is recorded with different embedding models or dimensions;
  - map the three-state `propagate_source_acls` to `acl_state` (`protected`, `unprotected`, `unknown`) and a fail-closed
    `acl_protected` (true unless the card says false).
- **Document set REST API.** New `GET /api/v1/document-sets/{document_set_id}/derivatives` returns the derivatives of
  one document set.
- **Document library REST API.** New `GET /api/v1/document-libraries/{library_id}/derivatives` returns the derivatives
  of every document set in the library, in the library's order, with `limit` and opaque `bookmark` pagination.
- **Document library listing.** `GET /api/v1/document-libraries/{library_id}/document-sets` now reports
  `is_derivative_available` computed from the derivatives and `propagate_source_acls` from the card (falling back to
  the existing metadata value only when the card value is null). The response shape does not change.
- **Redacted view.** The REST DTOs are built from an explicit field list. They never contain credentials, `${VAR}` or
  `vault://` references, hosts, connection strings, or a DuckDB file path. The domain object keeps the entity store
  `database_path` so that a consumer can open it.
- **Error codes.** `DERIVATIVE_INVALID_BOOKMARK` (400) is added; unknown libraries and document sets reuse the
  existing not-found codes.

No **BREAKING** changes. Document sets without a card, and libraries created before the data card existed, return empty
derivative lists, `acl_state` `unknown`, and `is_derivative_available` false.

## Capabilities

### New Capabilities

- `backend/derivative-resolution`: how a data card becomes derivatives (latest run per flow, union and de-duplication,
  embedding pairing, column mapping, correlation, conflicts, ACL state), plus the `DerivativeResolverPort` contract.
- `backend/derivatives-api`: the read-only REST contract for the derivatives of one document set and of a document
  library: shape, pagination, redaction, authentication, and error mapping.

### Modified Capabilities

- `backend/document-libraries-api`: the document sets listed for a library report `is_derivative_available` and
  `propagate_source_acls` from the card.

## Non-goals

- **No recording.** The card is written by `add-document-set-data-card`. This change adds no recorder, no composite
  lifecycle observer, no change to the orchestrator, and no `DocumentSet.metadata` key. A derivative missing from the
  card (for example a `vectordb` on a sibling branch) is a gap in the card, not something this change patches.
- **No write or delete API** for derivatives, and no backfill for document sets without a card.
- **No retrieval, search, or SQL execution** (see `add-retrieval-service`). Entity tables are reported by location
  and prefix; their table names are not enumerated and no table is opened.
- **No `include=derivatives` expansion** on existing document set or library responses.
- **No frontend** page or Redux slice.
- **No UDP-compatible routes**, `container_id` / `container_type` semantics (they are tolerated and ignored),
  `attachments`, or CAMS concepts.
- **No new tables, migrations, or dependencies.**

## Impact

- New: `src/docpipe/core/assets/derivatives/{domain,application,adapters}/`, `src/docpipe/api/dto/derivative_dto.py`
  and mapper, derivative routes added to `src/docpipe/api/routes/document_sets.py` and `document_libraries.py`.
- Changed: `src/docpipe/api/dependencies.py` (providers), `src/docpipe/api/routes/document_libraries.py` (the
  document-sets listing fields), `src/docpipe/exceptions/error_codes.py` and an exception class for the bookmark.
- Dependencies: none.
- Docs: `docs/api/REST_API_SERVER.md`, `docs/guides/USER_GUIDE_DOCUMENT_LIBRARIES.md` (the two
  `is_derivative_available` examples), and a section in `docs/guides/DOCUMENT_SET_DATA_CARD.md` pointing at the view.
