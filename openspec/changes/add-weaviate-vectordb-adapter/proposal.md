# Proposal

## Why

The `vectordb` operator can write to OpenSearch and Milvus only. Weaviate is a widely used open-source (BSD-3-Clause) vector database with named vectors, built-in BM25/hybrid search, and a managed cloud offering. Teams that already run it cannot use docpipe as their ingestion pipeline without writing a custom operator. The operator's hexagonal design (`VectorStorePort`, `VectorStoreFactory` lazy registration, per-adapter Pydantic config) was built for exactly this kind of extension. Weaviate can therefore be added as a first-class provider without changing the operator's contract.

**Layer:** backend-only. The backend gets a new storage adapter, metadata enrichment, a dependency, docs, and a sample flow. There are no frontend, routing, BFF proxy, or Redux slice changes.

## What Changes

- **Backend: new `weaviate` VectorDB adapter** at `src/docpipe/core/operators/vectordb/adapters/outbound/weaviate/`. It follows the existing Milvus/OpenSearch structure: `adapter.py`, `client.py`, `config.py`, `index_manager.py`, `batch_processor.py`, `resource_metadata.py`. It implements every `VectorStorePort` method:
  - creates a collection, mapping feature mappings to Weaviate properties and each dense vector column to a self-provided **named vector**, so multi-model embeddings are supported;
  - validates an existing collection, including named-vector presence, dimension, and property types, and adds missing scalar properties;
  - batch-inserts with deterministic UUIDv5 object IDs derived from positional chunk primary keys, so re-ingest replaces chunks in place;
  - cleans up stale chunks, deletes by ID, queries by document name, and counts objects.
- **Backend: lazy registration** of `weaviate` in `vectordb_operator.py` (`VectorStoreFactory.register_lazy`). The operator's `provider_config` JSON-schema map, `provider` valid values, and descriptions now include Weaviate.
- **Backend: flow enrichment.** `VectorDBMetadataFetcher` routes `weaviate` to a new `WeaviateResourceMetadata`. It returns the same five keys as the other providers: available collections, selected collection schema, feature mappings, supported-resource check, and stored distance metric and dimension.
- **Backend: per-chunk failure attribution.** Failed Weaviate objects are reported in the failed-item shape `VectorDBOperator` already parses, so each failed chunk is attributed to its parent document in run metadata.
- **Backend: sparse (BM25) mode, at parity with Milvus.** `add_sparse_vector: true` is supported. docpipe's Milvus sparse mode is server-computed BM25 over the `text` field (the `sparse_embeddings` feature is never inserted), and Weaviate's equivalent is BM25 over the keyword index of the mapped content property. The flag enables sparse-only runs with no dense embeddings, hybrid dense-plus-BM25 collections, Milvus's BM25 parameters (k1 = 1.2, b = 0.75), a check that content is mapped, and sparse-aware validation and enrichment. Content stays keyword-searchable when the flag is off.
- **Backend: dependency.** Add `weaviate-client` (v4 API) as a pinned core dependency alongside `pymilvus` and `opensearch-py`, and regenerate `uv.lock`. **Risk:** `weaviate-client` 4.23.1 caps `grpcio<1.80.0`, while the lock currently resolves `grpcio==1.84.0`. Resolving the lock is a gating task (see design).
- **Backend: constants.** Add `OperatorConstants.VectorDB.WEAVIATE` and the Weaviate-specific config keys.
- **Testing:**
  - backend unit tests for every new module, with the Weaviate client mocked;
  - operator-level tests with `provider: "weaviate"`;
  - a Docker-gated integration suite against a real Weaviate server (`docker/docker-compose.weaviate.yml`) that skips cleanly when Docker is unavailable.
- **Docs and samples:** update `docs/operators/vectordb/vectordb_readme.md` and `docs/reference/OPERATORS.md`, and add `sample_flows/vectordb/weaviate_integration.json`.

No **BREAKING** changes. Existing `opensearch` and `milvus` behavior, configuration, and defaults are unchanged.

## Capabilities

### New Capabilities

The specs are split in two so that provider-agnostic behavior is written once and each provider adds only its own contract:

- `backend/vectordb-operator`: the provider-agnostic contract of the `vectordb` operator: provider selection and rejection of unknown providers, the input-table contract, and the transform output and metadata contract. The project has no existing VectorDB operator specification. Future providers reuse this capability instead of restating it.
- `backend/vectordb-weaviate`: the Weaviate provider contract: registration in operator metadata, connection and configuration validation, authentication, collection creation and validation, sparse (BM25) retrieval mode, the deterministic-ID upsert and stale-chunk lifecycle, per-chunk failure reporting, and Weaviate flow-enrichment metadata. It also covers how OpenSearch-only options (ACL fields, schema templates) are handled.

### Modified Capabilities

None.

## Non-goals

- Frontend configuration and UI changes.
- Reimplementing any part of the Weaviate server. The adapter is a client of an existing Weaviate deployment through the official `weaviate-client`.
- Search or query features beyond what `VectorStorePort` requires: no hybrid/BM25/near-vector query API, generative modules, or reranking.
- Server-side vectorizer modules (`text2vec-*`). docpipe always supplies vectors from the `embeddings` operator, so collections use self-provided named vectors only.
- Multi-tenancy, replication/sharding configuration, aliases, backups, RBAC management, and cross-references.
- ACL support. The Weaviate provider neither stores nor enforces the ACL operator's `allowed_users` feature: a mapping for it is dropped with a warning. ACL-enforced reads remain OpenSearch-only.
- OpenSearch schema templates. The operator-level `schema_template_path` option is ignored with a warning; collection schemas come from feature mappings only.
- Vector quantization/compression configuration (PQ/BQ/SQ/RQ). Collections use the server default, including any `DEFAULT_QUANTIZATION` the operator of the Weaviate deployment sets.
- Writing to legacy collections that use a single unnamed vector, and adding new named vectors to an existing collection (`config.add_vector`). Both are reported as validation errors.
- Custom sparse embeddings such as SPLADE. Weaviate has no native sparse-vector field equivalent to Milvus's `SPARSE_FLOAT_VECTOR`, and docpipe's Milvus sparse mode does not store user-supplied sparse vectors either: it is BM25 computed by the server. Sparse mode on Weaviate is likewise BM25 over the content property.
- Embedded Weaviate. It is experimental, Linux/macOS only, and downloads a server binary at runtime, so it is unsuitable as a container-free test path the way Milvus Lite is.
- Changing OpenSearch or Milvus adapters, including Milvus's existing failed-item shape.
- Vault secret resolution (`vault://` URIs). The adapter uses `resolve_env_var()` for `$VAR`/`${VAR}` references, consistent with the OpenSearch and Milvus adapters. Upgrading all three adapters to `resolve_value()` (which handles both env vars and `vault://` URIs) is a separate cross-cutting change.

## Impact

- **Operators:** `vectordb` (`VectorDBOperator`) gains a provider. No new operator; `DOCPIPE_OPERATORS` is unchanged.
- **Storage adapters:** new `weaviate` outbound adapter package; `VectorStoreFactory` registration in `vectordb_operator.py`; `VectorDBMetadataFetcher` routing.
- **REST routes:** none added or changed. `GET /api/v1/operators` metadata now lists `weaviate` in `provider` valid values and `provider_config.providers`. `POST /api/v1/validation/enrich_flow_features` returns Weaviate metadata for `vectordb` nodes with `provider: "weaviate"`.
- **Dependencies:** `weaviate-client` (pinned) in `[project.dependencies]`; `uv.lock` regenerated. This may move `grpcio` to a version below 1.80 unless the upstream cap is lifted first.
- **Infrastructure and tests:** new `docker/docker-compose.weaviate.yml`; new `tests/unit/operators/vectordb/test_weaviate_*.py` and `tests/integration/weaviate/`.
- **Docs:** VectorDB operator README, `docs/reference/OPERATORS.md`, and a sample flow. `CHANGELOG.md` is not touched.
