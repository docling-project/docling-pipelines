# Design

## Context

`.bob/tmp/retrieval-v2/` is a standalone FastAPI service (`SearchOrchestrator`, `SqlRetriever`, Milvus hybrid retriever, job queue, event store, agent). It depends on a remote Document Library API for derivatives, `python-jose`, `structlog`, Presto, and CAMS. docpipe already has the pieces retrieval needs locally: derivative records (`add-document-library-derivatives`), `LLMInferencePort`/`LLMEmbeddingPort` with `LLMAdapterFactory`, ACL columns, `sqlglot`, `duckdb`, `psycopg2`, `pymilvus`, `opensearch-py`, auth, error handling, and OpenTelemetry. The port is therefore a re-implementation of the working behavior inside docpipe's layering, not a copy.

Existing ports are synchronous. Retrieval needs concurrency across stores; use a bounded `ThreadPoolExecutor` rather than introducing async ports.

## Goals / Non-Goals

Goals: hybrid vector search on Milvus and OpenSearch; safe text-to-SQL on DuckDB/Postgres; sync and async search; graceful partial results; no new required dependencies.
Non-goals: see proposal (agent, SOTA features, Presto, entity ACLs, distributed jobs).

## DDD layers

```
core/retrieval/
  domain/
    models/        RetrievalQuery, SearchConfigItem, ResultItem, RetrievalResult, JobRecord, RetrievalEvent
    ports/         VectorRetrieverPort, SqlEnginePort, TextToSqlPort, RerankerPort,
                   CachePort, JobQueuePort, EventStorePort, SummarizerPort
    errors.py      reason codes (not_configured, embedding_mismatch, store_busy, timeout, ...)
  application/
    services/
      search_service.py        SearchService      (orchestrates; sync entry point)
      search_job_service.py    SearchJobService   (submit/poll, owner check)
      store_planner.py         StorePlanner       (derivatives -> StoreTask list)
      vector_search.py         VectorSearchStep   (embed, compat check, retriever, rrf, rerank)
      sql_search.py            SqlSearchStep      (generate, validate, execute, retry)
      sql_validator.py         SqlValidator       (sqlglot; pure @staticmethods)
      correlator.py            IdCorrelator       (anchored match; pure)
      rrf.py                   RRF fusion         (pure)
      summarizer.py            Summarizer         (LLMInferencePort)
      evaluator.py             Evaluator
  adapters/
    vector/milvus_retriever.py, opensearch_retriever.py       (read-only; pymilvus / opensearch-py)
    sql/duckdb_engine.py, postgres_engine.py
    cache/in_memory_cache.py, redis_cache.py (optional extra)
    jobs/in_process_job_queue.py
    events/in_memory_event_store.py
    rerank/sentence_transformers_reranker.py, noop_reranker.py
  factories/retrieval_factory.py   wires adapters to ports at startup
api/routes/retrieval.py, api/dto/retrieval_dto.py, api/dto/retrieval_mapper.py
```

Application code never imports adapters; `retrieval_factory.py` is the only wiring point. Routes return DTOs. Pure helpers are `@staticmethod`. Multi-parameter functions are keyword-only. Logging via `get_logger()` with `%s`.

## Decisions

### D1. Routes in repo style, no UDP layer
Confirmed with the user. `container_id`/`container_type` are accepted and ignored. Agent routes are registered and return 501 until `add-retrieval-agent`.

### D2. Threads for concurrency
`SearchService` runs one `StoreTask` per store in a `ThreadPoolExecutor(max_workers=retrieval.max_concurrency)`, with `future.result(timeout=...)`. Timeouts mark the store failed; the worker thread may keep running until the driver call returns, so adapters set their own client timeouts as well. `SessionInfo` is thread-local, so the request's user and ids are passed explicitly in a `RequestContext` value object (not through `SessionInfo`).

### D3. Retrieval-only adapters
Existing `VectorStorePort` is write-oriented and `TableStoragePort.execute_query` is not safe for generated SQL (see findings: Postgres commits and has no read-only mode or timeout; DuckDB read-only only for keyword-detected statements). New read-only adapters are created under `core/retrieval/adapters`. They reuse config models and field names (`MilvusConfig.collection_name`, OpenSearch `index_name`), not write classes.

### D4. Milvus hybrid
The dense metric is read from the collection's index at query time (retrieval-v2 does the same after a review finding); a wrong dimension fails with a clear mismatch reason. Dense `AnnSearchRequest` on the mapped vector field and sparse BM25 request on the sparse field when `vector_params.sparse`; fused with `RRFRanker(k)`. Field names come from the derivative's `column_mapping`, not hard-coded. Output fields exclude vectors.

### D5. OpenSearch hybrid
kNN query on the vector field and `match` on the text field executed as two searches and fused in Python by `rrf.py`, which avoids dependence on the server-side search pipeline version. ACL filter is a `terms`/`term` filter in both queries using the same builder logic as `ACLQueryBuilder`; the value is passed as a JSON value, never concatenated.

### D6. RRF and rerank pool
Pure `reciprocal_rank_fusion(*, rankings, k)` over ids. Candidate pool = `max(rerank_candidates, limit)`. A failed rerank keeps fused order and still truncates to `limit`. Reranker port optional; default `noop`. `sentence-transformers` cross-encoder adapter loads lazily to avoid startup cost.

### D7. Embeddings
Default: retrieval uses the embedder from `retrieval.embeddings` (provider, model) via `LLMAdapterFactory.create_embedding_adapter`. Before each vector search the step compares dimension (always) and model id (when the derivative records one) with the derivative's `embeddings`; mismatch skips the store, and an unrecorded model with equal dimension proceeds with an `embedding_model_unverified` warning. Optional `use_derivative_model` builds the adapter from the derivative (provider and model) for convenience. Adapters are cached per `(provider, model)`.

### D8. SQL safety layering
1. `validate_and_authorize` (sqlglot, one function for every statement: generated, corrected, any fixed read) as first gate: single SELECT, scope walk of all physical relations, CTE names never authorize a table, only plain tables, catalogs and table functions refused, names resolved against the session schema, dialect-aware identifier case, id rule. Table-level only; column grants stay with the database role.
2. Engine hardening as second gate: DuckDB read-only + external access off + configuration locked, opened per query; Postgres read-only role/transaction, `statement_timeout`, `search_path`.
3. Row cap and timeout in the engine.
Validation is a convenience and attack-surface reducer, not the security boundary; the engine settings are. DuckDB hardening was verified experimentally on duckdb 1.3.2: `read_csv`, `read_text`, `COPY`, `ATTACH`, `glob`, `INSTALL`, reconfiguration, and DDL/multi-statement are blocked; `pragma database_list` still shows the path (minor, mitigated by the table allowlist and catalog rejection). `enable_external_access=false` is applied via `SET` after connect because passing it in `config=` fails when another connection to the same file uses a different config.
DuckDB read-only open fails if a pipeline writes the file; reported as `store_busy`. Documented; operators needing concurrent query and ingest should use Postgres.

### D8a. Safe diagnostics, deadlines, cancellation (adopted from retrieval-v2 PR #33)
- **Diagnostics.** Each engine adapter maps driver errors at its own boundary (DuckDB exception class, Postgres SQLSTATE) to `(kind, engine_code, fixed template, identifier only if present in the submitted SQL)` and raises without chaining the raw exception (`raise ... from None`, and no `inner`). Only repairable kinds reach `TextToSqlPort.correct`; the correction prompt also receives the real column names of the referenced allowed tables.
- **Deadline.** `RequestContext.deadline` is an absolute `time.monotonic()` instant. Each statement gets `min(time_left, retrieval.sql.timeout_seconds)` rounded up to whole milliseconds with a floor of 1 ms (0 means "no limit" on Postgres). Postgres sets a transaction-local `statement_timeout`; DuckDB starts a `threading.Timer` that calls `connection.interrupt()` and cancels it in `finally`. No engine or correction call is made after the deadline.
- **Cancellation.** One `CancelHandle` per statement. The adapter binds an action once the statement can be cancelled (DuckDB `interrupt`, Postgres `connection.cancel()`) and releases it before closing the connection. Outcome is `acknowledged` (statement ended with the engine's cancel error), `unconfirmed`, or `not_running`. I verified on duckdb 1.3.2 that `interrupt()` raises `InterruptException` after about the requested delay. Rows read after a cancel are discarded. A cancel requested before the statement starts means the statement is not run.
- **Capabilities.** `EngineCapabilities(statement_timeout, read_only_session, cancellation)` so a later Presto adapter, which has no read-only session, can state that the validator is its only read-only guard.
- **Limit of this.** Whether an installed server honors the limit is accepted per engine and tested with fakes plus a real DuckDB; Postgres cancellation is tested with mocks and a manual Docker test.
- **Source.** Behavior mirrors retrieval-v2 changes `c0-scope-aware-sql-authorization`, `er0-safe-engine-diagnostics`, `t0-engine-deadline-and-read-only-session`, `t1-request-scoped-sql-cancellation`. docpipe names are descriptive, not the `c0/er0/t0/t1` prefixes.

### D8b. Quote handling
No upstream-value substitution into SQL text is ported. retrieval-v2 `clean_value` escapes with `\'`, which Presto and ANSI SQL reject (needs `''`); the only values that enter SQL here are inside LLM-generated statements that are parsed and validated.

### D8c. Request model, zero rows, store auth failures
`RequestContext.model_id` is passed to `TextToSqlPort.generate/correct` and `SummarizerPort` (retrieval-v2 #32 fixed text-to-SQL always using its default model). A successful zero-row statement is returned as an item with `row_count: 0`. A store authentication or authorization failure is a failed store with reason `authorization_error`, so it can't read as "no evidence" (a known gap in retrieval-v2).

### D9. Correlation in Python
After vector results are known, build the set of `document_id`s. For each entity row, attempt anchored match per candidate document id and table name. Efficient form: strip the suffix with a single regex `^(?P<doc>.+?):(?P<table>[^:]+)(?::(?P<idx>[0-9]+))?$` is ambiguous when doc ids contain `:`, so the correlator instead tests each known `doc_id` with `re.escape` and the known table names, picking the longest matching `doc_id`. Complexity O(rows x docs), bounded by `max_rows` and `limit`. Entity rows with no vector-matched document keep `document_id` absent.

### D10. Entity ACL limitation
Rows are not filtered in release 1. `sql_not_acl_filtered` warning and `retrieval.sql.enabled` switch. Follow-up: post-filter rows by `document_id` against documents the user may read.

### D11. Job queue
In-process `ThreadPoolExecutor` plus dict guarded by a lock; records `owner`, `status`, `result_or_error`, `created_at`. A reaper removes expired jobs lazily on submit and poll. `JobQueuePort` allows an external store later. Failures store an `ErrorCode` and a generic message only.

### D12. Cache
`CachePort` with in-memory TTL LRU default. Key = SHA-256 of canonical JSON of `(user, normalized query, target, search_config, inference_config)`. Redis adapter loads only if the extra is installed and configured.

### D13. Configuration
Pydantic model `RetrievalConfig` read from `retrieval:` in `docling-pipelines-config.yaml` (via `DOCPIPE_CONFIG_PATH`) with env overrides (`DOCPIPE_RETRIEVAL_*`). Per-provider connection blocks: `retrieval.vector.milvus` (uri, token via `${VAR}`), `retrieval.vector.opensearch` (hosts, auth), `retrieval.sql.postgres`. Secrets are `SecretStr` and resolved through the existing secret resolver. Services bind per AGENTS/security rules (`127.0.0.1` default is the app's concern; this change adds no listener).

### D14. Error codes
Add `RETRIEVAL_DISABLED` (503), `RETRIEVAL_QUEUE_FULL` (503), `RETRIEVAL_INVALID_REQUEST` (400), `RETRIEVAL_UPSTREAM_FAILED` (502), `RETRIEVAL_JOB_NOT_FOUND` (404), `RETRIEVAL_AGENT_DISABLED` (501), `RETRIEVAL_SQL_REJECTED` (internal). Mapped through existing `DocpipeException` handling.

### D15. Auth
`Depends(get_current_user)` on all routes, swapped for `require_role("viewer")` once `add-authn-authz` lands. Job and event ownership by `User.username`.

### D16. Evaluate
Deterministic metrics only (precision@k, recall@k) by default; LLM judge is opt-in.

## Risks and trade-offs

| Risk | Mitigation |
|---|---|
| LLM-generated SQL escapes sandbox | `validate_and_authorize` + engine hardening + read-only roles; tests with an adversarial SQL corpus (CTE shadowing, table functions, catalogs, stacked statements) |
| Raw driver text leaks DSN/host/path via correction prompt or logs | Diagnostics built at the adapter boundary, exception chain cut, secret-fuzz tests |
| Running statement outlives an abandoned wait | Per-statement cancel handle (DuckDB `interrupt`, Postgres `cancel`), server-side limits, outcome logged |
| Entity rows leak restricted documents | Documented; `retrieval.sql.enabled` switch; warning in responses; follow-up change |
| Postgres creds with write rights used for reads | Dedicated read-only role config; startup warning on fallback |
| DuckDB file locked by pipeline | `store_busy` partial result; documented |
| Thread timeout leaves running work | Cancel handle + engine limits (see D8a); bounded pool; queue limit |
| In-process jobs lost on restart / multi-worker | Documented single-process limit; port for later store |
| Embedding mismatch gives garbage ranking | Hard skip with explicit reason |
| Prompt injection via chunk text | Delimited untrusted context, no tool use in this change, summary is advisory, text never reaches SQL generation (only the user query and schema do) |
| Derivative lacks `id_field` | Correlation silently absent for that store; documented in warnings |
| Cache cross-user leakage | User in key; tests |
| Cost/latency of rerank model | Lazy load, optional, bounded pool |
| Scope creep from retrieval-v2 stubs | Unsupported providers skipped with `unsupported_provider`, not stubbed |

## Migration / rollout

Feature flag `retrieval.enabled` default false. Order: derivatives change first, then this change; no data migration. Rollback: set flag false.

## Open questions

None blocking. Assumptions: D8a deadline floor and cancel semantics, D2 threads, D5 client-side RRF for OpenSearch, D13 config shape, D9 longest-match correlation.
