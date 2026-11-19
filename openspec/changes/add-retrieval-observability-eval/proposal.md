# Proposal: Retrieval Observability & Offline Evaluation (Phase 3)

## Why

Operators running the native Docling Pipelines retrieval service need visibility into query latency, store dispatch outcomes, cache hit rates, and answer quality — and dashboards built for `retrieval-v2` expect standard Prometheus, event-timeline, cache-stats, and offline evaluation endpoints under `/v2/retrieval/*`.

This change adds the `retrieval-v2`-compatible observability and optional RAGAS evaluation endpoints to Docling Pipelines while keeping heavy evaluation dependencies (`ragas`) strictly optional.

**Layer:** `backend-only`. Adds observability modules under `src/docpipe/core/retrieval/observability/`, evaluation service under `src/docpipe/core/retrieval/application/eval_service.py`, and REST routes under `/v2/retrieval/{events,metrics,evaluate}/*`. No frontend changes are included.

## What Changes

- **Prometheus metrics (`/v2/retrieval/metrics`, unauthenticated)**: Exposes `http_requests_total`, `http_request_duration_seconds`, `llm_inference_requests_total`, `llm_inference_duration_seconds`, `sql_query_requests_total`, `sql_query_duration_seconds`, and `vector_query_requests_total`.
- **Per-request event store**: Bounded in-memory event store (`max_event_store_size`, default 50 requests) recording timestamped lifecycle events (`START`, `FETCH_DOCUMENT_LIBRARY`, `ACL_CHECK`, `SQL_SEARCH`, `VECTOR_SEARCH`, `SYNTHESIZE`, `COMPLETE`), exposed via:
  - `GET /v2/retrieval/events/{request_id}`
  - `GET /v2/retrieval/metrics/{request_id}`
- **Cache statistics**: `GET /v2/retrieval/metrics/cachestats` returning hit count, miss count, and current cache size.
- **OpenTelemetry tracing**: Reuses `docling-pipelines`'s existing `[telemetry]` extra; when `OTLP_ENDPOINT` is set, emits spans for retrieval requests and store calls.
- **Optional RAGAS evaluation**:
  - `POST /v2/retrieval/evaluate/offline` for offline evaluation of `(query, contexts, answer)` triples (returns `501 Not Implemented` when the optional `retrieval-eval` extra is not installed).
  - Enables `evaluate: true` on `QueryRequest` to populate `additional_info.eval` when `ragas` is installed.
- **Dependencies**: Adds pinned `prometheus-client` to `[project.dependencies]` (or optional `[retrieval-observability]`) and optional `retrieval-eval = ["ragas==..."]` extra in `pyproject.toml`, regenerating `uv.lock`.

## Capabilities

### New Capabilities
- `backend/retrieval-observability`: Prometheus scrape endpoint, HTTP/LLM/SQL/vector metrics, per-request event timeline and count endpoints, cache statistics endpoint, OTLP tracing, and optional offline/inline RAGAS evaluation.

## Non-goals

- IBM Instana integration (`ENABLE_INSTANA`) or persistent external event stores (in-memory ring buffer only).
- Bundling `ragas` as a required core dependency.
- Frontend dashboards or Grafana JSON provisioning.

## Impact

- **REST routes**: Adds `/v2/retrieval/metrics`, `/v2/retrieval/metrics/cachestats`, `/v2/retrieval/metrics/{request_id}`, `/v2/retrieval/events/{request_id}`, and `/v2/retrieval/evaluate/offline` to `src/docpipe/api/routes/retrieval.py`.
- **Core modules**: Adds `src/docpipe/core/retrieval/observability/` (`events.py`, `metrics.py`, `tracing.py`) and `src/docpipe/core/retrieval/application/eval_service.py`.
- **Dependencies**: Updates `pyproject.toml` and `uv.lock`.
- **Tests**: Unit tests in `tests/unit/core/retrieval/test_observability.py` and `tests/unit/api/routes/test_retrieval_observability.py`.
