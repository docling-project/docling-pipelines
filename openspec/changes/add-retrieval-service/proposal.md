# Proposal: Add Native Retrieval Service to Docling Pipelines

## Why

Docling Pipelines excels at document ingestion, extraction, chunking, embedding, and indexing into DuckDB (`DocumentSetOperator`) and vector databases (`VectorDBOperator`: Milvus, OpenSearch, Weaviate), while organizing outputs into `DocumentSet` and `DocumentLibrary` assets. However, it has no unified query or retrieval capability across those indexed assets — only a single-index OpenSearch lookup route (`/api/v1/documents/{document_id}`) in `src/docpipe/api/routes/documents.py`.

Teams using Docling Pipelines need an out-of-the-box retrieval service that exposes the **same REST API contract as `retrieval-v2`** (`query-api` v1 synchronous + v2 asynchronous submit/poll + health probes) while operating natively over Docling Pipelines' own stores:
- **Structured tables** in **DuckDB** (via Text-to-SQL with `sqlglot` validation, read-only enforcement, and self-correction),
- **Vector stores** in **Milvus**, **OpenSearch**, and **Weaviate** (dense + hybrid sparse/BM25 search with optional reranking),
- **Hybrid correlation & synthesis**, joining structured SQL results with unstructured vector chunks through the document id (the document set table's `id`, stored by the vector index as its mapped `document_id` column) and producing a grounded LLM answer, and
- **Multi-Document-Set planning** when a `DocumentLibrary` spans multiple heterogeneous `DocumentSet`s.

Retrieval does not record or re-derive provenance itself. PR #639 (`add-document-set-data-card`) makes `DocumentSet.data_card` the single system-maintained provenance record (`embeddings[]` with `provider`/`model_id`/`dimension_size`, `derivative_store: {name, path, add_sparse_vector, feature_mappings, table_prefix}`, three-state `propagate_source_acls`), and the `add-document-library-derivatives` change (PR #496) resolves that card at request time into a credential-free derivatives view behind a `DerivativeResolverPort`. This change consumes that port, so retrieval discovers vector derivatives without polluting user-owned `DocumentSet.metadata` or introducing any IBM UDP / Presto / CAMS dependencies.

**Layer:** `backend-only`. Adds a new DDD subsystem under `src/docpipe/core/retrieval/`, mounts `retrieval-v2`-compatible REST routes (`/v1/retrieval/*` and `/v2/retrieval/*`) on the FastAPI app, adds a `retrieval:` config section to `docling-pipelines-config.yaml`, and adds unit/API tests. No frontend UI, BFF proxy, or Redux slice changes are included in this change.

## Dependencies on Other Changes

This change is **not independently implementable**. It requires:

1. **`add-document-set-data-card`** (PR #639): the `DocumentSet.data_card` provenance record, including `derivative_store.feature_mappings`, `embeddings[].provider`, `add_sparse_vector`, entity store location, and the three-state `propagate_source_acls`.
2. **`add-document-library-derivatives`** (PR #496): resolves the card at request time. It provides `DerivativeResolverPort`, the `GET /api/v1/document-sets/{id}/derivatives` and `GET /api/v1/document-libraries/{library_id}/derivatives` routes, and the multi-flow merge rule. That change OWNS those routes and its `backend/derivatives-api` capability. This change does NOT add or modify any derivatives route, does NOT call them (it uses the port), and does NOT add `backend/document-libraries-api` requirements.

### Resolver contract consumed here

For each `DocumentSet`, `DerivativeResolverPort` returns the following (field names as defined by `backend/derivative-resolution`). Retrieval treats every `null` as "unknown" and applies the fallbacks listed:

| Field | Source | Fallback when unknown |
|---|---|---|
| `vector_stores[].provider`, `.path` (collection or index) | card `derivative_store.name` / `.path` | none (store is not routable) |
| `vector_stores[].embedding` | the paired card `embeddings[]` entry | `null` means the store is skipped (no embedding model to embed the query with) |
| `vector_stores[].embedding.provider` | card `embeddings[].provider` | `retrieval.embeddings.default_provider` |
| `vector_stores[].embedding.model_id`, `.dimension_size` | card `embeddings[]` | none (store is not routable) |
| `vector_stores[].add_sparse_vector` | card `derivative_store.add_sparse_vector` | live collection schema introspection, then `metadata["retrieval_derivatives"]` override |
| `vector_stores[].column_mapping` (`document_id`, `text`, `vector`, `sparse`, `allowed_users`, each nullable) | explicit `derivative_store.feature_mappings` items of the `vectordb` entry (`id`, `content`, the embedding feature, `sparse_embeddings`, `allowed_users`) | `vectordb` operator defaults (`document_id`, `text`, `vector_embeddings`, `sparse_embeddings`); `allowed_users` has NO default |
| `acl_state`, `acl_protected` | card `propagate_source_acls` (true: `protected`, false: `unprotected`, null: `unknown`) | the resolver is already fail-closed: `acl_protected` is true unless the card says false; security policy is never stored in user-owned `metadata` |
| `purpose`, `summary`, `language` (planner hints) | card descriptive fields | omitted |
| `conflicts` (kind and provider only) | resolver merge rule below | empty |
| `entity_tables` (backend, schema, prefix, `retrievable`) | card `entity_store` entries | not queried here (see Non-goals) |

The embedding `feature` recorded on the card is the **source table column** and MUST NOT be used as the index vector field. Index field names come only from `column_mapping`.

**Multi-flow merge rule (owned by the derivatives change, consumed here):** the resolver takes the latest run per flow in `data_card.flows[]`, unions their `vectordb` stores, and returns each `(provider, path)` once, the newest winning. If the same `(provider, path)` appears with a different embedding `model_id` or `dimension_size`, the most recent wins and a `conflicts` entry carrying only the kind and provider is returned.

**ACL consequence:** a document set without a recorded card run resolves to `acl_state` `unknown`, so retrieval treats it as ACL-protected and skips its DuckDB SQL and its Milvus and Weaviate targets. A curator opens or protects a set exclusively via `PATCH /api/v1/document-sets/{id}/data-card` (`propagate_source_acls`); user-owned `metadata` cannot set or override ACL protection.

## What Changes

### 1. Derivative Discovery (consuming `DerivativeResolverPort`)
- Implement `LocalRetrievalCatalogAdapter` as a **thin wrapper** over `DerivativeResolverPort`. It does not walk the `DataCard` itself. It only adds:
  - **Connection resolution**: host/port/credentials come from `retrieval.vector_stores.<provider>` in `docling-pipelines-config.yaml` (never from the card, per PR #639's no-host rule). This supports **one cluster per provider**; two stores of the same provider on different clusters are a documented limitation.
  - **SQL target**: a `SqlTableTarget` of `kind: document_set_table`, built from the `DocumentSet`'s existing DuckDB storage attachment (`database_path`, `table_name`), with optional `document_class_id` enrichment from `src/docpipe/core/document_classes/*.json`.
  - **User overrides**: `DocumentSet.metadata["retrieval_derivatives"]` (for example, when a `vectordb` sink ran on a sibling branch that the card does not list, or to set `document_class_id`, `sparse_field`, `column_mapping`) merges with and takes precedence over resolver output. ACL protection is NOT configurable here (it lives exclusively on `DataCard.propagate_source_acls` so a `PATCH /document-sets/{id}` metadata replacement can never erase security policy).
  - **Fallbacks** for `null` resolver fields as listed in the resolver contract.

### 2. Core Retrieval Subsystem (`src/docpipe/core/retrieval/`)
- **Domain (`domain/`)**: pure Python/Pydantic domain models (`QueryRequest`, `QueryResponse`, `ResultItem`, `ResultMetadata`, `AdditionalInfo`, `DerivativeDescriptor`, `VectorStoreTarget`, `SqlTableTarget`, `DocumentClassContext`) and port ABCs (`RetrievalCatalogPort`, `SQLEnginePort`, `VectorStoreQueryPort`, `RerankerPort`, `RetrievalCachePort`, `RetrievalACLPort`).
- **Application (`application/`)**:
  - `SearchOrchestrator`: cache lookup → catalog resolution → ACL check → derivative-driven concurrent dispatch (`SqlRetriever` + `VectorRetriever`) → hybrid correlation & LLM synthesis → cache write.
  - `MultiDocSetOrchestrator` + `OuterQueryPlanner` + `DAGExecutor`: fast-paths single-set libraries directly to `SearchOrchestrator`; for multi-set libraries, decomposes complex questions into a wave-parallel DAG of per-set sub-questions.
  - `SqlRetriever`: builds schema + `document_classes/` context → generates SQL via `LLMInferencePort` → validates and authorizes SQL via an allowlist-based `sqlglot` validator (`duckdb` dialect, single `SELECT`, plain allowlisted tables, no table-valued functions, fixed function allowlist) → executes the re-serialized SQL with deadline/cancellation, row cap, and memory limits → self-corrects up to `max_retries`.
  - `VectorRetriever`: concurrently searches all vector targets in a set → supports hybrid dense+sparse/BM25 with dense-only fallback → applies optional reranking over a configurable candidate pool (`max(limit, rerank_candidates)`).
  - `SearchJobQueue`: bounded in-process async submit/poll queue (max depth 100 → `503`, result TTL 900s, max 2,048 retained results).
- **Adapters (`adapters/`)**:
  - **Catalog**: `LocalRetrievalCatalogAdapter` (wraps `DerivativeResolverPort`; adds config merge, overrides, the document-set DuckDB table target, and document-class enrichment).
  - **SQL**: `DuckDBSqlEngine` (access through the existing `DuckDBConnectionManager` in `locked` (default) or opt-in table-scoped `snapshot` mode via `retrieval.sql.access_mode`, `SET enable_external_access = false` + `SET lock_configuration = true`, memory/thread/row limits, query timeout and `conn.interrupt()` cancellation).
  - **Vector**: `MilvusVectorQueryAdapter` (dense + BM25 hybrid with RRF, dense fallback), `OpenSearchVectorQueryAdapter` (k-NN + BM25 hybrid + `allowed_users` ACL filter), `WeaviateVectorQueryAdapter` (named-vector `near_vector` + BM25 `hybrid` using `weaviate-client` v4).
  - **LLM / Embeddings / Reranker**: thin async bridges over `docpipe`'s `LLMInferencePort` and `LLMEmbeddingPort` (Ollama, Watsonx, LiteLLM/OpenAI-compatible, HuggingFace) plus optional rerankers (`ollama`, `watsonx`, `cross_encoder`).
  - **Cache**: `MemoryRetrievalCache` (`cachetools.TTLCache`, default) and optional `RedisRetrievalCache`.
  - **ACL**: `DocpipeACLAdapter` integrating with `docpipe.api.auth.models.User` (enforces `allowed_users` on OpenSearch; for ACL-protected document sets fails closed by skipping DuckDB SQL, Milvus, Weaviate, and any OpenSearch store whose `allowed_users` index mapping is unknown, because those stores cannot enforce per-document ACLs). All search/poll routes require `get_current_user`; there is no per-library authorization.
- **Factories (`factories/`)**: `RetrievalServiceFactory` reading the `retrieval:` block from `docling-pipelines-config.yaml` via `DocpipeConfigLoader`.

### 3. `retrieval-v2`-Compatible REST API Surface (`src/docpipe/api/routes/retrieval.py`)
Mounted directly on the FastAPI app in `src/docpipe/api/main.py` to preserve exact `retrieval-v2` wire compatibility (`query-api/spec.md`):
- **v1 Synchronous**:
  - `POST /v1/retrieval/advanced/search`
  - `POST /v1/retrieval/search` (alias)
- **v2 Asynchronous (submit + poll)**:
  - `POST /v2/retrieval/advanced/search` → `202 Accepted` `{"query_id": "<uuid>", "status": "pending"}`
  - `POST /v2/retrieval/search` (alias)
  - `GET /v2/retrieval/advanced/search/result/{query_id}` → `202` pending / `200` `QueryResponse` / `404` unknown or expired / `500` failed
  - `GET /v2/retrieval/search/result/{query_id}` (alias)
  - `POST /v2/retrieval/search_data_assets` → `202 Accepted` `{"query_id": "<uuid>", "status": "pending"}`
- **Health (unauthenticated)**:
  - `GET /v2/retrieval/healthz` → `200 OK` `{"status": "ok"}`
  - `GET /v2/retrieval/readyz` → `200 OK` when wired / `503 Service Unavailable` otherwise
- **Routing note**: these paths are mounted on the root app (outside `/api/v1`) for wire compatibility. The BFF proxy forwards only `/api/*`, so `/v1/retrieval/*` and `/v2/retrieval/*` are NOT reachable through it; deployments MUST route them (ingress or reverse proxy) or use the API service directly. Authentication uses the existing `get_current_user` dependency, which a future authn/authz change is expected to replace with role-based access.
- Dedicated Pydantic DTOs in `src/docpipe/api/dto/retrieval_dto.py` matching `retrieval-v2`'s `QueryRequest` (including `searchConfig` alias, `container_id`/`container_type`, `document_library_id`, `document_set_id`, `asset_id`, `asset_type`, `search_inference_config`, `disable_cache`, `evaluate`) and `QueryResponse` (`request_id`, `generated_text`, `results`, `additional_info`, `status`, `execution_time`).

### 4. Configuration & Dependencies
- Add a `retrieval:` section to `docling-pipelines-config.yaml.example` (disabled by default via `retrieval.enabled: false` returning `503 retrieval_disabled`, with `retrieval.sql.*` controls (`enabled`, `access_mode`, `lock_timeout_seconds`, `max_rows`, `max_memory`, `threads`) and default provider connection blocks for `milvus`, `opensearch`, and `weaviate` so card `derivative_store` names resolve without storing credentials or hosts in the card).
- Add pinned `cachetools` to `[project.dependencies]` in `pyproject.toml`, and optional `retrieval-redis` extra (`redis`) under `[project.optional-dependencies]`. Regenerate `uv.lock`.

## Capabilities

### New Capabilities
- `backend/retrieval-api`: `retrieval-v2`-compatible HTTP contract for v1 synchronous search, v2 asynchronous submit/poll, direct asset search, liveness/readiness probes, queue/TTL bounds, and `QueryRequest`/`QueryResponse` DTOs.
- `backend/retrieval-engine`: Derivative-driven store routing backed by the card-derived `DerivativeResolverPort`, DuckDB Text-to-SQL with `sqlglot` validation/authorization and self-correction, concurrent vector retrieval across Milvus, OpenSearch, and Weaviate with optional reranking, hybrid SQL+vector correlation and LLM synthesis, multi-Document-Set DAG planning, and result caching.

### Modified Capabilities
- None. The derivatives endpoint belongs to `add-document-library-derivatives`.

## Non-goals

- **IBM UDP, Presto/Iceberg, and CAMS integration**: All UDP HTTP client code, Presto SQL engine, IBM IAM/Zen JWKS auth, IBM Secrets Manager TLS, and CAMS ACL checks from `retrieval-v2` are explicitly excluded. (`container_id` and `container_type` are accepted on the wire for client compatibility, not sent to any external catalog.)
- **Modifying PR #639 or PR #496 in this change**: The resolver contract above is provided by those changes, and this change adds no card field, resolver field, or derivatives route.
- **SQL over entity tables (`entity_store_operator`)**: `SqlTableTarget.kind` has two values, `document_set_table` (implemented here) and `entity_table` (declared, NOT implemented). The resolver reports entity tables by backend, schema, and table prefix only, and not their runtime table names, so querying them needs a follow-up change that enumerates the tables under the prefix and applies the SQL allowlist to them.
- **Multiple clusters per vector provider**: connection settings are per provider in config; the card records no hosts.
- **PostgreSQL / pgvector retrieval backends**: Out of scope for this change (DuckDB is the SQL target; Milvus, OpenSearch, and Weaviate are the vector targets). Port interfaces allow adding Postgres/pgvector in a follow-up.
- **Agentic retrieval (`/v2/retrieval/agent/search`), offline RAGAS evaluation (`/v2/retrieval/evaluate/offline`), and Prometheus `/v2/retrieval/metrics`**: Deferred to follow-up changes (`evaluate` is accepted on `QueryRequest` for wire compatibility and ignored when eval is not enabled).
- **Frontend UI / Query Playground**: No React components, Redux slices, or BFF proxy routes are added in this change.
- **Replacing `/api/v1/documents`**: The existing OpenSearch document lookup/search routes in `src/docpipe/api/routes/documents.py` remain untouched.

## Impact

- **REST routes**: Adds `src/docpipe/api/routes/retrieval.py` and mounts v1/v2 retrieval routers in `src/docpipe/api/main.py` (with lifespan wiring for orchestrator readiness and clean shutdown).
- **DTOs**: Adds `src/docpipe/api/dto/retrieval_dto.py`.
- **Core modules**: Adds `src/docpipe/core/retrieval/` (`domain/`, `application/`, `adapters/`, `factories/`).
- **Operators**: None modified. `DocumentSetOperator` already persists the DuckDB table and (via PR #639) populates `DocumentSet.data_card`.
- **Derivatives endpoint**: None added here; see `add-document-library-derivatives`.
- **Storage adapters**: Read-only DuckDB query adapter (`DuckDBSqlEngine`) + query adapters for Milvus, OpenSearch, and Weaviate (reusing installed `duckdb`, `pymilvus`, `opensearch-py`, `weaviate-client`).
- **Shared utilities**: `src/docpipe/utils/duckdb/connection_manager.py` gains an optional, backward-compatible `lock_timeout_seconds` keyword on `get_connection` (default `None` preserves current behavior).
- **Config & Dependencies**: Adds `retrieval:` block to `docling-pipelines-config.yaml.example`; adds pinned `cachetools` to `pyproject.toml` and regenerates `uv.lock`.
- **Tests**: Unit tests under `tests/unit/core/retrieval/` and `tests/unit/api/routes/test_retrieval.py`.
