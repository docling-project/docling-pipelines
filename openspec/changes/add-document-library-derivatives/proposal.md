# Proposal

## Why

A pipeline run turns documents into derived data: chunks and embeddings in a vector store (OpenSearch, Milvus) and structured entities in tables (DuckDB, Postgres). Today docpipe forgets where that data went. The only link between a document set and its derived stores is the flow JSON that produced it, which holds raw `provider_config` (including credentials and `${VAR}`/`vault://` references).

The planned retrieval service (`add-retrieval-service`) must answer a question over a document library without the caller knowing which index, collection, embedding model, or entity tables to use. It needs a stored, credential-free description of "what was derived from this document set, and where". That description is also useful on its own: operators and UIs can show where a library's data lives.

This change adds that description (a **derivative record**), records it automatically when a flow completes, and exposes it read-only over REST.

**Layer:** backend-only. No frontend, routing, BFF, or Redux changes.

**Affected REST routes:** new `GET /api/v1/document-libraries/{library_id}/derivatives`.
**Affected operators:** none change behavior. `vectordb`, `entity_store_operator`, `embeddings`, and `document_set` are read through the flow definition and node metadata.
**Affected storage adapters:** the document set metadata repository (DuckDB/Postgres) stores the record under one reserved key of `DocumentSet.metadata`. No schema migration.

## What Changes

- **Derivative domain model** (pure Python, no framework imports): `DocumentSetDerivative` with `vector_stores`, `entity_tables`, and `correlation_details`. Each vector store records provider, non-secret location (index or collection name, host, port, TLS flag), embedding provider/model/dimension, chunk size/type, column mapping, the field that holds the ingest `id`, and a `correlatable` flag. Each entity table group records backend, schema, table names per entity key, and whether it is `retrievable` (persisted backend).
- **`DerivativeRecorder`** (application layer). On successful flow completion it builds a derivative for every `document_set` node from that node's ancestors in the flow DAG (`vectordb`, `embeddings`, `entity_store_operator`) and merges it into the document set's `metadata["derivatives"]`. It never stores credentials. A failed flow does not write. A flow without a `document_set` node writes nothing and logs a warning.
- **Flow-completion hook.** The orchestrator has one lifecycle observer slot used by lineage. Add a `CompositeExecutionObserver` so lineage and the recorder both run, each isolated from the other's failures.
- **`DerivativeQueryService`** (application layer) and **`DerivativeResolverPort`** (domain port). The retrieval service depends on the port, never on document set internals.
- **REST endpoint** `GET /api/v1/document-libraries/{library_id}/derivatives` with `limit` and `bookmark` pagination, returning a redacted DTO view (no filesystem paths, no credentials).
- **Vector `id` mapping check.** The recorder inspects the vectordb feature mappings and sets `id_field` to the chunk field that holds the ingest document `id` (default mappings map `id` to `document_id`). If no mapped field carries it, the store is recorded with `correlatable: false`.
- **In-memory entity stores** (`database_path: ":memory:"`) are recorded with `retrievable: false` because no other process can query them.

No **BREAKING** changes. Documents and libraries created before this change simply have no derivative record and return empty `derivative_stores`.

## Capabilities

### New Capabilities

- `backend/derivatives-api`: the read-only REST contract for listing a library's document-set derivatives, pagination, redaction, and error mapping.
- `backend/derivative-recording`: how and when derivative records are produced at flow completion, their content rules (no secrets, ancestor scoping, correlation flag), persistence by merge, and the resolver port used by consumers.

### Modified Capabilities

- `backend/flow-execution-engine`: lifecycle observers become a composite so that more than one consumer can observe flow completion without one consumer's failure affecting another or the flow result.

## Non-goals

- No retrieval, search, or SQL execution (see `add-retrieval-service`).
- No write or delete API for derivatives. They are system-recorded only.
- No backfill of derivatives for document sets created before this change.
- No new tables or migrations; no `document_id` column added to `EntityStoreOperator` output.
- No UDP-compatible `/udp/v1` routes, `container_id`/`container_type` semantics, `attachments`, or `data_card` fields.
- No ACL filtering of derivative metadata beyond existing document library access rules.
- No Presto/Iceberg derivatives (follow-up through the same model).

## Impact

- New: `src/docpipe/core/assets/derivatives/{domain,application}/`, `src/docpipe/api/routes/derivatives.py` (or added to `document_libraries.py`), `src/docpipe/api/dto/derivative_dto.py`, mapper.
- Changed: `abstract_orchestrator.py` observer wiring, `dependencies.py` (providers), `api_router.py` (if separate router), `error_codes.py` (new codes).
- Dependencies: none.
- Docs: `docs/reference/` API note and OPERATORS cross-reference for the `id` mapping requirement.
