# Proposal

## Why

The `vectordb` operator can write to OpenSearch and Milvus only. Weaviate is a widely used open-source (BSD-3-Clause) vector database with named vectors, built-in BM25/hybrid search, and a managed cloud offering. Teams that already run it cannot use docpipe as their ingestion pipeline without writing a custom operator. The operator's hexagonal design (`VectorStorePort`, `VectorStoreFactory` lazy registration, per-adapter Pydantic config) was built for exactly this kind of extension. Weaviate can therefore be added as a first-class provider without changing the operator's contract.

A backend adapter alone is not a usable feature. The VectorDB properties panel builds its provider list from operator metadata, but every provider-specific branch in it (connection fields, authentication, managed keys, collection naming, the BM25 toggle) is keyed on `opensearch` or `milvus`, and unknown providers fall back to the OpenSearch configuration. Once the backend lists `weaviate`, the panel would offer it and then render OpenSearch fields. The UI work is therefore part of this change.

**Layer:** full-stack. The backend gets a new storage adapter, metadata enrichment, a dependency, docs, and a sample flow. The frontend gets narrowly scoped VectorDB panel support for the new provider. There are no routing, BFF proxy, or Redux slice changes.

**Delivery:** one change and one set of specs, implemented as stacked pull requests by separate API and UI teams (see Rollout).

## What Changes

### Backend

- **New `weaviate` VectorDB adapter** at `src/docpipe/core/operators/vectordb/adapters/outbound/weaviate/`. It follows the existing Milvus/OpenSearch structure: `adapter.py`, `client.py`, `config.py`, `index_manager.py`, `batch_processor.py`, `resource_metadata.py`. It implements every `VectorStorePort` method:
  - creates a collection, mapping feature mappings to Weaviate properties and each dense vector column to a self-provided **named vector**, so multi-model embeddings are supported;
  - validates an existing collection, including named-vector presence, dimension, and property types, and adds missing scalar properties;
  - batch-inserts with deterministic UUIDv5 object IDs derived from positional chunk primary keys, so re-ingest replaces chunks in place;
  - cleans up stale chunks, deletes by ID, queries by document name, and counts objects.
- **Fixed primary-key property.** The adapter's identity property is always `pk`, distinct from the object UUID, and is `field`-tokenized so prefix matching is exact. A feature mapping that sends the primary feature anywhere else, or sends another feature to `pk`, is rejected at initialization.
- **Lazy registration** of `weaviate` in `vectordb_operator.py` (`VectorStoreFactory.register_lazy`). The operator's `provider_config` JSON-schema map, `provider` valid values, and descriptions now include Weaviate.
- **Flow enrichment.** `VectorDBMetadataFetcher` routes `weaviate` to a new `WeaviateResourceMetadata`. It returns the same five keys as the other providers. Two additive keys appear inside `is_docpipe_supported_resource`: `sparse_eligible` (a keyword-searchable collection can be made supported by turning BM25 on) and `error` (a redacted reason when the deployment is unreachable or rejects the request, so the UI can tell failure from an empty deployment). Other providers never set them.
- **Per-chunk failure attribution.** Failed Weaviate objects are reported in the failed-item shape `VectorDBOperator` already parses.
- **Sparse (BM25) mode.** `add_sparse_vector: true` is supported as server-side BM25 over the mapped content property's inverted index, using Weaviate's own default `k1` and `b`. Sparse-only runs (no dense vectors) create a **keyword-only collection**: one non-indexed named vector, because the client otherwise injects an indexed default vector. Existing keyword-only collections are recognized in both shapes (all vectors skipped, or no named vectors with a skipped legacy vector index). Sparse-only runs work with in-memory chunks only; memory-mapped chunks are an existing operator limitation and out of scope.
- **Server behaviors verified against a live Weaviate.** Stale-chunk cleanup uses keyset paging on `pk`, because offset paging fails past the server's `QUERY_MAXIMUM_RESULTS` window. Identity properties are validated as `field`-tokenized, because word tokenization makes keyset paging silently return nothing after the first page and lets prefix and equality filters match across values that share tokens. Mapped property names with an upper-case first character are rejected, because the server lower-cases the first character. When every object in a write batch fails the client raises one error rather than per-object errors, and the adapter reports the whole batch as failed. The `dynamic` vector index requires a server with async indexing and is refused with an actionable error otherwise.
- **Credential handling.** Authenticated custom connections require TLS on both HTTP and gRPC. Credential fields are flagged sensitive in operator metadata. Credentials accept literal values or `$VAR`/`${VAR}` references, and no configured secret may appear in raised messages or logs.
- **Dependency.** Add `weaviate-client` (v4 API) as a pinned core dependency in both `pyproject.toml` and `slim/pyproject.toml`, and regenerate both lockfiles. Trial resolution against 4.24.1 changed more than the client itself (see design D11), including a `grpcio` downgrade forced by the client's `grpcio<1.80.0` cap. The version is re-checked at implementation time, behind a maintainer-decision gate.
- **Constants.** Add `OperatorConstants.VectorDB.WEAVIATE` and the Weaviate-specific config keys.
- **Testing.** Backend unit tests for every new module (client mocked) run in CI. A Docker-gated real-server suite (`docker/docker-compose.weaviate.yml`) is manual-only, like the existing OpenSearch container tests and the Milvus Lite integration test, which CI also excludes (`pytest tests/unit -m "unit and not integration"`).
- **Docs and samples.** Update `docs/operators/vectordb/vectordb_readme.md` and `docs/reference/OPERATORS.md`, and add `sample_flows/vectordb/weaviate_integration.json`.

### Frontend

- **Provider configuration map.** Add a Weaviate entry (`hasEngine: false`, collection naming rule and placeholder, distance labels and options, sparse capability). Separate the keys stripped before enrichment from the keys hidden from the Advanced JSON field.
- **Connection and authentication controls** in the VectorDB panel: custom versus Weaviate Cloud connection, HTTP and gRPC address and TLS settings, and authentication-method-specific credential inputs. Unset `grpc_host` and `grpc_secure` stay unset so they inherit the HTTP values. Credentials use the existing `VaultInput` (masked literal or `$VAR`/`${VAR}` reference, with the existing Vault toggle for `vault://` references), as the OpenSearch panel does.
- **Validation that blocks.** Required connection and credential fields, and the TLS rule for authenticated custom connections, show accessible inline errors and block opening the feature-mapping tearsheet and enrichment while invalid.
- **Feature-mapping tearsheet.** Provider-specific collection-name rule and placeholder, distance metric selection without an engine control, and a capability- and eligibility-driven BM25 checkbox whose saved state is preserved on reopen, and display of the enrichment `error`. `index_type` and `index_parameters` stay editable in Advanced JSON.
- **Strings.** New strings are colocated message definitions, extracted into the catalogue with `npm run extract:messages`.
- **Compatibility.** OpenSearch and Milvus behavior is unchanged.

No **BREAKING** changes. Existing `opensearch` and `milvus` behavior, configuration, and defaults are unchanged.

## Capabilities

### New Capabilities

The backend specs are split in two so that provider-agnostic behavior is written once and each provider adds only its own contract:

- `backend/vectordb-operator`: the provider-agnostic contract of the `vectordb` operator: provider selection and rejection of unknown providers, the input-table contract, document identity, the sparse retrieval mode, and the transform output and metadata contract. These requirements **describe behavior the operator already has**, verified against the current `VectorDBOperator`, with **two exceptions**: "Document identity" (a null or missing `id` falls back to the document ID, design D5, task 5.5) and "Adapter release after flow validation" (`VectorDBOperator.validate` closes the adapter when it runs under flow validation, design D17, task 5.4) are new behavior. Tasks group 6 adds tests that pin the existing behavior. Future providers reuse this capability instead of restating it.
- `backend/vectordb-weaviate`: the Weaviate provider contract: registration, configuration and credential validation, TLS, authentication, collection creation and validation, the fixed primary key, sparse (BM25) mode, the deterministic-ID upsert and stale-chunk lifecycle, per-chunk failure reporting, secret hygiene, and flow-enrichment metadata.

### Modified Capabilities

- `frontend/properties-panel`: the existing requirement "VectorDB feature mapping and backend configuration" is modified to cover Weaviate. Its two existing scenarios are preserved verbatim in the delta; the added scenarios cover connection and authentication, validation gating, collection naming, distance metrics, BM25, enrichment states, accessibility, and OpenSearch/Milvus compatibility.

## Frontend Carbon components

Existing Carbon React components and tokens only: `Dropdown`, `TextInput`, `NumberInput`-style numeric entry via `TextInput` (as the current panel does), `PasswordInput`, `Toggle`, `Checkbox`, `Accordion`/`AccordionItem`, `TextArea`, `InlineNotification`, `ComboBox`, and the existing `Tearsheet` and `DataTableSkeleton`. New styling reuses the existing `VectorDB.module.scss` and Carbon `var(--cds-*)` tokens.

## Rollout

The change is delivered as a stack:

1. **API PR** (backend team): groups 1-6 in `tasks.md` (all backend).
2. **UI PR** (frontend team), stacked on the API PR: groups 7-8. It can be developed in parallel against the `provider_config` schema and enrichment shape fixed by the specs, with enrichment mocked.
3. **Integrated verification and docs**: group 9, after both are in.

Both PRs MUST ship in the same release. If only the API PR is released, the panel lists `weaviate` and renders the OpenSearch fallback. Merging the UI PR first is harmless, because the provider list comes from operator metadata and does not include `weaviate` until the API PR is in.

## Non-goals

- Frontend changes beyond the VectorDB panel and tearsheet: no routing, BFF proxy, or Redux slice changes, no panel-wide string migration into the message catalogue, and no generic provider-form rewrite.
- A shared Vault credential redesign. The Weaviate credential fields reuse the existing `VaultInput` unchanged.
- Shared lazy validation (letting flow validation skip the connection) and sparse-only support for memory-mapped chunks. Both are operator-wide changes.
- Reimplementing any part of the Weaviate server. The adapter is a client of an existing Weaviate deployment through the official `weaviate-client`.
- Search or query features beyond what `VectorStorePort` requires: no hybrid/BM25/near-vector query API, generative modules, or reranking.
- Server-side vectorizer modules (`text2vec-*`). docpipe always supplies vectors from the `embeddings` operator, so collections use self-provided named vectors only.
- Multi-tenancy, replication/sharding configuration, aliases, backups, RBAC management, and cross-references.
- ACL support. The Weaviate provider neither stores nor enforces the ACL operator's `allowed_users` feature: a mapping for it is dropped with a warning. ACL-enforced reads remain OpenSearch-only.
- OpenSearch schema templates. The operator-level `schema_template_path` option is ignored with a warning.
- Vector quantization/compression configuration. Collections use the server default, including any `DEFAULT_QUANTIZATION` the Weaviate deployment sets.
- Writing to legacy collections that use a single unnamed vector, and adding new named vectors to an existing collection. Both are reported as errors.
- Custom sparse embeddings such as SPLADE. Weaviate has no native sparse-vector field; a `sparse_embeddings` mapping is skipped and retrieval uses BM25.
- Embedded Weaviate. It is experimental and downloads a server binary at runtime.
- Changing OpenSearch or Milvus adapters, `VectorStoreFactory`, or the factory's 500 wrapping of adapter errors.
- A CI job for the real-server suite. It stays manual-only, like the other vector database container tests; a CI job is a possible follow-up.
- Adapter-specific Vault handling. `vault://` references are resolved upstream by the flow executor (and by flow enrichment) before the adapter is built, exactly as for the other adapters; the Weaviate adapter contains no Vault resolution code. During flow validation, where the executor has not resolved references, the adapter skips the connection for a credential that is still the validator's placeholder (design D18).

## Impact

- **Operators:** `vectordb` (`VectorDBOperator`) gains a provider; its chunk keys and stale-chunk lookup now fall back to the document ID when `id` is null or absent (design D5), which changes only flows that previously overwrote each other's chunks or skipped cleanup; and `VectorDBOperator.validate` now releases the adapter's connection when it runs under flow validation (design D17); this applies to every provider and is a no-op for OpenSearch and Milvus clients, whose `close()` is idempotent. No new operator; `DOCPIPE_OPERATORS` is unchanged.
- **Storage adapters:** new `weaviate` outbound adapter package; `VectorStoreFactory` registration in `vectordb_operator.py`; `VectorDBMetadataFetcher` routing.
- **REST routes:** none added or changed. `GET /api/v1/operators` metadata now lists `weaviate` in `provider` valid values and `provider_config.providers`. `POST /api/v1/validation/enrich_flow_features` returns Weaviate metadata for `vectordb` nodes with `provider: "weaviate"`.
- **Frontend:** `frontend/src/components/PropertiesPanel/CustomPanels/VectorDB/` (`constants.ts`, `VectorDB.tsx`, `VectorDBFeatureMappingTearsheet.tsx`, `VectorDB.module.scss`, a colocated messages file) and `frontend/src/i18n/messages_en.json`; extended tests under `frontend/tests/unit/components/PropertiesPanel/CustomPanels/VectorDB/`.
- **Dependencies:** `weaviate-client` (pinned) in `[project.dependencies]` of `pyproject.toml` and `slim/pyproject.toml`; both `uv.lock` files regenerated. Transitive moves include `grpcio` (downgrade) and `authlib` (upgrade).
- **Infrastructure and tests:** new `docker/docker-compose.weaviate.yml` (test-only); new `tests/unit/operators/vectordb/test_weaviate_*.py` and `tests/integration/weaviate/`.
- **Docs:** VectorDB operator README, `docs/reference/OPERATORS.md`, provider enumerations, and a sample flow. `CHANGELOG.md` is not touched.
