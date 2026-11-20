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
    │   │   ├── derivatives.py                # LibraryDescriptor, DocumentSetDescriptor, SqlTableTarget (kind),
    │   │   │                                 # VectorStoreTarget (column_mapping), DocumentClassContext
    │   │   └── plan.py                       # SubQuestion, QueryPlan, ExecutionWave
    │   ├── ports/
    │   │   ├── catalog_port.py               # RetrievalCatalogPort ABC
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
    │   │   └── local_catalog_adapter.py      # Wraps DerivativeResolverPort; config merge, overrides, SQL table target
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

### D1. Derivative Discovery via `DerivativeResolverPort` (card-derived) + Local Storage Attachments
PR #639 (`add-document-set-data-card`) makes `DocumentSet.data_card` the single system-maintained provenance record while keeping `DocumentSet.metadata` strictly user-owned. The `add-document-library-derivatives` change turns that card into resolved derivatives behind `DerivativeResolverPort` (contract in `proposal.md`). Retrieval does NOT walk the card and does NOT record provenance. `LocalRetrievalCatalogAdapter` composes four inputs and never mutates `DocumentSet.metadata`:

1. **SQL table (automatic)**: a `SqlTableTarget(kind="document_set_table")` built from the `DocumentSet`'s existing DuckDB storage attachment (`database_path`, `table_name`). `kind="entity_table"` is declared on the model for a follow-up but is rejected as unsupported here.
2. **Vector stores & embeddings (from the resolver)**: for each resolved store, the adapter uses `provider`, `path`, `embedding.{provider, model_id, dimension_size}`, `add_sparse_vector`, `column_mapping`, `acl_protected` and `conflicts`:
   - **Index field names come from `column_mapping`, never from the card's embedding `feature`.** The card's `feature` is the source table column (default `embeddings`); the index field is the mapped column. When no mapping is recorded, the adapter falls back to the `vectordb` operator defaults (`vector_embeddings`, `document_id`, `sparse_embeddings`, `text`). `allowed_users` has no default: when it is not mapped, the store is treated as unable to enforce ACLs (D7).
   - `embedding.provider` unknown: fall back to `retrieval.embeddings.default_provider`. `add_sparse_vector` unknown: detect via live collection schema introspection, then override.
   - `acl_protected` true marks the set ACL-protected, which triggers the fail-closed behavior in D7 (not merely a hint).
   - `DataCard.purpose`, `summary`, and `language` (read through the resolver's descriptive fields) are passed to `OuterQueryPlanner` / `SchemaFormatter` to improve multi-Document-Set routing.
   - `conflicts` returned by the resolver (same `(provider, path)` with different embedding model or dimension across flows) are surfaced as a generic note in `additional_info`; the resolver's most-recent-wins value is used.
3. **Connection settings (config only)**: the card records no hosts or credentials (PR #639 D5). Connection parameters come from `retrieval.vector_stores.<provider>` (with `$VAR`/`${VAR}` expansion). This model supports **one cluster per provider**; two stores of the same provider on different clusters cannot be addressed (documented limitation).
4. **Optional user overrides (`DocumentSet.metadata["retrieval_derivatives"]`)**: the card builder only walks *ancestors* of `document_set`, so a `vectordb` sink on a sibling branch or downstream of it is not recorded. Users may declare extra vector targets, `sparse_field`, `embedding_provider`, `column_mapping`, `acl_protected`, or `document_class_id` here. Explicit entries merge with and take precedence over resolver output.

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
   - **`snapshot` (opt-in for busy deployments)**: Query a read-only, **table-scoped** snapshot stored under `retrieval.sql.snapshot_dir` (never exposed in responses or logs). While holding the source file's manager lock, the engine creates a new DuckDB file containing ONLY copies of the allowlisted tables of the document sets being queried (for example `CREATE TABLE snap.t AS SELECT * FROM t` through an attached snapshot file), written under a temporary name and atomically renamed. The snapshot NEVER contains other tables of the shared file (document-set metadata, library, or data-card tables, or unrelated sets' data). The snapshot directory is created with mode `0700` and snapshot files with `0600`. A snapshot is keyed by `(database_path, table names)`, refreshed single-flight when older than `retrieval.sql.snapshot_ttl_seconds` (default 60), and opened `read_only=True` WITHOUT taking the source lock. If a refresh cannot acquire the source lock within `lock_timeout_seconds`, the previous snapshot is served and `additional_info` notes that the data may be stale; if no snapshot exists yet the store is marked `unavailable`. Results may lag ingestion by up to the TTL, and the copy time grows with table size.
   - **Shared-file contention**: by default the document-set data tables, the document-set and library metadata repositories, and the data cards all live in the same `document_sets.duckdb`, and every access goes through the same per-path lock. In `locked` mode a running retrieval query therefore also blocks the asset API, data-card recording, and `document_set` operator writes for that file for up to `sql.timeout_seconds`. `locked` is the default for single-user and low-concurrency deployments only; `snapshot` is RECOMMENDED when ingestion or asset API traffic runs concurrently with retrieval (documented in the guide).
3. **Connection Hardening & Resource Limits**: On every retrieval connection, after trusted schema introspection and before executing model-generated SQL, run `SET enable_external_access = false`, `SET lock_configuration = true` (so SQL cannot undo the setting), `SET max_memory = '<retrieval.sql.max_memory>'` (default `512MB`) and `SET threads = <retrieval.sql.threads>` (default `2`). The result is fetched with a hard row cap (`retrieval.sql.max_rows`, default `1000`); rows beyond the cap are dropped, a truncation note is recorded in `additional_info`, and `status` becomes `"partial"`.
4. **Deadline, Cancellation & Fail-Fast Retries**: Enforce a per-query deadline (`sql.timeout_seconds`, default 30s). On timeout or caller cancellation, invoke `conn.interrupt()` via `CancelHandle` from the coordinator thread to abort long-running scans cleanly and release the file lock. Non-repairable errors (authorization refusal, timeout, cancellation, lock-acquire timeout, connection failure) fail fast without invoking the self-correction LLM.
5. **Schema & Document Class Enrichment**: Introspect column names/types via `DESCRIBE <table>` (trusted internal path, executed before the hardening step) and enrich them with descriptions/examples/extraction instructions from `src/docpipe/core/document_classes/<document_class_id>.json` when `document_class_id` is set.
6. **SQL Kill-Switch (`retrieval.sql.enabled`)**: Operators can set `retrieval.sql.enabled: false` to disable SQL retrieval globally; SQL routing is skipped cleanly with a note in `additional_info`. For ACL-protected document sets the SQL path is disabled automatically regardless of this flag (see D7).

### D7. Authorization Model & Fail-Closed ACL Handling
The retrieval service MUST NOT imply a stronger access-control model than the platform provides. Current platform facts: `DocumentLibrary` only carries an informational `created_by` and the existing `/api/v1/document-libraries` routes do not call `get_current_user`; per-row ACLs exist only as the OpenSearch `allowed_users` field populated when `propagate_source_acls` is set and mapped into the index; DuckDB tables, Milvus collections, and Weaviate collections carry no ACL enforcement.

1. **Authentication**: All v1/v2 search and result-polling routes depend on `get_current_user` (HTTP bearer JWT). Unauthenticated callers get `401`. Only `/v2/retrieval/healthz` and `/v2/retrieval/readyz` are unauthenticated. These routes sit outside `/api/v1`; see the routing note in `proposal.md`. When an authn/authz change lands, `get_current_user` is swapped for its role-based dependency.
2. **Library/set level**: There is no per-library or per-document-set ownership model. Any authenticated user may query any `DocumentLibrary`/`DocumentSet` for which retrieval is enabled. `RetrievalACLPort` therefore exposes only the caller identity and the per-document ACL hints below; library-level authorization is explicitly out of scope and MUST be documented as such in `docs/guides/RETRIEVAL_SERVICE_GUIDE.md`. Per-user ownership applies to async job results only (`query_id`).
3. **ACL-protected document set**: A `DocumentSet` is *ACL-protected* when the resolver reports `acl_protected` true (card `propagate_source_acls`) or `DocumentSet.metadata["retrieval_derivatives"]["acl_protected"]` is true. For an ACL-protected set the engine fails closed:
   - **SQL (DuckDB) retrieval is skipped**, and every DuckDB-backed helper (`column_values`, `find_documents`, literal-spelling probes, agent `query_table`/`list_documents`/`read_document`) is unavailable for it, because DuckDB tables cannot enforce per-row ACLs. `retrieval.sql.enabled` does not need to be changed by the operator.
   - **OpenSearch** targets are queried with the mandatory `allowed_users` filter for the authenticated user, but ONLY when the store's `column_mapping.allowed_users` is known (recorded by #639 or set by override). If the mapping is unknown or absent, the store is skipped, because the filter cannot be guaranteed to match an indexed field.
   - **Milvus and Weaviate** targets are skipped, because the adapters cannot enforce `allowed_users`. (Adding filtering support is a follow-up and lifts the skip for that provider.)
   - Each skip is recorded in `additional_info` as a generic note (`acl_protected_store_skipped`) without store names or paths, and `status` is `"partial"`.
4. **Cache and event isolation**: The cache key already includes caller identity; request event timelines and metrics-by-request are owner-scoped (see Phase 3).

### D4. Vector Query Adapters (Milvus, OpenSearch, Weaviate)
All three vector backends implement `VectorStoreQueryPort.search(...)` and offload blocking SDK calls via `asyncio.to_thread`:
`VectorStoreTarget.vector_field`, `sparse_field`, `id_field`, `text_field` and `acl_field` are populated from the resolver `column_mapping` (D1), never from the card's embedding `feature`. `sparse_field` is set only when `add_sparse_vector` is true (or detected/overridden).
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
    access_mode: locked       # locked (default; DuckDBConnectionManager lock) | snapshot (table-scoped read-only copy, may be stale; recommended with concurrent ingestion)
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
  vector_stores:              # Default connection settings used to resolve card derivative_store providers (one cluster per provider)
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
    default_provider: ollama  # Fallback when the resolver reports no embedding provider
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
| **PR #639 / #496 merge ordering** (nested `DataCard` and `DerivativeResolverPort` not yet on `main`) | This change is blocked on both (see "Dependencies on Other Changes"). `LocalRetrievalCatalogAdapter` depends only on the port, so retrieval tests use a fake resolver; with no resolver output a set is routable only through its DuckDB attachment and `metadata["retrieval_derivatives"]` overrides. |
| **Sibling-branch `vectordb` sinks** not captured in the card | Support optional `DocumentSet.metadata["retrieval_derivatives"]["vector_stores"]` overrides that merge with resolver output. |
| **Mapping drift**: card embedding `feature` mistaken for the index field | Index fields come only from the resolver `column_mapping` (operator defaults as fallback); a scenario asserts the card `feature` is never used as a vector field. |
| **Multi-flow provenance ambiguity** | The resolver owns a deterministic merge rule (latest run per flow, union, most recent wins per `(provider, path)`); retrieval surfaces conflicts as a note. |
| **DuckDB file lock contention** between ingestion writes, asset API, data-card recording and retrieval reads (all share `document_sets.duckdb` by default; `read_only=True` alone does not avoid it) | Route all access through `DuckDBConnectionManager` with a bounded lock-acquire timeout (`locked` mode, default) or query a periodically refreshed table-scoped read-only snapshot (`snapshot` mode, recommended with concurrent traffic). Lock timeouts and cross-process `IOException` mark the SQL store `unavailable` and yield `"partial"` instead of blocking ingestion or hanging requests. |
| **Snapshot data exposure** (a whole-file copy would include metadata, library and data-card tables and unrelated sets) | Snapshots copy only allowlisted tables of the queried sets into a new file under a `0700` directory (files `0600`); never the shared file. |
| **LLM-generated SQL injection, table-function escape (`query`, `query_table`, `duckdb_*()`), cross-document-set reads from the shared DuckDB file, or local file exfiltration** | Allowlist-based `sqlglot` validation (plain allowlisted unqualified tables only, no table-valued functions, fixed scalar-function allowlist, fail closed on unknown nodes), execution of the re-serialized AST, `enable_external_access = false` followed by `lock_configuration = true`, `max_memory`/`threads` limits, and a hard result row cap. |
| **ACL bypass through stores that cannot enforce per-document ACLs** | Fail closed for ACL-protected document sets: skip DuckDB SQL and DuckDB-backed helpers, skip Milvus/Weaviate targets, apply `allowed_users` on OpenSearch only when its index mapping is known, and skip it otherwise (D7). |
| **Credential leakage** in config, metadata, or error logs | Keep credentials and hosts out of the card; expand `$VAR`/`${VAR}` at runtime; never log connection dicts or raw driver messages. |
| **Event-loop starvation** from sync SDKs | Offload all blocking SDK calls via `asyncio.to_thread` and cap async concurrency/queue depth (100 pending). |
