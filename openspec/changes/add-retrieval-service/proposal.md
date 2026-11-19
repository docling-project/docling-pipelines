# Proposal: Add Native Retrieval Service to Docling Pipelines

## Why

Docling Pipelines excels at document ingestion, extraction, chunking, embedding, and indexing into DuckDB (`DocumentSetOperator`) and vector databases (`VectorDBOperator`: Milvus, OpenSearch, Weaviate), while organizing outputs into `DocumentSet` and `DocumentLibrary` assets. However, it has no unified query or retrieval capability across those indexed assets — only a single-index OpenSearch lookup route (`/api/v1/documents/{document_id}`) in `src/docpipe/api/routes/documents.py`.

Teams using Docling Pipelines need an out-of-the-box retrieval service that exposes the **same REST API contract as `retrieval-v2`** (`query-api` v1 synchronous + v2 asynchronous submit/poll + health probes) while operating natively over Docling Pipelines' own stores:
- **Structured tables** in **DuckDB** (via Text-to-SQL with `sqlglot` validation, read-only enforcement, and self-correction),
- **Vector stores** in **Milvus**, **OpenSearch**, and **Weaviate** (dense + hybrid sparse/BM25 search with optional reranking),
- **Hybrid correlation & synthesis**, joining structured SQL results with unstructured vector chunks via `document_id` and producing a grounded LLM answer, and
- **Multi-Document-Set planning** when a `DocumentLibrary` spans multiple heterogeneous `DocumentSet`s.

In addition, PR #639 (`add-document-set-data-card`) introduces a structured `DataCard` on `DocumentSet` that records upstream `embeddings` (`model_id`, `feature`, `dimension_size`), `vectordb` (`derivative_store: {name, path}`), and `propagate_source_acls`, explicitly deferring derivative consumption to a later change. This proposal builds directly on that `DataCard` provenance model so retrieval discovers vector derivatives automatically without polluting user-owned `DocumentSet.metadata` or introducing any IBM UDP / Presto / CAMS dependencies.

**Layer:** `backend-only`. Adds a new DDD subsystem under `src/docpipe/core/retrieval/`, mounts `retrieval-v2`-compatible REST routes (`/v1/retrieval/*` and `/v2/retrieval/*`) on the FastAPI app, adds a `retrieval:` config section to `docling-pipelines-config.yaml`, and adds unit/API tests. No frontend UI, BFF proxy, or Redux slice changes are included in this change.

## What Changes

### 1. Native Derivative Discovery (Building on PR #639 `DataCard`)
- Implement `LocalDocumentLibraryCatalogAdapter` resolving a `DocumentLibrary` or `DocumentSet` directly from `DocumentLibraryService`, `DocumentSetService`, `DataCardService` (PR #639), and `src/docpipe/core/document_classes/*.json`:
  - **SQL derivative**: inferred directly from `DocumentSet`'s existing DuckDB storage attachment (`database_path`, `table_name`), with optional `document_class_id` enrichment. No write to `DocumentSet.metadata` is required.
  - **Vector derivatives**: auto-discovered from the latest run in `DocumentSet.data_card` (`DataCardOperator.derivative_store` → `{name: provider, path: collection_name/index_name}` + `DataCardOperator.embeddings` → `{model_id, feature, dimension_size}`) merged with provider connection defaults in `docling-pipelines-config.yaml`.
  - **Optional user overrides**: if `DocumentSet.metadata["retrieval_derivatives"]` is explicitly provided by a user (for example, when a `vectordb` sink ran on a sibling branch not walked by `DataCardRunBuilder`, or to specify `document_class_id` / `sparse_field` / custom connection overrides), those entries merge with or override auto-discovered derivatives.

### 2. Core Retrieval Subsystem (`src/docpipe/core/retrieval/`)
- **Domain (`domain/`)**: pure Python/Pydantic domain models (`QueryRequest`, `QueryResponse`, `ResultItem`, `ResultMetadata`, `AdditionalInfo`, `DerivativeDescriptor`, `VectorStoreTarget`, `SqlTableTarget`, `DocumentClassContext`) and port ABCs (`DocumentLibraryCatalogPort`, `SQLEnginePort`, `VectorStoreQueryPort`, `RerankerPort`, `RetrievalCachePort`, `RetrievalACLPort`).
- **Application (`application/`)**:
  - `SearchOrchestrator`: cache lookup → catalog resolution → ACL check → derivative-driven concurrent dispatch (`SqlRetriever` + `VectorRetriever`) → hybrid correlation & LLM synthesis → cache write.
  - `MultiDocSetOrchestrator` + `OuterQueryPlanner` + `DAGExecutor`: fast-paths single-set libraries directly to `SearchOrchestrator`; for multi-set libraries, decomposes complex questions into a wave-parallel DAG of per-set sub-questions.
  - `SqlRetriever`: builds schema + `document_classes/` context → generates SQL via `LLMInferencePort` → validates and authorizes SQL via `sqlglot` (`duckdb` dialect, read-only SELECT-only, table allowlist) → executes with deadline/cancellation → self-corrects up to `max_retries`.
  - `VectorRetriever`: concurrently searches all vector targets in a set → supports hybrid dense+sparse/BM25 with dense-only fallback → applies optional reranking over a configurable candidate pool (`max(limit, rerank_candidates)`).
  - `SearchJobQueue`: bounded in-process async submit/poll queue (max depth 100 → `503`, result TTL 900s, max 2,048 retained results).
- **Adapters (`adapters/`)**:
  - **Catalog**: `LocalDocumentLibraryCatalogAdapter` (reads `DocumentLibraryService`, `DocumentSetService`, `DataCardService`, and `src/docpipe/core/document_classes/`).
  - **SQL**: `DuckDBSqlEngine` (read-only connection, `SET enable_external_access = false`, `sqlglot` DuckDB dialect, query timeout and `conn.interrupt()` cancellation).
  - **Vector**: `MilvusVectorQueryAdapter` (dense + BM25 hybrid with RRF, dense fallback), `OpenSearchVectorQueryAdapter` (k-NN + BM25 hybrid + `allowed_users` ACL filter), `WeaviateVectorQueryAdapter` (named-vector `near_vector` + BM25 `hybrid` using `weaviate-client` v4).
  - **LLM / Embeddings / Reranker**: thin async bridges over `docpipe`'s `LLMInferencePort` and `LLMEmbeddingPort` (Ollama, Watsonx, LiteLLM/OpenAI-compatible, HuggingFace) plus optional rerankers (`ollama`, `watsonx`, `cross_encoder`).
  - **Cache**: `MemoryRetrievalCache` (`cachetools.TTLCache`, default) and optional `RedisRetrievalCache`.
  - **ACL**: `DocpipeACLAdapter` integrating with `docpipe.api.auth.models.User` (enforces `allowed_users` filter on OpenSearch when `propagate_source_acls` or auth is active).
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
- Dedicated Pydantic DTOs in `src/docpipe/api/dto/retrieval_dto.py` matching `retrieval-v2`'s `QueryRequest` (including `searchConfig` alias, `container_id`/`container_type`, `document_library_id`, `document_set_id`, `asset_id`, `asset_type`, `search_inference_config`, `disable_cache`, `evaluate`) and `QueryResponse` (`request_id`, `generated_text`, `results`, `additional_info`, `status`, `execution_time`).

### 4. Configuration & Dependencies
- Add a `retrieval:` section to `docling-pipelines-config.yaml.example` (disabled by default via `retrieval.enabled: false` returning `503 retrieval_disabled`, with a `retrieval.sql.enabled` toggle for ACL-restricted libraries and default provider connection blocks for `milvus`, `opensearch`, and `weaviate` so `DataCard.derivative_store` names resolve without storing credentials in `DataCard`).
- Add pinned `cachetools` to `[project.dependencies]` in `pyproject.toml`, and optional `retrieval-redis` extra (`redis`) under `[project.optional-dependencies]`. Regenerate `uv.lock`.

## Capabilities

### New Capabilities
- `backend/retrieval-api`: `retrieval-v2`-compatible HTTP contract for v1 synchronous search, v2 asynchronous submit/poll, direct asset search, liveness/readiness probes, queue/TTL bounds, and `QueryRequest`/`QueryResponse` DTOs.
- `backend/retrieval-engine`: Derivative-driven store routing backed by local `DocumentLibrary`/`DocumentSet`/`DataCard`, DuckDB Text-to-SQL with `sqlglot` validation/authorization and self-correction, concurrent vector retrieval across Milvus, OpenSearch, and Weaviate with optional reranking, hybrid SQL+vector correlation and LLM synthesis, multi-Document-Set DAG planning, and result caching.

### Modified Capabilities
- None. Existing `document-sets-api`, `document-libraries-api`, `document-set-data-card` (PR #639), and `documents-api` contracts remain unchanged.

## Non-goals

- **IBM UDP, Presto/Iceberg, and CAMS integration**: All UDP HTTP client code, Presto SQL engine, IBM IAM/Zen JWKS auth, IBM Secrets Manager TLS, and CAMS ACL checks from `retrieval-v2` are explicitly excluded. (`container_id` and `container_type` are accepted on the wire for client compatibility, not sent to any external catalog.)
- **Modifying PR #639 (`add-document-set-data-card`)**: This change consumes `DataCard` as proposed in PR #639 without changing its schema or allowlist rules.
- **PostgreSQL / pgvector retrieval backends**: Out of scope for this change (DuckDB is the SQL target; Milvus, OpenSearch, and Weaviate are the vector targets). Port interfaces allow adding Postgres/pgvector in a follow-up.
- **Agentic retrieval (`/v2/retrieval/agent/search`), offline RAGAS evaluation (`/v2/retrieval/evaluate/offline`), and Prometheus `/v2/retrieval/metrics`**: Deferred to follow-up changes (`evaluate` is accepted on `QueryRequest` for wire compatibility and ignored when eval is not enabled).
- **Frontend UI / Query Playground**: No React components, Redux slices, or BFF proxy routes are added in this change.
- **Replacing `/api/v1/documents`**: The existing OpenSearch document lookup/search routes in `src/docpipe/api/routes/documents.py` remain untouched.

## Impact

- **REST routes**: Adds `src/docpipe/api/routes/retrieval.py` and mounts v1/v2 retrieval routers in `src/docpipe/api/main.py` (with lifespan wiring for orchestrator readiness and clean shutdown).
- **DTOs**: Adds `src/docpipe/api/dto/retrieval_dto.py`.
- **Core modules**: Adds `src/docpipe/core/retrieval/` (`domain/`, `application/`, `adapters/`, `factories/`).
- **Operators**: None modified. `DocumentSetOperator` already persists the DuckDB table and (via PR #639) populates `DocumentSet.data_card`.
- **Storage adapters**: Read-only DuckDB query adapter (`DuckDBSqlEngine`) + query adapters for Milvus, OpenSearch, and Weaviate (reusing installed `duckdb`, `pymilvus`, `opensearch-py`, `weaviate-client`).
- **Config & Dependencies**: Adds `retrieval:` block to `docling-pipelines-config.yaml.example`; adds pinned `cachetools` to `pyproject.toml` and regenerates `uv.lock`.
- **Tests**: Unit tests under `tests/unit/core/retrieval/` and `tests/unit/api/routes/test_retrieval.py`.
