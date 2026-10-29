# Spec Delta

## Purpose

How the retrieval engine answers a query: resolving a target to stores through derivatives, searching vector stores with hybrid retrieval and reranking, enforcing document ACLs, running the SQL path, correlating entity rows with documents, summarizing, caching, tracking jobs and events, and degrading gracefully when a store fails. SQL safety is specified separately in `backend/retrieval-sql`.

## ADDED Requirements

### Requirement: Target resolution through derivatives
The engine SHALL resolve `document_library_id` or `asset_id` to stores using `DerivativeResolverPort` only. Stores that are not usable (vector store with unknown provider, entity table with `retrievable` false) SHALL be skipped and reported in `additional_info.skipped`. If no usable store remains, the engine SHALL return 200 with `status: "success"`, empty `results`, and an `additional_info` explanation, not a server error.

#### Scenario: Library with two document sets
- **WHEN** a library has two document sets, each with one vector store
- **THEN** the engine queries both stores and returns two vector result items

#### Scenario: Non-retrievable entity table
- **WHEN** a derivative's entity table has `retrievable: false`
- **THEN** it is skipped and listed in `additional_info.skipped` with reason `not_retrievable`

#### Scenario: No derivatives
- **WHEN** the target has no derivatives
- **THEN** the response has empty `results` and `additional_info` states that no derived data is recorded

### Requirement: Concurrent store queries with partial results
The engine SHALL query all selected stores concurrently, bounded by `retrieval.max_concurrency`, with a per-store timeout from `retrieval.store_timeout_seconds`. A store failure or timeout SHALL NOT fail the request when at least one store succeeded; the response SHALL have `status: "partial"` and list the failed store with a generic reason. When all stores fail the status SHALL be `error`.

#### Scenario: One store down
- **WHEN** two vector stores are queried and one raises a connection error
- **THEN** the response status is `partial`, one item is returned, and `additional_info.failed` names the failed store without host or driver message

#### Scenario: Timeout
- **WHEN** a store exceeds `retrieval.store_timeout_seconds`
- **THEN** it is treated as failed, the abandoned statement is cancelled where the engine supports it, and the others are returned

#### Scenario: Store rejects the credentials
- **WHEN** a store answers with an authentication or authorization failure
- **THEN** the store is reported failed with reason `authorization_error` and is never reported as an empty result

### Requirement: Query embedding compatibility
Before searching a store, the engine SHALL verify that the query embedder's dimension equals the derivative's, and that its model id equals the derivative's when the derivative records one. On mismatch it SHALL skip the store with reason `embedding_mismatch` and MUST NOT search with a mismatched vector. A derivative without a model id and with a matching dimension SHALL be searched with a warning.

#### Scenario: Matching model
- **WHEN** the derivative embeddings are `nomic-embed-text` with dimension 768 and the retrieval embedder is the same
- **THEN** the store is searched

#### Scenario: Derivative model option
- **WHEN** `retrieval.embeddings.use_derivative_model` is true
- **THEN** the embedder is built from the derivative's provider and model through `LLMAdapterFactory`

#### Scenario: Unknown model, matching dimension
- **WHEN** the derivative has no model id but its dimension equals the embedder's dimension
- **THEN** the store is searched and `embedding_model_unverified` is added to `additional_info.warnings`

#### Scenario: Different model, same dimension
- **WHEN** the derivative names model A, the embedder is model B, and the dimensions are equal
- **THEN** the store is skipped with reason `embedding_mismatch`

#### Scenario: Dimension mismatch
- **WHEN** the retrieval embedder yields 1024 dimensions and the derivative says 768
- **THEN** the store is skipped with reason `embedding_mismatch` and no search is issued

### Requirement: Hybrid vector retrieval
For Milvus and OpenSearch stores, the engine SHALL run dense vector search and, when `vector_params.sparse` is true, BM25 keyword search, combined with reciprocal rank fusion using `retrieval.rrf_k` (default 60). The dense metric SHALL be read from the collection or index at query time.

#### Scenario: Metric read from the collection
- **WHEN** a Milvus collection was indexed with an inner-product metric
- **THEN** the dense request uses that metric

#### Scenario: Dense only
- **WHEN** `vector_params.sparse` is false
- **THEN** only dense search runs and `rrf_score` is absent

#### Scenario: Provider adapters
- **WHEN** the derivative provider is `opensearch` or `milvus`
- **THEN** a read-only retriever adapter for that provider is used, and any other provider is skipped with reason `unsupported_provider`

### Requirement: Rerank candidate pool
The engine SHALL fetch `retrieval.rerank_candidates` candidates (default 30, never less than `limit`), optionally rerank them with the configured reranker, and truncate to `limit`. Without a reranker, truncation SHALL follow fused order. A reranker failure SHALL fall back to fused order.

#### Scenario: Hybrid with rerank pool
- **WHEN** `limit` is 5 and `rerank_candidates` is 30 with a reranker configured
- **THEN** 30 candidates are fused and reranked and 5 items are returned

#### Scenario: Rerank failure
- **WHEN** the reranker raises or returns nothing
- **THEN** the fused order is used and the result is still truncated to `limit`, with `rerank_failed` added to `additional_info.warnings`

### Requirement: Document ACL filtering on vector search
When the store's chunk fields include `allowed_users`, the engine SHALL restrict results to chunks whose `allowed_users` contains the authenticated username, using the same fail-closed semantics as `ACLQueryBuilder`. When the username is unavailable and authentication is enabled, the engine SHALL return no chunks. Stores without `allowed_users` SHALL be searched unfiltered.

#### Scenario: Restricted chunk
- **WHEN** a chunk's `allowed_users` does not contain the caller
- **THEN** the chunk is not returned

#### Scenario: No ACL column
- **WHEN** the store has no `allowed_users` field
- **THEN** no ACL filter is applied

### Requirement: Entity rows are not ACL-filtered in this release
The SQL path SHALL NOT apply document ACLs to entity rows. This limitation SHALL be documented and `retrieval.sql.enabled` SHALL switch the SQL path off globally. When SQL is on and any chunk store in the same target has an `allowed_users` field, `additional_info.warnings` SHALL include `sql_not_acl_filtered`.

#### Scenario: Warning emitted
- **WHEN** SQL results are returned for a library whose vector store has `allowed_users`
- **THEN** `additional_info.warnings` contains `sql_not_acl_filtered`

### Requirement: Correlation on id
The engine SHALL derive `document_id` for an entity row by matching its `id` against `^<doc_id>:<table>(:[0-9]+)?$` for the documents returned by vector search, with metacharacters escaped. The match SHALL run in Python after the query. Unmatched rows SHALL be returned without `document_id`.

#### Scenario: Object row
- **WHEN** a row has `id = "doc-1:orders"` and `doc-1` was returned by vector search
- **THEN** the row's `metadata.document_id` is `doc-1`

#### Scenario: List item row
- **WHEN** a row has `id = "doc-1:line_items:3"`
- **THEN** its `document_id` is `doc-1`

#### Scenario: Prefix collision
- **WHEN** documents `a` and `a:b` both exist and a row has `id = "a:b:orders"`
- **THEN** the row is attributed to `a:b` only

#### Scenario: Unmatched row
- **WHEN** a row's `id` matches no returned document
- **THEN** the row is returned without `document_id`

#### Scenario: Special characters in ids
- **WHEN** a document id contains `.` or `(`
- **THEN** matching treats them literally

### Requirement: SQL path orchestration
For each retrievable entity table group, when SQL is enabled, the engine SHALL generate SQL via `TextToSqlPort`, validate and authorize it under `backend/retrieval-sql`, execute it, and request a correction at most `retrieval.sql.max_retries` times (default 2). The statement SHALL select `id`. Failure after retries SHALL fail the store, not the request. Correction input SHALL be the safe diagnostic, never raw engine text.

#### Scenario: Correction succeeds
- **WHEN** the first SQL is invalid and the second succeeds
- **THEN** one SQL item is returned and `additional_info.execution_steps` records two attempts

#### Scenario: Retries exhausted
- **WHEN** all attempts fail
- **THEN** the SQL store is reported failed with a generic reason and vector results are still returned

#### Scenario: No wasted correction
- **WHEN** the final attempt fails
- **THEN** no further correction call is made

### Requirement: Zero rows is a result, not a failure
A SQL statement that executes successfully and returns no rows SHALL produce a SQL result item with `row_count` 0 and empty `data`, which the summary treats as an observation ("none found"). An errored or unauthorized statement MUST NOT be reported as zero rows.

#### Scenario: No matching rows
- **WHEN** a valid query matches nothing
- **THEN** the SQL item has `row_count: 0` and the response status is `success`

#### Scenario: Errored statement
- **WHEN** a statement fails
- **THEN** the store is listed in `additional_info.failed`, not returned as an empty item

### Requirement: Request model applies to every LLM stage
When `search_inference_config.model_id` is set, text-to-SQL generation, SQL correction, and summary generation SHALL use that model through the configured adapter. When absent, the configured default SHALL be used. A model id the adapter does not accept SHALL produce a 400 with code `retrieval_invalid_request` before any store is queried.

#### Scenario: Model override reaches SQL generation
- **WHEN** a request sets `model_id` to `m1`
- **THEN** both the SQL generation call and the SQL correction call use `m1`

#### Scenario: Unsupported model
- **WHEN** `model_id` is not accepted by the adapter
- **THEN** the response is 400 and no store is queried

### Requirement: Credentials for retrieval stores
The retrieval service SHALL obtain endpoints and credentials for vector stores and Postgres from `retrieval.*` configuration and `DOCPIPE_POSTGRES_*` environment variables, never from derivative records, and SHALL resolve `${VAR}` and `vault://` references through the existing secret mechanism. Credentials MUST NOT appear in logs, events, errors, or responses. A derivative whose provider has no retrieval configuration SHALL be skipped with reason `not_configured`.

#### Scenario: Missing provider configuration
- **WHEN** a derivative uses `opensearch` and `retrieval.vector.opensearch` is not configured
- **THEN** the store is skipped with reason `not_configured`

### Requirement: Summary generation
When `generate_summary` is true and an inference adapter is configured, the engine SHALL produce `generated_text` through `LLMInferencePort`, delimiting chunk text and rows as untrusted input. When generation fails, results SHALL be kept, `generated_text` SHALL be null, and `summary_failed` SHALL be added to warnings.

#### Scenario: Summary on
- **WHEN** `generate_summary` is true and the LLM responds
- **THEN** `generated_text` is non-empty

#### Scenario: Prompt framing
- **WHEN** the summary prompt is built
- **THEN** it states that chunk text is ground truth, SQL rows are a secondary index, and insufficient context must be said

#### Scenario: LLM failure
- **WHEN** the LLM call raises
- **THEN** results are returned, `generated_text` is null, and `summary_failed` is in warnings

### Requirement: Cache
When caching is enabled and `disable_cache` is false, identical requests (same normalized query, target, search config, inference config, and user) SHALL be served from `CachePort` until `retrieval.cache.ttl_seconds`. The cache key MUST include the user identity so that ACL-filtered results are never shared across users. Responses with `status` other than `success` SHALL NOT be cached.

#### Scenario: Cache hit
- **WHEN** the same user repeats an identical request within TTL
- **THEN** the second response is served from cache and `additional_info.cache_hit` is true

#### Scenario: Different users
- **WHEN** two users send identical requests
- **THEN** each gets its own cache entry

### Requirement: Job queue
The in-process job queue SHALL hold jobs in states PENDING, DONE, ERROR with a TTL (`retrieval.jobs.ttl_seconds`), a worker pool size (`retrieval.jobs.workers`), and a maximum queued count (`retrieval.jobs.max_queued`). Expired jobs SHALL be removed. The queue is single-process and SHALL document that multi-worker deployments need an external job store.

#### Scenario: TTL expiry
- **WHEN** a finished job is older than the TTL
- **THEN** polling it returns 404

#### Scenario: Capacity
- **WHEN** queued jobs equal `max_queued`
- **THEN** a new submission is rejected

### Requirement: Event store
Each request SHALL record stage events (resolve, embed, vector, sql, rerank, summary, cache) with duration and counts. Events SHALL be kept for `retrieval.events.ttl_seconds` and MUST NOT include query text, SQL text, rows, or credentials.

#### Scenario: Stage durations
- **WHEN** a search completes
- **THEN** events exist for each executed stage with non-negative durations

### Requirement: Input handling of untrusted text
The query text, chunk text, and entity values SHALL be treated as untrusted. They MUST NOT be interpolated into SQL by string formatting outside the generated-and-validated path, into filter expressions without escaping, or into log statements.

#### Scenario: Filter injection attempt
- **WHEN** a username contains a quote or expression syntax
- **THEN** the ACL filter escapes it or uses parameters, and no extra clause is produced

### Requirement: Observability
The engine SHALL log with `get_logger()` using `%s` formatting, include request id, stage, and counts, and MUST NOT log query text, SQL text, row data, or credentials at INFO or above. Spans SHALL be emitted through OpenTelemetry when it is configured.

#### Scenario: Default logging
- **WHEN** a search runs at INFO level
- **THEN** log lines contain request id and counts and no query or SQL text
