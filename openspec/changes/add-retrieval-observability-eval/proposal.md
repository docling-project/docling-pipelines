# Proposal: Retrieval Observability & Offline Evaluation (Phase 3)

## Why

Operators running the native Docling Pipelines retrieval service need visibility into query latency, store dispatch outcomes, cache hit rates, and answer quality — and dashboards built for `retrieval-v2` expect standard Prometheus, event-timeline, cache-stats, and offline evaluation endpoints under `/v2/retrieval/*`.

This change adds the `retrieval-v2`-compatible observability and optional RAGAS evaluation endpoints to Docling Pipelines while keeping heavy evaluation dependencies (`ragas`) strictly optional.

**Layer:** `backend-only`. Adds observability modules under `src/docpipe/core/retrieval/observability/`, evaluation service under `src/docpipe/core/retrieval/application/eval_service.py`, and REST routes under `/v2/retrieval/{events,metrics,evaluate}/*`. No frontend changes are included.

## What Changes

- **Prometheus metrics (`/v2/retrieval/metrics`, authenticated by default; `retrieval.observability.metrics_public: true` opts in to unauthenticated scraping)**: Served from a dedicated `CollectorRegistry`, with a `docpipe_retrieval_` name prefix and low-cardinality, identifier-free labels. The prefix intentionally departs from the unprefixed `retrieval-v2` metric names to avoid collisions with other collectors; existing `retrieval-v2` dashboards need a metric rename or relabel rule. Exposes `docpipe_retrieval_http_requests_total`, `docpipe_retrieval_http_request_duration_seconds`, `docpipe_retrieval_llm_inference_requests_total`, `docpipe_retrieval_llm_inference_duration_seconds`, `docpipe_retrieval_sql_query_requests_total`, `docpipe_retrieval_sql_query_duration_seconds`, and `docpipe_retrieval_vector_query_requests_total`.
- **Per-request event store**: Bounded in-memory, owner-scoped event store (`max_event_store_size`, default 50 requests; endpoints require authentication and return `404` for another user's `request_id`) recording timestamped lifecycle events (`START`, `FETCH_DOCUMENT_LIBRARY`, `ACL_CHECK`, `SQL_SEARCH`, `VECTOR_SEARCH`, `SYNTHESIZE`, `COMPLETE`), exposed via:
  - `GET /v2/retrieval/events/{request_id}`
  - `GET /v2/retrieval/metrics/{request_id}`
- **Cache statistics**: authenticated `GET /v2/retrieval/metrics/cachestats` returning hit count, miss count, and current cache size.
- **OpenTelemetry tracing**: Reuses the existing `TelemetryService` (`get_telemetry_service()`), the `[telemetry]` extra, and the existing `TELEMETRY_ENABLED` / `OTEL_EXPORTER_OTLP_ENDPOINT` variables. No new OTLP endpoint variable is introduced; retrieval spans and store-call spans go through `TelemetryService.span(...)`.
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
