# backend/retrieval-engine Specification

## Purpose

Defines the observable behavior of the native Docling Pipelines retrieval engine: derivative-driven store routing over local `DocumentLibrary`, `DocumentSet`, and `DataCard` (PR #639) assets, DuckDB Text-to-SQL with safety enforcement and self-correction, concurrent vector search across Milvus, OpenSearch, and Weaviate with optional reranking, hybrid correlation and LLM synthesis, multi-Document-Set DAG planning, and caching.

## ADDED Requirements

### Requirement: Local derivative-driven store routing
The engine SHALL resolve SQL tables from `DocumentSet` storage attachments and vector stores from `DocumentSet.data_card` (merged with `retrieval.vector_stores` config defaults and optional `DocumentSet.metadata["retrieval_derivatives"]` overrides). Single-set routing SHALL be strictly derivative-driven with no LLM intent classification.

#### Scenario: Document set with only a DuckDB table routes to SQL
- **WHEN** a `DocumentSet` exposes a DuckDB SQL table and no vector store derivatives
- **THEN** only the SQL retriever is dispatched

#### Scenario: Document set with vector derivative in DataCard routes to vector
- **WHEN** a `DocumentSet.data_card` records a `vectordb` `derivative_store` (`milvus`, `opensearch`, or `weaviate`) and `embeddings` metadata, with no SQL table
- **THEN** only the vector retriever is dispatched using the `DataCard` collection/index and embedding model

#### Scenario: Hybrid document set dispatches SQL and vector concurrently
- **WHEN** a `DocumentSet` exposes both a DuckDB SQL table and one or more vector store derivatives
- **THEN** both SQL and vector retrievers are dispatched concurrently and SQL `ResultItem` entries appear before vector `ResultItem` entries in `results`

#### Scenario: Missing derivatives returns partial status
- **WHEN** a `DocumentLibrary` or `DocumentSet` has no resolvable SQL or vector derivatives
- **THEN** no retriever is dispatched, `results` is empty, and `status` is `"partial"`

### Requirement: Safe DuckDB Text-to-SQL retrieval
The SQL retriever SHALL generate SQL via `LLMInferencePort` from a schema description (DuckDB `DESCRIBE` metadata enriched with the configured document class), validate it with an allowlist-based `sqlglot` validator (`duckdb` dialect), execute only the validator's re-serialized SQL through `DuckDBConnectionManager` on a hardened read-only connection, and self-correct up to `max_retries` times on repairable failures.

#### Scenario: Connection is hardened before SQL runs
- **WHEN** the SQL engine opens a DuckDB connection for a generated query
- **THEN** it applies `enable_external_access = false`, then `lock_configuration = true`, plus `max_memory`, `threads`, a hard result row cap, and a query timeout, before executing any generated SQL

#### Scenario: Valid SELECT query executes against read-only DuckDB
- **WHEN** the generated SQL is a single `SELECT` statement referencing only allowlisted, unqualified table(s) for the target `DocumentSet` and only allowlisted functions
- **THEN** the validator's re-serialized SQL executes on a read-only DuckDB connection obtained via `DuckDBConnectionManager` with `enable_external_access = false` and `lock_configuration = true`, and returns a single `ResultItem` with `source: "sql"`, `data`, and `metadata.sql`

#### Scenario: Disallowed SQL statement, table function, qualified name, or CTE shadowing is rejected without retry
- **WHEN** the generated SQL contains DDL/DML (`DROP`, `INSERT`, `COPY`, `ATTACH`, `PRAGMA`, `SET`), multiple statements, any table-valued function (for example `read_csv`, `read_parquet`, `read_text`, `glob`, `query`, `query_table`, `duckdb_databases`, `duckdb_settings`, `pragma_table_info`), a function or AST node type outside the validator allowlist, a catalog- or schema-qualified table name (for example `information_schema.tables`, `other_db.main.t`), CTEs shadowing allowlisted tables, or references a table outside the target `DocumentSet` allowlist
- **THEN** the SQL is NOT executed and the authorization failure fails fast without invoking the self-correction LLM

#### Scenario: Generated SQL cannot re-enable external access
- **WHEN** a statement attempts `SET enable_external_access = true` or `SET lock_configuration = false`
- **THEN** the validator rejects it, and even if it reached DuckDB the locked configuration would refuse it

#### Scenario: Result row cap truncates and degrades status
- **WHEN** a generated query would return more than `retrieval.sql.max_rows` rows
- **THEN** at most `max_rows` rows are returned, a truncation note is recorded in `additional_info`, and `status` is `"partial"`

#### Scenario: Self-correction retry loop skips non-repairable failures and stops after max_retries
- **WHEN** SQL fails with a repairable syntax or binder error up to `max_retries + 1` total attempts, or fails with a non-repairable error (authorization, timeout, cancellation, lock-acquire timeout, connection error)
- **THEN** non-repairable errors fail fast with no correction call, no correction call is made after the final attempt, the SQL store is marked failed, and any succeeding vector results are still returned with `status: "partial"`

#### Scenario: SQL retrieval skipped when retrieval.sql.enabled is false
- **WHEN** `retrieval.sql.enabled` is false and a `DocumentSet` has a DuckDB table
- **THEN** the SQL retriever is not dispatched, a note is recorded in `additional_info`, and vector retrieval (if configured) proceeds normally

#### Scenario: Query timeout triggers DuckDB interruption
- **WHEN** a DuckDB query exceeds `sql.timeout_seconds`
- **THEN** the engine invokes `conn.interrupt()` via `CancelHandle`, aborts the query cleanly, and releases the file lock

### Requirement: DuckDB access mode and file-lock handling
The SQL engine SHALL access document-set DuckDB files only through `DuckDBConnectionManager` and SHALL support `retrieval.sql.access_mode` values `locked` (default) and `snapshot`. In `locked` mode it SHALL acquire the per-file lock within `retrieval.sql.lock_timeout_seconds`. In `snapshot` mode it SHALL query a read-only snapshot copy that is refreshed no more often than `retrieval.sql.snapshot_ttl_seconds` and SHALL NOT take the source file lock when reading.

#### Scenario: Locked mode serializes with ingestion and times out when the lock is busy
- **WHEN** `access_mode` is `locked` and the per-file lock is not acquired within `lock_timeout_seconds`
- **THEN** the SQL store is marked `unavailable` without invoking the self-correction LLM, ingestion writes are not blocked beyond the single running query, and the response `status` is `"partial"` (or `"error"` when no other store succeeded)

#### Scenario: Cross-process writer makes the file unavailable
- **WHEN** a writer in another process holds the DuckDB file and DuckDB raises an `IOException` on open
- **THEN** the SQL store is marked `unavailable` with a sanitized diagnostic containing no filesystem path

#### Scenario: Snapshot mode reads without taking the source lock
- **WHEN** `access_mode` is `snapshot` and a snapshot younger than `snapshot_ttl_seconds` exists
- **THEN** the query runs read-only against the snapshot without acquiring the source file lock, and ingestion is not blocked

#### Scenario: Stale snapshot served when refresh cannot lock the source
- **WHEN** `access_mode` is `snapshot`, the snapshot is older than the TTL, and the refresh cannot acquire the source lock within `lock_timeout_seconds`
- **THEN** the previous snapshot is served and `additional_info` notes that the data may be stale

### Requirement: Fail-closed handling of ACL-protected document sets
The engine SHALL treat a `DocumentSet` as ACL-protected when `DataCard.propagate_source_acls` is true or `DocumentSet.metadata["retrieval_derivatives"]["acl_protected"]` is true. For an ACL-protected set the engine SHALL skip DuckDB SQL retrieval and all DuckDB-backed helpers, SHALL query OpenSearch targets only with the mandatory `allowed_users` filter for the authenticated user, and SHALL skip Milvus and Weaviate targets.

#### Scenario: ACL-protected set skips SQL regardless of retrieval.sql.enabled
- **WHEN** a `DocumentSet` is ACL-protected, has a DuckDB table, and `retrieval.sql.enabled` is true
- **THEN** the SQL retriever is not dispatched, `additional_info` records a generic `acl_protected_store_skipped` note, and `status` is `"partial"` unless another store returned results for the set

#### Scenario: ACL-protected OpenSearch target is always filtered
- **WHEN** an ACL-protected set has an OpenSearch vector target
- **THEN** the query includes the `allowed_users` filter for the authenticated user, and a request without a resolvable user identity returns no hits for that target

#### Scenario: ACL-protected Milvus or Weaviate target is skipped
- **WHEN** an ACL-protected set has a Milvus or Weaviate vector target
- **THEN** the target is not queried and a generic `acl_protected_store_skipped` note is recorded without store names or paths

### Requirement: Concurrent multi-backend vector retrieval
The vector retriever SHALL support **Milvus**, **OpenSearch**, and **Weaviate** vector store targets, searching all configured targets for a `DocumentSet` concurrently and producing one `ResultItem` (`source: "vector"`) per non-empty target.

#### Scenario: Milvus hybrid search with dense-only fallback
- **WHEN** a vector target has `provider: "milvus"` and a `sparse_field` configured
- **THEN** the adapter executes hybrid dense + BM25 search with RRF and falls back to dense-only ANN if hybrid search raises an error

#### Scenario: OpenSearch vector search with ACL filtering
- **WHEN** a vector target has `provider: "opensearch"` and the request includes an authenticated user
- **THEN** the adapter applies the `allowed_users` ACL filter alongside k-NN / hybrid search (mandatory for ACL-protected sets)

#### Scenario: Weaviate named-vector and BM25 hybrid search
- **WHEN** a vector target has `provider: "weaviate"`
- **THEN** the adapter queries the collection using `weaviate-client` v4 (`near_vector` on `vector_field`, or `hybrid` when BM25/sparse mode is enabled) and closes the client on completion

#### Scenario: Optional reranking over expanded candidate pool
- **WHEN** a reranker is configured (`ollama`, `watsonx`, or `cross_encoder`) and request `limit` is `L`
- **THEN** each vector target fetches `max(L, rerank_candidates)` hits, reranks them, and returns at most `L` hits in reranked order (falling back to original order truncated to `L` on reranker error)

### Requirement: Hybrid correlation and LLM synthesis
When both SQL and vector stores exist for a `DocumentSet`, the schema prompt SHALL instruct SQL generation to include the correlation column (`document_id`). When an inference LLM is configured, the synthesizer SHALL combine SQL rows (as Markdown tables) with deduplicated vector chunks grouped by `document_id` and populate `generated_text`.

#### Scenario: Answer synthesized from hybrid SQL and vector results
- **WHEN** both SQL and vector retrievers return hits and an inference LLM is configured
- **THEN** `generated_text` is populated from the unified SQL + vector context

#### Scenario: Raw retrieval when no inference LLM is configured
- **WHEN** no inference LLM is configured
- **THEN** `generated_text` is `None` and `results` contains the ordered SQL and vector `ResultItem`s

### Requirement: Multi-Document-Set DAG planning
When a `DocumentLibrary` contains more than one `DocumentSet`, the engine SHALL use an LLM outer planner to decompose the query into a DAG of per-Document-Set sub-questions and execute independent steps in parallel waves, delegating each step to `SearchOrchestrator`.

#### Scenario: Single-set library bypasses outer planner
- **WHEN** a `DocumentLibrary` contains exactly one `DocumentSet`
- **THEN** the engine delegates directly to `SearchOrchestrator` without invoking the outer planner

#### Scenario: Multi-set library executes planned DAG waves
- **WHEN** a `DocumentLibrary` contains multiple `DocumentSet`s
- **THEN** the outer planner assigns sub-questions to target `DocumentSet`s, `DAGExecutor` runs each wave concurrently, and results are merged into a single `QueryResponse`

### Requirement: Result caching
When caching is enabled and `disable_cache` is false, the engine SHALL cache successful `QueryResponse` objects keyed by a digest of the caller identity and normalized request parameters, and bypass the cache when `disable_cache` is true.

#### Scenario: Cache hit returns stored response
- **WHEN** an identical request from the same user arrives within the cache TTL
- **THEN** the cached `QueryResponse` is returned without re-querying SQL or vector stores

#### Scenario: Cache bypass skips lookup and write
- **WHEN** a request sets `disable_cache: true`
- **THEN** the engine executes fresh store queries and does not read from the cache
