# backend/retrieval-api Specification

## Purpose

Defines the externally observable HTTP contract for Docling Pipelines' native retrieval service, maintaining full wire compatibility with the `retrieval-v2` `query-api` specification (synchronous v1, asynchronous v2 submit/poll, direct asset search, and liveness/readiness probes).

## ADDED Requirements

### Requirement: Synchronous query endpoint (v1)
The service SHALL accept `POST /v1/retrieval/advanced/search` (alias: `POST /v1/retrieval/search`) with a JSON `QueryRequest` body containing `query`, optional `container_id` and `container_type` (accepted for `retrieval-v2` client compatibility), a target identifier (`document_library_id`, `document_set_id`, or `asset_id` + `asset_type`), and optionally `search_config` (alias `searchConfig`), `search_inference_config`, `disable_cache`, and `evaluate`.

#### Scenario: Successful synchronous search
- **WHEN** a client sends a valid `POST /v1/retrieval/advanced/search` (or `POST /v1/retrieval/search`) request with a `query` and an existing `document_library_id` or `document_set_id`
- **THEN** the service returns `200 OK` with a `QueryResponse` body containing `request_id`, `results`, `status`, and `execution_time`

#### Scenario: Synchronous search returns partial status on store failure
- **WHEN** a retrieval store fails during search and at least one other store succeeds
- **THEN** the response `status` field is `"partial"` and the available results are included

#### Scenario: Unknown target asset returns 404
- **WHEN** a client sends a search request referencing a `document_library_id`, `document_set_id`, or `asset_id` that does not exist
- **THEN** the service returns `404 Not Found`

#### Scenario: Missing target identifier or blank query returns 400
- **WHEN** a client sends a search request with a blank `query` or without any target identifier (`document_library_id`, `document_set_id`, or `asset_id`)
- **THEN** the service returns `400 Bad Request` (via Docling Pipelines' global validation error handler)

### Requirement: Asynchronous query submit endpoint (v2)
The service SHALL accept `POST /v2/retrieval/advanced/search` (alias: `POST /v2/retrieval/search`) and return `202 Accepted` immediately with `query_id` and `status: "pending"`.

#### Scenario: Submit returns 202 with query_id
- **WHEN** a client sends `POST /v2/retrieval/advanced/search` (or `POST /v2/retrieval/search`)
- **THEN** the service returns `202 Accepted` with a JSON body containing `query_id` (a UUID string) and `status: "pending"`

### Requirement: Asynchronous result poll endpoint (v2)
The service SHALL accept `GET /v2/retrieval/advanced/search/result/{query_id}` (alias: `GET /v2/retrieval/search/result/{query_id}`) and return the job status.

#### Scenario: Poll returns 202 while job is pending
- **WHEN** the job identified by `query_id` is still executing
- **THEN** the service returns `202 Accepted` with `{"query_id": "<uuid>", "status": "pending"}`

#### Scenario: Poll returns 200 with result when job is done
- **WHEN** the job identified by `query_id` has completed successfully
- **THEN** the service returns `200 OK` with the full `QueryResponse`

#### Scenario: Poll returns 500 when job failed
- **WHEN** the job identified by `query_id` failed with an error
- **THEN** the service returns `500` with a sanitized error response (never leaking connection credentials)

#### Scenario: Poll returns 404 for unknown query_id
- **WHEN** the provided `query_id` is not found (never submitted or TTL expired)
- **THEN** the service returns `404 Not Found`

### Requirement: Direct asset search endpoint (v2)
The service SHALL accept `POST /v2/retrieval/search_data_assets` and execute the same asynchronous retrieval pipeline as `POST /v2/retrieval/advanced/search`.

#### Scenario: Direct asset search returns 202
- **WHEN** a client sends `POST /v2/retrieval/search_data_assets`
- **THEN** the service returns `202 Accepted` with a `query_id` and `status: "pending"`

### Requirement: Liveness probe
The service SHALL expose `GET /v2/retrieval/healthz` that returns `200 OK` with `{"status": "ok"}` without authentication.

#### Scenario: Liveness returns 200
- **WHEN** the service is running
- **THEN** `GET /v2/retrieval/healthz` returns `200 OK` with body `{"status": "ok"}`

### Requirement: Readiness probe
The service SHALL expose `GET /v2/retrieval/readyz` that returns `200 OK` when the orchestrator is fully wired and `503 Service Unavailable` otherwise, without authentication.

#### Scenario: Readiness returns 503 before orchestrator is ready
- **WHEN** the service has started but the orchestrator is not yet initialised (or retrieval is disabled)
- **THEN** `GET /v2/retrieval/readyz` returns `503 Service Unavailable`

#### Scenario: Readiness returns 200 when ready
- **WHEN** the orchestrator is fully initialised
- **THEN** `GET /v2/retrieval/readyz` returns `200 OK`

### Requirement: QueryResponse schema
The service SHALL return `QueryResponse` objects with fields: `request_id` (UUID string), `generated_text` (optional string), `results` (optional list of `ResultItem`), `status` (`"success"`, `"partial"`, or `"error"`), `execution_time` (integer milliseconds), and optionally `additional_info`. All routes SHALL serialize payloads exclusively through Pydantic DTOs in `src/docpipe/api/dto/retrieval_dto.py`.

#### Scenario: Response includes request_id and execution_time
- **WHEN** any search completes
- **THEN** the response body contains a non-empty `request_id` and a non-negative integer `execution_time`

### Requirement: Async job TTL and queue limits
The service SHALL discard async job results after 900 seconds, hold at most 2 048 results in the TTL cache, and reject new submissions when the queue depth exceeds 100 with `503 Service Unavailable`.

#### Scenario: Expired result returns 404
- **WHEN** a client polls for a `query_id` more than 900 seconds after completion
- **THEN** the service returns `404 Not Found`

#### Scenario: Full queue rejects new submissions
- **WHEN** the async job queue already contains 100 pending jobs
- **THEN** a new `POST /v2/retrieval/advanced/search` returns `503 Service Unavailable`

### Requirement: Authentication and ACL propagation
All v1 and v2 search and result-polling routes SHALL integrate with Docling Pipelines' authentication dependency (`get_current_user`) and pass the authenticated user identity to the retrieval ACL adapter for store-level filtering (such as OpenSearch `allowed_users`).

#### Scenario: Authenticated user identity propagated to ACL
- **WHEN** an authenticated user invokes `POST /v1/retrieval/advanced/search`
- **THEN** the authenticated user identity is passed to `RetrievalACLPort`
