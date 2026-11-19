# backend/retrieval-observability Specification

## Purpose

Defines the externally observable telemetry and evaluation contract for Docling Pipelines' retrieval service, compatible with `retrieval-v2`'s observability and offline evaluation endpoints.

## ADDED Requirements

### Requirement: Prometheus metrics endpoint
The service SHALL expose `GET /v2/retrieval/metrics` as a Prometheus text-format scrape endpoint without authentication, emitting HTTP (`http_requests_total`, `http_request_duration_seconds`), LLM (`llm_inference_requests_total`, `llm_inference_duration_seconds`), SQL (`sql_query_requests_total`, `sql_query_duration_seconds`), and vector (`vector_query_requests_total`) metrics.

#### Scenario: Metrics endpoint returns Prometheus text
- **WHEN** a scrape client sends `GET /v2/retrieval/metrics`
- **THEN** the response is `200 OK` in Prometheus text exposition format containing `http_requests_total` and `http_request_duration_seconds`

### Requirement: Per-request event timeline and count endpoints
The service SHALL record timestamped lifecycle events per `request_id` in a bounded in-memory store and expose `GET /v2/retrieval/events/{request_id}` and `GET /v2/retrieval/metrics/{request_id}`.

#### Scenario: Event timeline includes standard lifecycle events
- **WHEN** a search request completes
- **THEN** `GET /v2/retrieval/events/{request_id}` returns `200 OK` with events including `START`, `FETCH_DOCUMENT_LIBRARY`, `ACL_CHECK`, any dispatched `SQL_SEARCH` / `VECTOR_SEARCH`, and `COMPLETE`

#### Scenario: Event count matches timeline length
- **WHEN** a completed request recorded N events
- **THEN** `GET /v2/retrieval/metrics/{request_id}` returns `200 OK` with count N

#### Scenario: Unknown request_id returns 404
- **WHEN** `GET /v2/retrieval/events/{unknown_id}` or `GET /v2/retrieval/metrics/{unknown_id}` is called
- **THEN** the service returns `404 Not Found`

### Requirement: Cache statistics endpoint
The service SHALL expose `GET /v2/retrieval/metrics/cachestats` returning cache hit count, miss count, and current size.

#### Scenario: Cache stats returned
- **WHEN** a client requests `GET /v2/retrieval/metrics/cachestats`
- **THEN** the response is `200 OK` containing `hits`, `misses`, and `size`

### Requirement: OpenTelemetry trace export
When `OTLP_ENDPOINT` is configured and the `telemetry` extra is installed, the service SHALL export spans via OTLP/gRPC for retrieval requests and store calls; otherwise tracing SHALL be a no-op.

#### Scenario: No-op tracing without OTLP_ENDPOINT
- **WHEN** `OTLP_ENDPOINT` is unset
- **THEN** no OTLP exporter is initialized and retrieval requests complete normally

### Requirement: Optional offline RAGAS evaluation endpoint
The service SHALL expose `POST /v2/retrieval/evaluate/offline` to score `(query, contexts, answer)` inputs when the optional `retrieval-eval` extra (`ragas`) is installed, and SHALL return `501 Not Implemented` when `ragas` is unavailable.

#### Scenario: Offline eval returns 501 when ragas is not installed
- **WHEN** `POST /v2/retrieval/evaluate/offline` is called without `ragas` installed
- **THEN** the service returns `501 Not Implemented`

#### Scenario: Offline eval returns scores when ragas is available
- **WHEN** `POST /v2/retrieval/evaluate/offline` is called with valid inputs and `ragas` configured
- **THEN** the service returns `200 OK` with faithfulness, answer relevancy, and context precision scores
