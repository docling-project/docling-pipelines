# Tasks

Depends on `add-document-library-derivatives` (tasks 1-4 merged) for `DerivativeResolverPort`.

## 1. Foundations

- [ ] 1.1 [backend] Add `RetrievalConfig` Pydantic model and loader (`retrieval.*`, env overrides, `SecretStr`), default `enabled: false`
- [ ] 1.2 [backend] Add retrieval `ErrorCode` entries and exception classes with status codes (D14)
- [ ] 1.3 [backend] Add domain models in `core/retrieval/domain/models/`
- [ ] 1.4 [backend] Add port ABCs in `core/retrieval/domain/ports/` and reason-code constants
- [ ] 1.5 [backend] Unit tests for config parsing, defaults, and secret redaction in `repr`

## 2. Pure algorithms

- [ ] 2.1 [backend] Implement `reciprocal_rank_fusion(*, rankings, k)` and tests (ties, empty lists, single list)
- [ ] 2.2 [backend] Implement `IdCorrelator` (escaped, longest-match, list-item suffix) and tests incl. prefix collision and metacharacter ids
- [ ] 2.3 [backend] Implement `validate_and_authorize` with sqlglot: single SELECT, scope walk of physical relations, CTE shadowing, plain tables only, catalogs/table functions refused, name resolution against session schema, dialect-aware identifier case, id rule, for `duckdb` and `postgres`
- [ ] 2.4 [backend] Adversarial SQL corpus tests (stacked statements, comments, quoting tricks, CTE named like a table, `read_csv`, `pg_read_file`, catalogs, subquery tables, four-part names, wrong schema, identifier case)
- [ ] 2.5 [backend] Define `EngineCapabilities`, `CancelHandle`, `CancelOutcome`, diagnostic kinds and `timeout_milliseconds` (floor 1 ms) in the domain/ports; unit tests for the handle (bind, release, cancel before start, already finished)

## 3. SQL engines

- [ ] 3.1 [backend] Implement `DuckDbSqlEngine`: read-only open per query, `SET enable_external_access=false`, `SET lock_configuration=true`, row cap, `Timer` + `interrupt()` for timeout and cancel, `store_busy` mapping, diagnostics with no chained raw exception
- [ ] 3.2 [backend] Tests with a temp DuckDB file: blocked `read_text`/`COPY`/`ATTACH`/reconfigure, busy lock
- [ ] 3.3 [backend] Implement `PostgresSqlEngine`: separate connection config, read-only session, transaction-local `statement_timeout`, `search_path`, `connection.cancel()` bound to the handle, rollback, connection closed on every path, SQLSTATE-to-kind mapping without chaining the raw exception, startup warning on fallback creds
- [ ] 3.4 [backend] Postgres tests with fakes/mocks (and Docker-gated integration test, manual-only)
- [ ] 3.5 [backend] Implement `TextToSqlPort` adapter on `LLMInferencePort`: prompt builder (allowed tables only, id rule, delimited question), correction prompt from safe diagnostic plus real column names, request `model_id`
- [ ] 3.6 [backend] Implement `SqlSearchStep` (generate, validate+authorize, execute, correct only repairable kinds, no correction after last attempt, no engine or correction call after deadline, hash-only logging, zero rows kept as an item)
- [ ] 3.7 [backend] Tests: secret fuzzing across prompt/log/error/traceback, real DuckDB interrupt test (`timeout` and cancel), Postgres cancel with mocks, deadline floor, deadline-passed makes no calls, authorization failure makes no correction call, concurrent statements cancel independently

## 4. Vector retrieval

- [ ] 4.1 [backend] Implement `MilvusRetriever` (dense + BM25 + RRFRanker, mapping-driven fields, ACL expression escaped)
- [ ] 4.2 [backend] Implement `OpenSearchRetriever` (kNN + match, client-side RRF, ACL filter as JSON value)
- [ ] 4.3 [backend] Implement reranker adapters (noop, sentence-transformers lazy)
- [ ] 4.4 [backend] Implement query embedding with adapter cache and model/dimension compatibility check
- [ ] 4.5 [backend] Implement `VectorSearchStep` (embed, check, retrieve, fuse, rerank pool, truncate)
- [ ] 4.6 [backend] Tests with fake clients: dense-only, hybrid, pool size, ACL, mismatch skip, unknown model with equal dimension warns, collection metric read, rerank failure fallback, store auth failure reported as `authorization_error`, unsupported provider

## 5. Orchestration

- [ ] 5.1 [backend] Implement `StorePlanner` (derivatives to store tasks, skip reasons)
- [ ] 5.2 [backend] Implement `SearchService` (thread pool, per-store timeout, partial/error status, correlation, warnings)
- [ ] 5.3 [backend] Implement `Summarizer` (delimited context, failure handling) and `generated_text`
- [ ] 5.4 [backend] Implement in-memory cache adapter and cache keying with user identity
- [ ] 5.5 [backend] Implement in-process job queue (TTL, capacity, owner) and `SearchJobService`
- [ ] 5.6 [backend] Implement in-memory event store and stage recording without content
- [ ] 5.7 [backend] Implement `Evaluator` (precision/recall at k)
- [ ] 5.8 [backend] Implement `retrieval_factory.py` wiring and disabled-mode behavior
- [ ] 5.9 [backend] Tests: `model_id` reaches SQL generation, correction and summary; unsupported model returns 400; zero-row SQL item; partial results, timeout, all-stores-fail, cache hit and per-user isolation, job TTL and capacity, owner 404, event content absence

## 6. REST layer

- [ ] 6.1 [backend] Add DTOs and mapper (`retrieval_dto.py`, `retrieval_mapper.py`) with validation bounds
- [ ] 6.2 [backend] Add routes `search`, `search-jobs` (submit/poll), `events/{request_id}`, `evaluate`, agent routes returning 501
- [ ] 6.3 [backend] Register router in `api_router.py`, DI providers in `dependencies.py`, feature gate dependency (503 `retrieval_disabled`)
- [ ] 6.4 [backend] API tests: validation (target xor, bounds), 200/202/404/503, generic errors, `include_sql` behavior, container params ignored, 401 when auth enabled

## 7. Logging and observability

- [ ] 7.1 [backend] Add stage spans (OpenTelemetry) and structured `%s` logs with request id and counts only
- [ ] 7.2 [backend] Test that logs at INFO contain no query, SQL, rows, or credentials (caplog assertions)

## 8. Optional extras

- [ ] 8.1 [backend] Redis cache adapter behind an optional extra; if `pyproject.toml` changes, run `uv lock` and `uv pip install -e ".[dev]"` and commit both files

## 9. Docs

- [ ] 9.1 [backend] Write `docs/guides/RETRIEVAL_GUIDE.md` (config, routes, limitations: entity ACL, single-process jobs, DuckDB lock, in-memory entity stores, table-level authorization only, server-side limits verified per engine)
- [ ] 9.2 [backend] Document `retrieval.*` keys in the config reference and the read-only Postgres role setup

## 10. Validation

- [ ] 10.1 [backend] `uv run ruff check --fix .`
- [ ] 10.2 [backend] `uv run mypy .`
- [ ] 10.3 [backend] `uv run pytest tests/unit -m "unit and not integration"`
- [ ] 10.4 [backend] `openspec validate add-retrieval-service --strict`
