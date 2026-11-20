# Design: Retrieval Observability & Offline Evaluation (Phase 3)

## 1. Module Placement (DDD)

```text
src/docpipe/
├── api/
│   ├── dto/retrieval_dto.py                  # Add EventTimelineResponse, CacheStatsResponse, OfflineEvalRequest/Response
│   └── routes/retrieval.py                   # Add /v2/retrieval/{metrics,events,evaluate}/* routes
└── core/retrieval/
    ├── observability/
    │   ├── events.py                         # MemoryEventStore (bounded FIFO/LRU by request_id)
    │   ├── metrics.py                        # Prometheus counters & histograms (always a dedicated CollectorRegistry, docpipe_retrieval_ prefix)
    │   └── tracing.py                        # Thin delegate to the existing TelemetryService (no-op when telemetry disabled)
    └── application/
        └── eval_service.py                   # Optional RAGAS faithfulness/relevancy/precision scorer (lazy import)
```

## 2. Key Decisions

- **D1. Route ordering for `/v2/retrieval/metrics/cachestats`**: Register `/v2/retrieval/metrics/cachestats` *before* `/v2/retrieval/metrics/{request_id}` in FastAPI so `"cachestats"` is never captured as a `request_id` path parameter.
- **D2. Bounded, owner-scoped event store**: `MemoryEventStore` retains at most `max_event_store_size` (default 50) recent `request_id` timelines in an `OrderedDict`, evicting the oldest entry on overflow. Each timeline records the authenticated owner username; `GET /v2/retrieval/events/{request_id}` and `GET /v2/retrieval/metrics/{request_id}` require `get_current_user` and return `404` when the caller is not the owner, mirroring the async `query_id` ownership rule. Events never store raw user queries, SQL text, or document content — only event names, timestamps, durations, and safe metadata counts.
- **D3. Lazy optional extras**: `EvalService` imports `ragas` lazily inside the evaluation call. When `ragas` is not installed, `POST /v2/retrieval/evaluate/offline` returns `501 Not Implemented` with an actionable message, and inline `evaluate: true` logs a warning and leaves `additional_info.eval = None`.
- **D4. Reuse the existing `TelemetryService`**: [`telemetry_service.py`](../../../src/docpipe/utils/infrastructure/telemetry_service.py) already owns OTLP trace and metric export, gated by `TELEMETRY_ENABLED` and configured by the standard `OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_*` variables. `tracing.py` is a thin delegate over `get_telemetry_service().span(...)`; it creates no tracer provider or exporter and introduces no retrieval-specific endpoint variable. When telemetry is disabled the delegate is a no-op.
- **D5. Prometheus alongside OTel metrics**: Prometheus exposition is kept only because `GET /v2/retrieval/metrics` is part of the `retrieval-v2` surface. A single `RetrievalMetrics` facade records each measurement to the dedicated Prometheus registry and, when `TelemetryService.metrics_enabled` is true, to the OTel meter, so call sites are instrumented once. Metric names carry the `docpipe_retrieval_` prefix (departing from `retrieval-v2`'s unprefixed names) and the dedicated registry never shares the default process registry, preventing collisions with other collectors.
- **D6. Authentication**: `/v2/retrieval/metrics` requires `get_current_user` by default and is unauthenticated only when `retrieval.observability.metrics_public: true`. `/v2/retrieval/metrics/cachestats`, the per-request endpoints, and `/v2/retrieval/evaluate/offline` always require authentication. Register `cachestats` before `{request_id}` (D1) while keeping the same dependency on both routes.

## 3. Risk Mitigations

| Risk | Mitigation |
|---|---|
| High-cardinality Prometheus labels (`request_id`, `query_id`) | Normalize route templates (`/v2/retrieval/search/result/{query_id}`) for `path` labels; never put IDs in Prometheus labels. |
| Memory growth in event store | Strict bounded `OrderedDict` with `max_event_store_size` eviction. |
| Duplicate Prometheus collector registration during pytest reloads | Support an injectable `CollectorRegistry` in `metrics.py` for clean test isolation. |
| Cross-user disclosure through event timelines or unauthenticated scraping | Owner-scoped event store with `404` on mismatch, mandatory authentication on all non-metrics observability routes, and authentication on `/v2/retrieval/metrics` unless `metrics_public` is explicitly enabled. |
| Two parallel telemetry pipelines (Prometheus and OTel) drifting apart | Single `RetrievalMetrics` facade feeds both; tracing delegates to the existing `TelemetryService`. |
