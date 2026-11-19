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
The SQL retriever SHALL synthesize a schema description from DuckDB `DESCRIBE` metadata enriched with `src/docpipe/core/document_classes/<document_class_id>.json` (when configured), generate SQL via `LLMInferencePort`, validate and authorize the SQL with `sqlglot` (`duckdb` dialect), execute it against a read-only DuckDB connection with external access disabled and a query timeout, and self-correct up to `max_retries` times on validation or execution failure.

#### Scenario: Valid SELECT query executes against read-only DuckDB
- **WHEN** the generated SQL is a single `SELECT` statement referencing only allowlisted table(s) for the target `DocumentSet`
- **THEN** it executes on a `read_only=True` DuckDB connection with `enable_external_access = false` and returns a single `ResultItem` with `source: "sql"`, `data`, and `metadata.sql`

#### Scenario: Disallowed SQL statement, table function, or CTE shadowing is rejected without retry
- **WHEN** the generated SQL contains DDL/DML (`DROP`, `INSERT`, `COPY`, `ATTACH`, `PRAGMA`), multiple statements, DuckDB file/external table functions (`read_csv`, `read_parquet`, `read_text`, `glob`), CTEs shadowing allowlisted tables, or references a table outside the target `DocumentSet` allowlist
- **THEN** the SQL is NOT executed and the authorization failure fails fast without invoking the self-correction LLM

#### Scenario: Self-correction retry loop skips non-repairable failures and stops after max_retries
- **WHEN** SQL fails with a repairable syntax or binder error up to `max_retries + 1` total attempts, or fails with a non-repairable error (authorization, timeout, cancellation, connection error)
- **THEN** non-repairable errors fail fast with no correction call, no correction call is made after the final attempt, the SQL store is marked failed, and any succeeding vector results are still returned with `status: "partial"`

#### Scenario: SQL retrieval skipped when retrieval.sql.enabled is false
- **WHEN** `retrieval.sql.enabled` is false and a `DocumentSet` has a DuckDB table
- **THEN** the SQL retriever is not dispatched, a note is recorded in `additional_info`, and vector retrieval (if configured) proceeds normally

#### Scenario: Query timeout triggers DuckDB interruption
- **WHEN** a DuckDB query exceeds `sql.timeout_seconds`
- **THEN** the engine invokes `conn.interrupt()` via `CancelHandle` and aborts the query cleanly

### Requirement: Concurrent multi-backend vector retrieval
The vector retriever SHALL support **Milvus**, **OpenSearch**, and **Weaviate** vector store targets, searching all configured targets for a `DocumentSet` concurrently and producing one `ResultItem` (`source: "vector"`) per non-empty target.

#### Scenario: Milvus hybrid search with dense-only fallback
- **WHEN** a vector target has `provider: "milvus"` and a `sparse_field` configured
- **THEN** the adapter executes hybrid dense + BM25 search with RRF and falls back to dense-only ANN if hybrid search raises an error

#### Scenario: OpenSearch vector search with ACL filtering
- **WHEN** a vector target has `provider: "opensearch"` and the request includes an authenticated user
- **THEN** the adapter applies the `allowed_users` ACL filter alongside k-NN / hybrid search

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
