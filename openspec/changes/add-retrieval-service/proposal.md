# Proposal

## Why

docpipe can ingest, chunk, embed, and store documents, and it records where the derived data lives (`add-document-library-derivatives`). It cannot answer a question over that data. Users must query OpenSearch or Milvus by hand and cannot combine semantic search over chunks with structured queries over extracted entities.

A reference implementation exists in `.bob/tmp/retrieval-v2/` (the local copy is `main`; the SQL safety behavior below follows the stacked PRs jjojo/retrieval-v2 #30, #32 and #33, branch `HarshadNehate/tool-mode-round2`): a standalone service with hybrid dense + BM25 search, RRF, reranking, text-to-SQL with validation and retry, an async job queue, an event store, and an optional agent. It is a separate project with its own config, auth, models, and stubs (OpenSearch and pgvector backends are stubs, the SQL prompt is Presto-only). This change brings its working behavior into docpipe under docpipe's architecture, instead of running a second service.

**Layer:** backend-only. No frontend, routing, BFF, or Redux changes.

**Affected REST routes (all under `/api/v1`, DTOs only):**
- `POST /retrieval/search`
- `POST /retrieval/search-jobs`, `GET /retrieval/search-jobs/{query_id}`
- `GET /retrieval/events/{request_id}`
- `POST /retrieval/evaluate`

**Affected operators:** none. Retrieval reads data written by `vectordb`, `embeddings`, and `entity_store_operator`.
**Affected storage adapters:** new read-only retrieval adapters for Milvus, OpenSearch, DuckDB, and Postgres. Existing write adapters are untouched.

## What Changes

- **Retrieval domain and ports.** `RetrievalQuery`, `RetrievalResult`, `ResultItem`, and ports `VectorRetrieverPort`, `SqlEnginePort`, `RerankerPort`, `CachePort`, `JobQueuePort`, `EventStorePort`, `TextToSqlPort`, `SummarizerPort`. The LLM and embedding ports reuse `LLMInferencePort` and `LLMEmbeddingPort`.
- **Search orchestration.** For a `document_library_id` (or a single `asset_id` document set), resolve derivatives through `DerivativeResolverPort`, query every vector store and entity table concurrently, and return one `ResultItem` per store. Vector and SQL results are not fused. A store failure yields `status: "partial"` with the remaining results.
- **Vector retrievers.** Milvus hybrid dense + BM25 with RRF; OpenSearch hybrid (kNN + BM25) with RRF. A rerank candidate pool larger than `limit`, then truncation to `limit`. ACL filter on `allowed_users` using the same fail-closed rule as `ACLQueryBuilder`.
- **SQL path.** Text-to-SQL over the derivative's entity tables on DuckDB and Postgres: generate, validate and authorize every statement with one scope-aware function (CTE shadowing, table functions and catalogs refused), execute with limits through a hardened `SqlEnginePort`, and correct at most `MAX_SQL_RETRIES` times using safe diagnostics only (no raw driver text). Non-repairable failures (connection, authorization, timeout, cancelled) are not sent for correction. The request deadline reaches every statement as a server-side limit, and abandoning a wait cancels the running statement (DuckDB `interrupt`, Postgres `cancel`). A zero-row success is a result, not a failure. Entity rows are correlated with chunks on `id` using an anchored match performed in Python. `retrieval.sql.enabled` switches the SQL path off.
- **Request model.** `search_inference_config.model_id` applies to SQL generation, correction and summary.
- **Sync and async search.** Sync returns the result. Async returns `202` with `query_id`; polling returns 202 while pending, 200 when done, 404 unknown, and the stored error mapping when failed. In-process job queue with TTL and a capacity limit (503 when full).
- **Optional LLM summary** (`generated_text`) with a prompt that treats chunk text as ground truth and SQL rows as a secondary index.
- **Event store, cache, evaluate.** Per-request event trail; optional cache (in-memory default, Redis through optional extra); an evaluation endpoint comparing retrieved items to expected answers.
- **Agent (opt-in, outline only here).** Agent routes are registered but return 501 unless `AGENT_ENABLED=true` and an LLM is configured. The implementation of the agent is out of this change (see `add-retrieval-agent`).
- **Configuration** under `retrieval.*` in `docling-pipelines-config.yaml` and env overrides, including per-provider endpoints and credentials the service itself uses.
- **Auth.** Routes depend on `get_current_user` and viewer-level access under `add-authn-authz`.
- **Observability.** `get_logger()` with `%s` logging, OpenTelemetry spans using the dependencies already present, no queries or row data in logs by default.

No **BREAKING** changes. The feature is disabled until `retrieval.enabled` is true; when disabled the routes return 503 with code `retrieval_disabled`.

## Capabilities

### New Capabilities

- `backend/retrieval-api`: REST contract for sync/async search, polling, events, evaluate, request and response shapes, validation, error mapping, and auth.
- `backend/retrieval-engine`: orchestration across stores, vector hybrid search, reranking, ACL filtering, correlation on `id`, summary, job queue, cache, events, configuration, and partial-failure semantics.
- `backend/retrieval-sql`: security and execution contract for generated SQL: single read-only `SELECT`, table allowlist, engine hardening for DuckDB and Postgres, limits, retry, and logging rules.

### Modified Capabilities

None. `backend/document-libraries-api` and `backend/flow-execution-engine` changes live in `add-document-library-derivatives`, which this change depends on.

## Dependencies on other changes

- Requires `add-document-library-derivatives` (derivative records and `DerivativeResolverPort`).
- Uses `add-authn-authz` for `require_role`; falls back to `get_current_user` while that change is unmerged.

## Non-goals

- No UDP-compatible routes, `/udp/v1` prefix, contract fixtures, `attachments`, or `data_card` fields.
- `container_id` and `container_type` are accepted and ignored.
- No agent implementation (plan mode, native tool mode, thinking arm, the eight agent tools, direct-SQL `query_table`, budgets, step trace, agent queue), planner/DAG, citations, JSON-validated LLM steps, or document-class context for text-to-SQL. These belong to `add-retrieval-agent` and a later SOTA change.
- No port of the retrieval-v2 value-substitution helper; its backslash quote escaping (`\'`) is wrong for Presto and ANSI SQL and the engine here uses validated statements, not substituted text.
- No Presto/Iceberg or other SQL engine beyond DuckDB and Postgres (`add-retrieval-sql-engines`), though `SqlEnginePort` is designed for it.
- No ACL filtering of entity-table rows in the first release (documented limitation; use `retrieval.sql.enabled=false` for libraries with restricted documents).
- No new write paths, no change to `EntityStoreOperator` output, no `document_id` column.
- No multi-worker job queue or distributed job store; single-process only.
- No port of `python-jose`, `structlog`, `presto-python-client`, or CAMS integrations from retrieval-v2.
- No frontend search UI.

## Impact

- New: `src/docpipe/core/retrieval/{domain,application,adapters}/`, `src/docpipe/api/routes/retrieval.py`, `src/docpipe/api/dto/retrieval_dto.py` and mapper, config model, error codes.
- Changed: `api_router.py`, `dependencies.py`, `error_codes.py`, `docling-pipelines-config.yaml` schema/docs.
- Dependencies: none required (all of `pymilvus`, `opensearch-py`, `duckdb`, `psycopg2-binary`, `sqlglot`, `sentence-transformers` are present). `redis` and `prometheus-client` are optional extras; any `pyproject.toml` change is followed by `uv lock` and `uv pip install -e ".[dev]"`.
- Docs: new `docs/guides/RETRIEVAL_GUIDE.md`, config reference entry.
