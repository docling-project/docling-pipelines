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
   - `DataCard.propagate_source_acls` → marks the set as ACL-protected, which triggers the fail-closed behavior in D7 (not merely a hint).
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
- **Read-only Derivatives View**: Mounted on `document_libraries_router` at `GET /api/v1/document-libraries/{library_id}/derivatives` (with `limit`, opaque `bookmark`, and tolerated `container_id`/`container_type` query params). Reuses `DocumentLibraryCatalogPort` directly and maps to credential-free DTOs (`DocumentLibraryDerivativesResponse`), redacting all secrets, `${VAR}`/`vault://` references, connection strings, and DuckDB `database_path` values.
- **Request resolution**: Accepts `QueryRequest` verbatim:
  - `document_library_id` or (`asset_type == "document_library"` and `asset_id`) → targets a `DocumentLibrary`.
  - `document_set_id` or (`asset_type == "document_set"` and `asset_id`) → targets a single `DocumentSet`.
  - `container_id` and `container_type` are accepted (defaulting to `""` and `"project"` when omitted by native `docling-pipelines` callers, and accepted without error when supplied by `retrieval-v2` callers).
  - `search_config` accepts both `search_config` and alias `searchConfig` (`populate_by_name=True`).
  - `search_inference_config` (`model_id`, `deployment_id`), `disable_cache`, and `evaluate` are accepted verbatim (`evaluate` is a no-op until offline RAGAS evaluation is added).
- **Response schema**: Returns `QueryResponse` verbatim (`request_id`, `generated_text`, `results`, `additional_info`, `status`, `execution_time` in integer milliseconds) and `ResultItem` / `ResultMetadata`.

### D3. DuckDB Read-Only SQL Engine with AST Authorization, Resource Limits & Cancellation
Unlike Presto, DuckDB runs in-process on a local file (`database_path`). `DuckDBDocumentSetStorage` writes every document set into one shared DuckDB file, so the file also contains tables of unrelated document sets. Opening it safely for LLM-generated SQL requires the following layers of defense:
1. **Allowlist-based AST Authorization (`sql_validator.py`)**: Parse with `sqlglot.parse(sql, read="duckdb")` and enforce an *allowlist*, not a denylist of known-bad functions:
   - Exactly one statement, and it MUST be a `SELECT` (optionally with CTEs / set operations). Everything else (DDL/DML/`PRAGMA`/`COPY`/`ATTACH`/`INSTALL`/`LOAD`/`SET`/`CALL`/`EXPORT`) is rejected.
   - Every relation in `FROM`/`JOIN` MUST be a plain table reference whose *unqualified* name is in the allowlist of tables of the target `DocumentSet`(s) or a CTE defined in the same statement. Catalog- or schema-qualified names (for example `other_db.main.t`, `information_schema.*`, `main.t`) are rejected.
   - **All table-valued functions are rejected** (not only `read_csv`, `read_parquet`, `read_text`, `glob`, but also `query`, `query_table`, `duckdb_*()`, `pragma_*()`, `sniff_csv`, `parquet_*()`, `range`/`generate_series`, etc.).
   - Scalar/aggregate/window functions MUST appear in a fixed in-code allowlist (aggregates, string, numeric, date/time, `CAST`/`TRY_CAST`, `COALESCE`/`NULLIF`, `LOWER`/`UPPER`, etc.); any function not in the allowlist, and any unknown AST node type, is rejected (fail closed). The allowlist is a module constant and is NOT configurable at runtime.
   - CTE names that shadow allowlisted tables are rejected.
   - The executed SQL text is the validator's re-serialization of the parsed AST (`expression.sql(dialect="duckdb")`), never the raw model output, which removes sqlglot-vs-DuckDB parser differentials from the trust boundary.
2. **Connection Access Mode (`retrieval.sql.access_mode`)**: DuckDB does not allow concurrent connections to the same file with different configurations, and [`DuckDBConnectionManager`](../../../src/docpipe/utils/duckdb/connection_manager.py) already serializes all access per path with a lock. Retrieval MUST go through that manager (never a bare `duckdb.connect`) in one of two modes:
   - **`locked` (default)**: Acquire the per-path lock via `DuckDBConnectionManager.get_connection(database_path=..., read_only=True)` inside `asyncio.to_thread`, bounded by `retrieval.sql.lock_timeout_seconds` (default 5s). The manager gains an optional, backward-compatible `lock_timeout_seconds` parameter (default `None` = current blocking behavior) that raises a dedicated timeout error. The lock is held for the lifetime of the query, so retrieval and ingestion writes to the *same file* are serialized and retrieval on one file runs one query at a time. If the lock is not acquired in time, or a writer in another process holds the file and DuckDB raises an `IOException`, the SQL store is marked `unavailable` (no self-correction LLM call) and the response is `"partial"`. This mode is supported for a single API process; document it in the deployment guide.
   - **`snapshot` (opt-in for busy deployments)**: Query a read-only snapshot copy of the document-set DuckDB file stored under `retrieval.sql.snapshot_dir` (never exposed in responses or logs). A snapshot is produced while holding the source file's manager lock (checkpoint, then consistent copy), refreshed single-flight when older than `retrieval.sql.snapshot_ttl_seconds` (default 60), and opened `read_only=True` WITHOUT taking the source lock. If a refresh cannot acquire the source lock within `lock_timeout_seconds`, the previous snapshot is served and `additional_info` notes that the data may be stale; if no snapshot exists yet the store is marked `unavailable`. Results may lag ingestion by up to the TTL.
3. **Connection Hardening & Resource Limits**: On every retrieval connection, after trusted schema introspection and before executing model-generated SQL, run `SET enable_external_access = false`, `SET lock_configuration = true` (so SQL cannot undo the setting), `SET max_memory = '<retrieval.sql.max_memory>'` (default `512MB`) and `SET threads = <retrieval.sql.threads>` (default `2`). The result is fetched with a hard row cap (`retrieval.sql.max_rows`, default `1000`); rows beyond the cap are dropped, a truncation note is recorded in `additional_info`, and `status` becomes `"partial"`.
4. **Deadline, Cancellation & Fail-Fast Retries**: Enforce a per-query deadline (`sql.timeout_seconds`, default 30s). On timeout or caller cancellation, invoke `conn.interrupt()` via `CancelHandle` from the coordinator thread to abort long-running scans cleanly and release the file lock. Non-repairable errors (authorization refusal, timeout, cancellation, lock-acquire timeout, connection failure) fail fast without invoking the self-correction LLM.
5. **Schema & Document Class Enrichment**: Introspect column names/types via `DESCRIBE <table>` (trusted internal path, executed before the hardening step) and enrich them with descriptions/examples/extraction instructions from `src/docpipe/core/document_classes/<document_class_id>.json` when `document_class_id` is set.
6. **SQL Kill-Switch (`retrieval.sql.enabled`)**: Operators can set `retrieval.sql.enabled: false` to disable SQL retrieval globally; SQL routing is skipped cleanly with a note in `additional_info`. For ACL-protected document sets the SQL path is disabled automatically regardless of this flag (see D7).

### D7. Authorization Model & Fail-Closed ACL Handling
The retrieval service MUST NOT imply a stronger access-control model than the platform provides. Current platform facts: `DocumentLibrary` only carries an informational `created_by` and the existing `/api/v1/document-libraries` routes do not call `get_current_user`; per-row ACLs exist only as the OpenSearch `allowed_users` field populated when `DataCard.propagate_source_acls` is set; DuckDB tables, Milvus collections, and Weaviate collections carry no ACL enforcement.

1. **Authentication**: All v1/v2 search and result-polling routes depend on `get_current_user` (HTTP bearer JWT). Unauthenticated callers get `401`. Only `/v2/retrieval/healthz` and `/v2/retrieval/readyz` are unauthenticated.
2. **Library/set level**: There is no per-library or per-document-set ownership model. Any authenticated user may query any `DocumentLibrary`/`DocumentSet` for which retrieval is enabled. `RetrievalACLPort` therefore exposes only the caller identity and the per-document ACL hints below; library-level authorization is explicitly out of scope and MUST be documented as such in `docs/guides/RETRIEVAL_SERVICE_GUIDE.md`. Per-user ownership applies to async job results only (`query_id`).
3. **ACL-protected document set**: A `DocumentSet` is *ACL-protected* when `DataCard.propagate_source_acls` is true or `DocumentSet.metadata["retrieval_derivatives"]["acl_protected"]` is true. For an ACL-protected set the engine fails closed:
   - **SQL (DuckDB) retrieval is skipped**, and every DuckDB-backed helper (`column_values`, `find_documents`, literal-spelling probes, agent `query_table`/`list_documents`/`read_document`) is unavailable for it, because DuckDB tables cannot enforce per-row ACLs. `retrieval.sql.enabled` does not need to be changed by the operator.
   - **OpenSearch** targets are queried with the mandatory `allowed_users` filter for the authenticated user.
   - **Milvus and Weaviate** targets are skipped, because the adapters cannot enforce `allowed_users`. (Adding filtering support is a follow-up and lifts the skip for that provider.)
   - Each skip is recorded in `additional_info` as a generic note (`acl_protected_store_skipped`) without store names or paths, and `status` is `"partial"`.
4. **Cache and event isolation**: The cache key already includes caller identity; request event timelines and metrics-by-request are owner-scoped (see Phase 3).

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
  enabled: false              # Disabled by default; routes return 503 retrieval_disabled until enabled
  default_limit: 10
  sql:
    enabled: true             # Set false to disable SQL retrieval globally (ACL-protected sets are skipped automatically)
    access_mode: locked       # locked (default; DuckDBConnectionManager lock) | snapshot (read-only copy, may be stale)
    lock_timeout_seconds: 5   # Max wait for the per-file DuckDB lock (locked) or for a snapshot refresh (snapshot)
    snapshot_dir: data/duckdb/retrieval_snapshots   # snapshot mode only; never exposed in responses
    snapshot_ttl_seconds: 60  # snapshot mode only
    timeout_seconds: 30
    max_retries: 2
    max_rows: 1000            # Hard cap on rows returned from a generated query
    max_memory: 512MB         # DuckDB max_memory for retrieval connections
    threads: 2                # DuckDB threads for retrieval connections
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
| **DuckDB file lock contention** between ingestion writes and retrieval reads (`read_only=True` alone does not avoid it: DuckDB rejects differently-configured concurrent connections to one file, and a writer in another process blocks readers) | Route all access through `DuckDBConnectionManager` with a bounded lock-acquire timeout (`locked` mode, default) or query a periodically refreshed read-only snapshot (`snapshot` mode). Lock timeouts and cross-process `IOException` mark the SQL store `unavailable` and yield `"partial"` instead of blocking ingestion or hanging requests. |
| **LLM-generated SQL injection, table-function escape (`query`, `query_table`, `duckdb_*()`), cross-document-set reads from the shared DuckDB file, or local file exfiltration** | Allowlist-based `sqlglot` validation (plain allowlisted unqualified tables only, no table-valued functions, fixed scalar-function allowlist, fail closed on unknown nodes), execution of the re-serialized AST, `enable_external_access = false` followed by `lock_configuration = true`, `max_memory`/`threads` limits, and a hard result row cap. |
| **ACL bypass through stores that cannot enforce per-document ACLs** | Fail closed for ACL-protected document sets: skip DuckDB SQL and DuckDB-backed helpers, skip Milvus/Weaviate targets, and apply `allowed_users` on OpenSearch (D7). |
| **Credential leakage** in config, metadata, or error logs | Keep credentials out of `DataCard`; expand `$VAR`/`${VAR}` at runtime; never log connection dicts or raw driver messages. |
| **Event-loop starvation** from sync SDKs | Offload all blocking SDK calls via `asyncio.to_thread` and cap async concurrency/queue depth (100 pending). |
