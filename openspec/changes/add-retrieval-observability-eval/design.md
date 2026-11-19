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
    │   ├── metrics.py                        # Prometheus counters & histograms (dedicated CollectorRegistry optional)
    │   └── tracing.py                        # Lazy OTel tracer wrapper (no-op if opentelemetry or OTLP_ENDPOINT absent)
    └── application/
        └── eval_service.py                   # Optional RAGAS faithfulness/relevancy/precision scorer (lazy import)
```

## 2. Key Decisions

- **D1. Route ordering for `/v2/retrieval/metrics/cachestats`**: Register `/v2/retrieval/metrics/cachestats` *before* `/v2/retrieval/metrics/{request_id}` in FastAPI so `"cachestats"` is never captured as a `request_id` path parameter.
- **D2. Bounded event store**: `MemoryEventStore` retains at most `max_event_store_size` (default 50) recent `request_id` timelines in an `OrderedDict`, evicting the oldest entry on overflow. Events never store raw user queries, SQL text, or document content — only event names, timestamps, durations, and safe metadata counts.
- **D3. Lazy optional extras**: `EvalService` imports `ragas` lazily inside the evaluation call. When `ragas` is not installed, `POST /v2/retrieval/evaluate/offline` returns `501 Not Implemented` with an actionable message, and inline `evaluate: true` logs a warning and leaves `additional_info.eval = None`.
- **D4. OTel reuse**: `tracing.py` checks for `opentelemetry` (already in `docling-pipelines`'s `[telemetry]` extra) and `OTLP_ENDPOINT`; when absent, uses a zero-overhead no-op context manager.

## 3. Risk Mitigations

| Risk | Mitigation |
|---|---|
| High-cardinality Prometheus labels (`request_id`, `query_id`) | Normalize route templates (`/v2/retrieval/search/result/{query_id}`) for `path` labels; never put IDs in Prometheus labels. |
| Memory growth in event store | Strict bounded `OrderedDict` with `max_event_store_size` eviction. |
| Duplicate Prometheus collector registration during pytest reloads | Support an injectable `CollectorRegistry` in `metrics.py` for clean test isolation. |
