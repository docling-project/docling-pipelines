# Design: Native Retrieval Service in Docling Pipelines

## 1. Architecture Overview & DDD Layer Boundaries

The retrieval subsystem is implemented as a self-contained DDD module under `src/docpipe/core/retrieval/` with strict inward dependencies (`adapters` → `application` → `domain`; `domain` has zero framework or driver imports):

```text
src/docpipe/
├── api/
│   ├── dto/retrieval_dto.py                  # retrieval-v2-compatible Pydantic DTOs + mappers
│   └── routes/retrieval.py                   # Thin FastAPI routes (/v1/retrieval/*, /v2/retrieval/*)
└── core/retrieval/
    ├── domain/
    │   ├── models/
    │   │   ├── query.py                      # QueryRequest, QueryResponse, ResultItem, ResultMetadata, AdditionalInfo
    │   │   ├── derivatives.py                # LibraryDescriptor, DocumentSetDescriptor, SqlTableTarget,
    │   │   │                                 # VectorStoreTarget, DocumentClassContext
    │   │   └── plan.py                       # SubQuestion, QueryPlan, ExecutionWave
    │   ├── ports/
    │   │   ├── catalog_port.py               # DocumentLibraryCatalogPort ABC
    │   │   ├── sql_engine_port.py            # SQLEnginePort ABC, CancelHandle, EngineCapabilities
    │   │   ├── vector_store_port.py          # VectorStoreQueryPort ABC
    │   │   ├── reranker_port.py              # RerankerPort ABC
    │   │   ├── cache_port.py                 # RetrievalCachePort ABC
    │   │   └── acl_port.py                   # RetrievalACLPort ABC
    │   └── exceptions.py                     # RetrievalException subclasses (extend DocpipeException)
    ├── application/
    │   ├── search_orchestrator.py            # Single-set orchestration (cache -> catalog -> ACL -> route -> synth)
    │   ├── multi_docset_orchestrator.py      # Top-level entry: single-set fast-path vs multi-set DAG
    │   ├── outer_planner.py                  # LLM DAG decomposition for multi-DocumentSet libraries
    │   ├── dag_executor.py                   # Wave-parallel DAG step execution
    │   ├── sql_retriever.py                  # Schema synthesis -> Text-to-SQL -> sqlglot validate -> retry
    │   ├── sql_validator.py                  # sqlglot AST read-only & table-allowlist authorization
    │   ├── vector_retriever.py               # Concurrent per-collection vector search + optional rerank
    │   ├── synthesizer.py                    # Unified context builder (SQL Markdown + deduplicated vector chunks)
    │   └── job_queue.py                      # Bounded async submit/poll queue (TTL 900s, max 2048, depth 100)
    ├── adapters/
    │   ├── catalog/
    │   │   └── local_catalog_adapter.py      # Reads DocumentLibraryService, DocumentSetService, DataCard, document_classes/
    │   ├── sql/
    │   │   └── duckdb_sql_engine.py          # Read-only DuckDB execution, timeout, interrupt() cancellation
    │   ├── vector/
    │   │   ├── milvus_query_adapter.py       # pymilvus hybrid (dense + BM25 RRF) & dense fallback
    │   │   ├── opensearch_query_adapter.py   # opensearch-py k-NN / hybrid + allowed_users ACL filter
    │   │   └── weaviate_query_adapter.py     # weaviate-client v4 named-vector near_vector / BM25 hybrid
    │   ├── llm/
    │   │   ├── inference_bridge.py           # Async wrapper over docpipe LLMInferencePort
    │   │   ├── embedding_bridge.py           # Async wrapper over docpipe LLMEmbeddingPort
    │   │   └── rerankers.py                  # Ollama, Watsonx, CrossEncoder HTTP reranker adapters
    │   ├── cache/
    │   │   ├── memory_cache.py               # cachetools.TTLCache
    │   │   └── redis_cache.py                # Optional Redis cache (lazy import)
    │   └── acl/
    │       └── docpipe_acl_adapter.py        # Bridges docpipe User / allowed_users
    └── factories/
        └── retrieval_factory.py              # Wires adapters from DocpipeConfigLoader ("retrieval" section)
```

All code adheres to `docling-pipelines` architectural rules:
- `get_logger()` from `docpipe.utils.infrastructure.logging` with `%s`-style formatting (no f-strings, no emoji).
- Keyword-only `*` separator for all functions/methods with 2+ parameters (excluding `self`/`cls`).
- `@staticmethod` / `@classmethod` for pure helpers that do not read `self`.
- Routes accept and return Pydantic DTOs only (`retrieval_dto.py`), never domain objects.

---

## 2. Key Design Decisions & Trade-offs

### D1. Derivative Discovery via PR #639 `DataCard` + Local Storage Attachments
PR #639 (`add-document-set-data-card`) establishes `DocumentSet.data_card` as the system-maintained provenance record while keeping `DocumentSet.metadata` strictly user-owned. `LocalDocumentLibraryCatalogAdapter` therefore discovers derivatives in three layers without ever mutating `DocumentSet.metadata`:

1. **SQL tables (automatic)**: Resolved from `DocumentSet`'s existing DuckDB storage attachment (`database_path` and `table_name`). No extra operator write is needed.
2. **Vector stores & embeddings (automatic from `DataCard`)**: Walks the most recent recorded run(s) in `DocumentSet.data_card.flows[].details.jobs[].runs[].operators[]`:
   - `vectordb` operator entry → `derivative_store.name` (`milvus` | `opensearch` | `weaviate`) and `derivative_store.path` (`collection_name` or `index_name`).
   - `embeddings` operator entry → `embeddings[0].model_id`, `feature` (`vector_field`, default `embeddings`), and `dimension_size`.
   - `DataCard.propagate_source_acls` → hints whether ACL filtering is expected on OpenSearch.
   - `DataCard.purpose`, `DataCard.summary`, and `DataCard.language` → passed to `OuterQueryPlanner` / `SchemaFormatter` to improve multi-Document-Set query routing.
   - Because `DataCard` intentionally excludes hosts, credentials, embedding provider names, and sparse/BM25 flags (PR #639 D5), connection parameters are resolved from `retrieval.vector_stores.<provider>` in `docling-pipelines-config.yaml` (with `$VAR`/`${VAR}` expansion), embedding provider falls back to `retrieval.embeddings.default_provider`, and sparse/BM25 fields are detected via live collection schema introspection or metadata override.
3. **Optional user overrides (`DocumentSet.metadata["retrieval_derivatives"]`)**: Because PR #639's `DataCardRunBuilder` only walks *ancestors* (`input_edges`) of `document_set` (excluding downstream `document_set -> vectordb` nodes and sibling branches where `vectordb` ran in parallel), users may optionally declare extra vector targets, `sparse_field`, `embedding_provider`, or `document_class_id` in `DocumentSet.metadata["retrieval_derivatives"]`. Explicit entries merge with and take precedence over `DataCard`-derived entries.

### D2. Exact `retrieval-v2` Wire Compatibility (`query-api/spec.md`)
To allow existing `retrieval-v2` clients and SDKs to talk directly to `docling-pipelines` without URL or payload rewrites:
- **Route paths**: Mounted directly on the root FastAPI `app` (outside `/api/v1`) at:
  - `POST /v1/retrieval/advanced/search` and `POST /v1/retrieval/search`
  - `POST /v2/retrieval/advanced/search` and `POST /v2/retrieval/search`
  - `GET /v2/retrieval/advanced/search/result/{query_id}` and `GET /v2/retrieval/search/result/{query_id}`
  - `POST /v2/retrieval/search_data_assets`
  - `GET /v2/retrieval/healthz` and `GET /v2/retrieval/readyz` (unauthenticated)
- **Request resolution**: Accepts `QueryRequest` verbatim:
  - `document_library_id` or (`asset_type == "document_library"` and `asset_id`) → targets a `DocumentLibrary`.
  - `document_set_id` or (`asset_type == "document_set"` and `asset_id`) → targets a single `DocumentSet`.
  - `container_id` and `container_type` are accepted (defaulting to `""` and `"project"` when omitted by native `docling-pipelines` callers, and accepted without error when supplied by `retrieval-v2` callers).
  - `search_config` accepts both `search_config` and alias `searchConfig` (`populate_by_name=True`).
  - `search_inference_config` (`model_id`, `deployment_id`), `disable_cache`, and `evaluate` are accepted verbatim (`evaluate` is a no-op until offline RAGAS evaluation is added).
- **Response schema**: Returns `QueryResponse` verbatim (`request_id`, `generated_text`, `results`, `additional_info`, `status`, `execution_time` in integer milliseconds) and `ResultItem` / `ResultMetadata`.

### D3. DuckDB Read-Only SQL Engine with AST Authorization & Cancellation
Unlike Presto, DuckDB runs in-process on a local file (`database_path`). Opening it safely for LLM-generated SQL requires three layers of defense:
1. **AST Authorization (`sql_validator.py`)**: Parse with `sqlglot.parse(sql, read="duckdb")`. Reject multi-statement queries, non-`SELECT` statements (DDL/DML/PRAGMA/COPY/ATTACH/INSTALL/LOAD), and any table reference not in the allowlist of tables belonging to the target `DocumentSet`(s).
2. **Read-Only Connection**: Open DuckDB with `duckdb.connect(database=db_path, read_only=True)` in a worker thread (`asyncio.to_thread`), executing `SET enable_external_access = false;` so SQL cannot read local files (`read_csv`, `read_parquet`, `httpfs`).
3. **Deadline & Cancellation**: Enforce a per-query deadline (`sql.timeout_seconds`, default 30s). On timeout or caller cancellation, invoke `conn.interrupt()` via `CancelHandle` from the coordinator thread to abort long-running scans cleanly.
4. **Schema & Document Class Enrichment**: Introspect column names/types via `DESCRIBE <table>` and enrich them with descriptions/examples/extraction instructions from `src/docpipe/core/document_classes/<document_class_id>.json` when `document_class_id` is set.

### D4. Vector Query Adapters (Milvus, OpenSearch, Weaviate)
All three vector backends implement `VectorStoreQueryPort.search(...)` and offload blocking SDK calls via `asyncio.to_thread`:
- **Milvus (`milvus_query_adapter.py`)**: Uses `pymilvus.MilvusClient`. When `sparse_field` is present on the target, issues a hybrid search (dense ANN + sparse BM25 with `RRFRanker`), falling back to dense-only ANN on hybrid failure.
- **OpenSearch (`opensearch_query_adapter.py`)**: Uses `opensearchpy.OpenSearch`. Supports k-NN dense search and hybrid k-NN + BM25 queries, and injects `ACLQueryBuilder`-compatible `allowed_users` term filters when `RetrievalACLPort` supplies a user identity.
- **Weaviate (`weaviate_query_adapter.py`)**: Uses `weaviate-client` v4 (`weaviate.connect_to_custom` / `connect_to_weaviate_cloud`). Aligns with `docling-pipelines`'s Weaviate ingestion conventions (named self-provided vectors, `pk` primary key, server-side BM25 on the content property):
  - When `sparse_field` / BM25 mode is enabled, executes `collection.query.hybrid(query=user_query, vector=query_vector, target_vector=vector_field, limit=fetch_limit)`.
  - Otherwise executes `collection.query.near_vector(near_vector=query_vector, target_vector=vector_field, limit=fetch_limit)`.
  - Always closes the client in `finally`.

### D5. Bridging `LLMInferencePort` and `LLMEmbeddingPort`
- `InferenceBridge` and `EmbeddingBridge` wrap `docpipe`'s synchronous `LLMInferencePort` and `LLMEmbeddingPort` with `asyncio.to_thread`, reusing `LLMAdapterFactory` (Ollama, Watsonx, LiteLLM/OpenAI-compatible, HuggingFace).
- Embedding adapters are cached by `(provider, model_id)` so repeated queries avoid re-initializing local/remote clients.

### D6. Configuration Schema (`docling-pipelines-config.yaml`)
```yaml
retrieval:
  enabled: true
  default_limit: 10
  sql:
    timeout_seconds: 30
    max_retries: 2
  vector:
    reranker: none            # none | ollama | watsonx | cross_encoder
    rerank_candidates: 30
  vector_stores:              # Default connection settings used to resolve DataCard derivative_store entries
    milvus:
      uri: http://localhost:19530
      db_name: default
    opensearch:
      host: localhost
      port: 9200
      use_ssl: false
    weaviate:
      connection_type: on-prem
      http_host: localhost
      http_port: 8080
      grpc_port: 50051
  llm:
    provider: ollama          # ollama | watsonx | litellm
    model_id: llama3.1:8b
  embeddings:
    default_provider: ollama  # Fallback provider when DataCard only records model_id
  cache:
    enabled: true
    backend: memory           # memory | redis
    ttl_seconds: 300
    max_size: 512
  async_queue:
    max_depth: 100
    result_ttl_seconds: 900
    max_results: 2048
```

## 3. Risk Mitigations

| Risk | Mitigation |
|---|---|
| **PR #639 merge ordering** (`DataCard` nested model not yet merged on `main`) | `LocalDocumentLibraryCatalogAdapter` inspects `document_set.data_card` defensively (tolerant of `None` or pre-PR-#639 flat `DataCard`), falling back to storage attachments and optional `metadata["retrieval_derivatives"]`. |
| **Sibling-branch `vectordb` sinks** not captured in `DataCard` | Support optional `DocumentSet.metadata["retrieval_derivatives"]["vector_stores"]` overrides that merge with `DataCard`-discovered stores. |
| **DuckDB file lock contention** between ingestion writes and retrieval reads | Open retrieval connections strictly `read_only=True` per query and close in `finally`. |
| **LLM-generated SQL injection or local file exfiltration** | Enforce both `sqlglot` AST allowlist (single `SELECT`, allowed tables only) AND `SET enable_external_access = false` on a `read_only=True` connection. |
| **Credential leakage** in config, metadata, or error logs | Keep credentials out of `DataCard`; expand `$VAR`/`${VAR}` at runtime; never log connection dicts or raw driver messages. |
| **Event-loop starvation** from sync SDKs | Offload all blocking SDK calls via `asyncio.to_thread` and cap async concurrency/queue depth (100 pending). |
