# backend/retrieval-observability Specification

## Purpose

Defines the externally observable telemetry and evaluation contract for Docling Pipelines' retrieval service, compatible with `retrieval-v2`'s observability and offline evaluation endpoints.

## ADDED Requirements

### Requirement: Prometheus metrics endpoint
The service SHALL expose `GET /v2/retrieval/metrics` as a Prometheus text-format endpoint served from a dedicated `CollectorRegistry` (never the process-global default). It SHALL require `get_current_user` unless `retrieval.observability.metrics_public` is true (default `false`). Metric names SHALL use the `docpipe_retrieval_` prefix and cover HTTP, LLM, SQL, and vector calls.

#### Scenario: Metric families are exposed
- **WHEN** retrieval requests have exercised HTTP, LLM, SQL, and vector paths
- **THEN** the scrape output contains `docpipe_retrieval_http_requests_total`, `docpipe_retrieval_http_request_duration_seconds`, `docpipe_retrieval_llm_inference_requests_total`, `docpipe_retrieval_llm_inference_duration_seconds`, `docpipe_retrieval_sql_query_requests_total`, `docpipe_retrieval_sql_query_duration_seconds`, and `docpipe_retrieval_vector_query_requests_total`

#### Scenario: Labels are low-cardinality and identifier-free
- **WHEN** metrics are scraped
- **THEN** labels contain only route templates, store types, and outcome codes, and never `request_id`, `query_id`, user, library, or document identifiers

#### Scenario: Metrics endpoint returns Prometheus text
- **WHEN** an authenticated scrape client sends `GET /v2/retrieval/metrics`
- **THEN** the response is `200 OK` in Prometheus text exposition format containing `docpipe_retrieval_http_requests_total` and `docpipe_retrieval_http_request_duration_seconds`

#### Scenario: Metrics endpoint requires authentication by default
- **WHEN** an unauthenticated client sends `GET /v2/retrieval/metrics` and `retrieval.observability.metrics_public` is false
- **THEN** the service returns `401 Unauthorized`

#### Scenario: Metrics endpoint can be made public explicitly
- **WHEN** `retrieval.observability.metrics_public` is true and an unauthenticated client sends `GET /v2/retrieval/metrics`
- **THEN** the service returns `200 OK` with the same low-cardinality, identifier-free metrics

### Requirement: Per-request event timeline and count endpoints
The service SHALL record timestamped lifecycle events per `request_id` in a bounded in-memory store together with the authenticated owner of the request, and expose `GET /v2/retrieval/events/{request_id}` and `GET /v2/retrieval/metrics/{request_id}`. Both endpoints SHALL require `get_current_user` and SHALL only return data for requests owned by the caller.

#### Scenario: Event timeline includes standard lifecycle events
- **WHEN** a search request completes
- **THEN** `GET /v2/retrieval/events/{request_id}` returns `200 OK` with events including `START`, `FETCH_DOCUMENT_LIBRARY`, `ACL_CHECK`, any dispatched `SQL_SEARCH` / `VECTOR_SEARCH`, and `COMPLETE`

#### Scenario: Event count matches timeline length
- **WHEN** a completed request recorded N events
- **THEN** `GET /v2/retrieval/metrics/{request_id}` returns `200 OK` with count N

#### Scenario: Unknown request_id returns 404
- **WHEN** `GET /v2/retrieval/events/{unknown_id}` or `GET /v2/retrieval/metrics/{unknown_id}` is called
- **THEN** the service returns `404 Not Found`

#### Scenario: Request owned by another user returns 404
- **WHEN** an authenticated user calls `GET /v2/retrieval/events/{request_id}` or `GET /v2/retrieval/metrics/{request_id}` for a request recorded for a different user
- **THEN** the service returns `404 Not Found` and discloses no event data

#### Scenario: Unauthenticated event access is rejected
- **WHEN** a client calls `GET /v2/retrieval/events/{request_id}` or `GET /v2/retrieval/metrics/{request_id}` without a valid bearer token
- **THEN** the service returns `401 Unauthorized`

### Requirement: Cache statistics endpoint
The service SHALL expose `GET /v2/retrieval/metrics/cachestats` returning cache hit count, miss count, and current size. The endpoint SHALL require `get_current_user`.

#### Scenario: Cache stats returned
- **WHEN** an authenticated client requests `GET /v2/retrieval/metrics/cachestats`
- **THEN** the response is `200 OK` containing `hits`, `misses`, and `size`

#### Scenario: Unauthenticated cache stats rejected
- **WHEN** an unauthenticated client requests `GET /v2/retrieval/metrics/cachestats`
- **THEN** the service returns `401 Unauthorized`

### Requirement: OpenTelemetry trace export via the existing telemetry service
The service SHALL emit spans for retrieval requests and store calls only through the existing `TelemetryService`, governed by the existing `TELEMETRY_ENABLED` and `OTEL_EXPORTER_OTLP_ENDPOINT` variables. No retrieval-specific OTLP variable SHALL be introduced, and tracing SHALL be a no-op when telemetry is disabled or the extra is missing.

#### Scenario: No-op tracing when telemetry is disabled
- **WHEN** `TELEMETRY_ENABLED` is unset or false
- **THEN** no OTLP exporter is initialized by retrieval code and retrieval requests complete normally

#### Scenario: Spans emitted through the shared telemetry service
- **WHEN** `TELEMETRY_ENABLED=true`, the `telemetry` extra is installed, and `OTEL_EXPORTER_OTLP_ENDPOINT` is set
- **THEN** retrieval request and store-call spans are created via `TelemetryService.span(...)` and exported with the application's existing exporter configuration

### Requirement: Optional offline RAGAS evaluation endpoint
The service SHALL expose `POST /v2/retrieval/evaluate/offline` to score `(query, contexts, answer)` inputs when the optional `retrieval-eval` extra (`ragas`) is installed, and SHALL return `501 Not Implemented` when `ragas` is unavailable. The endpoint SHALL require `get_current_user`.

#### Scenario: Offline eval returns 501 when ragas is not installed
- **WHEN** `POST /v2/retrieval/evaluate/offline` is called without `ragas` installed
- **THEN** the service returns `501 Not Implemented`

#### Scenario: Offline eval returns scores when ragas is available
- **WHEN** `POST /v2/retrieval/evaluate/offline` is called with valid inputs and `ragas` configured
- **THEN** the service returns `200 OK` with faithfulness, answer relevancy, and context precision scores
