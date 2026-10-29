# Spec Delta

## Purpose

The REST contract of the retrieval service: how clients submit a question against a document library or document set, receive results synchronously or through a polled job, read the event trail, and evaluate results. Shapes are docpipe's own and follow repo conventions (`/api/v1`, hyphenated resources, DTOs only, `ErrorResponse` errors).

## ADDED Requirements

### Requirement: Synchronous search
The system SHALL expose `POST /api/v1/retrieval/search`. The body SHALL contain `query` (1 to 4000 characters) and exactly one of `document_library_id` or `asset_id` (a document set id). The 200 response SHALL contain `request_id`, `generated_text`, `results`, `additional_info`, `status` (`success`, `partial`, `error`), and `execution_time`.

Optional body fields are `search_config`, `search_inference_config`, `disable_cache`, `evaluate`, `container_id`, and `container_type`.

#### Scenario: Library search
- **WHEN** a client posts a `query` and a valid `document_library_id`
- **THEN** the response is 200 with `status: "success"` and one result item per queried store

#### Scenario: Neither or both targets
- **WHEN** the body has neither or both of `document_library_id` and `asset_id`
- **THEN** the response is 422

#### Scenario: Empty query
- **WHEN** `query` is empty or longer than 4000 characters
- **THEN** the response is 422

#### Scenario: Unknown library
- **WHEN** the library does not exist
- **THEN** the response is 404 with code `document_library_not_found`

### Requirement: Search configuration
`search_config` items SHALL have `type` in `vector` or `sql` and `limit` between 1 and 100. When omitted, the service SHALL use one `vector` item and, if `retrieval.sql.enabled` is true and the target has retrievable entity tables, one `sql` item, each with the configured default limit. A requested `sql` type when SQL is disabled or no entity table exists SHALL produce no SQL item and a note in `additional_info`, not an error.

#### Scenario: Default config
- **WHEN** `search_config` is omitted and the library has vector stores and entity tables
- **THEN** both vector and SQL items are returned

#### Scenario: SQL disabled
- **WHEN** `retrieval.sql.enabled` is false and a client requests type `sql`
- **THEN** the response contains no SQL item and `additional_info` states that SQL retrieval is disabled

#### Scenario: Limit bounds
- **WHEN** an item has `limit` 0 or 101
- **THEN** the response is 422

### Requirement: Inference configuration
`search_inference_config` SHALL accept `model_id`, `generate_summary`, `include_sql`, and `llm_judge`. Unknown keys SHALL be rejected with 422.

#### Scenario: Unknown key
- **WHEN** `search_inference_config` contains an unknown key
- **THEN** the response is 422

### Requirement: Result item shape
Each `results` item SHALL contain `source` (`vector` or `sql`), `data` (list of rows or chunks), `metadata` (`execution_time`, `row_count`, and as applicable `sql`, `model_used`, `document_id`, `page_number`, `rrf_score`), and optionally `summary`. `metadata.sql` SHALL be present only when `search_inference_config.include_sql` is true.

#### Scenario: Vector chunk metadata
- **WHEN** a vector item is returned
- **THEN** each chunk carries `document_id` and `rrf_score` when hybrid search ran

#### Scenario: Zero-row SQL item
- **WHEN** a SQL query executes and matches nothing
- **THEN** a SQL item with `row_count: 0` and empty `data` is returned

#### Scenario: SQL text hidden by default
- **WHEN** a SQL item is returned without `include_sql`
- **THEN** `metadata.sql` is absent

### Requirement: Asynchronous search
The system SHALL expose `POST /api/v1/retrieval/search-jobs` accepting the same body as synchronous search and returning 202 with `query_id`. `GET /api/v1/retrieval/search-jobs/{query_id}` SHALL return 202 while pending, 200 with the search response when done, 404 when unknown or expired, and the job's mapped error status when it failed.

#### Scenario: Submit and poll
- **WHEN** a client submits a job and polls until completion
- **THEN** the poll returns 202 until done, then 200 with the same body shape as synchronous search

#### Scenario: Unknown query id
- **WHEN** a client polls an unknown `query_id`
- **THEN** the response is 404

#### Scenario: Queue full
- **WHEN** the job queue is at capacity
- **THEN** submission returns 503 with code `retrieval_queue_full` and a `Retry-After` header

#### Scenario: Failed job
- **WHEN** a job failed with an upstream store error
- **THEN** polling returns the mapped error with the generic client message and the failure is recorded in the event trail

### Requirement: Job ownership
A job SHALL be readable only by the user that submitted it. Polling a job of another user SHALL return 404, not 403.

#### Scenario: Other user polls
- **WHEN** user B polls the `query_id` submitted by user A
- **THEN** the response is 404

### Requirement: Event trail
The system SHALL expose `GET /api/v1/retrieval/events/{request_id}` returning the ordered events recorded for a request (stage, timestamp, duration, status, counts). Events MUST NOT contain query text, SQL text, row data, or credentials. Only the submitting user SHALL read them; others get 404.

#### Scenario: Events for a request
- **WHEN** a client requests events for a completed search it submitted
- **THEN** the response lists stages such as resolve, vector, sql, rerank, summary in order

#### Scenario: No content in events
- **WHEN** events are returned
- **THEN** they contain no `query`, `sql`, or `data` fields

### Requirement: Evaluate
The system SHALL expose `POST /api/v1/retrieval/evaluate` accepting `query`, a target, and `expected` (list of expected document ids or answer snippets) and returning retrieval metrics (precision at k, recall at k, and per-item match flags). It SHALL NOT call an LLM unless `search_inference_config.llm_judge` is true.

#### Scenario: Document id expectations
- **WHEN** `expected` lists document ids and two of three are retrieved in the top results
- **THEN** recall at k is 2/3 for the requested k

### Requirement: Feature gating and authentication
All retrieval routes SHALL require an authenticated user and viewer-level role when `add-authn-authz` roles are active. When `retrieval.enabled` is false the routes SHALL respond 503 with code `retrieval_disabled`. Agent routes SHALL respond 501 unless `AGENT_ENABLED=true` and an LLM is configured.

#### Scenario: Disabled
- **WHEN** `retrieval.enabled` is false
- **THEN** every retrieval route returns 503 `retrieval_disabled`

#### Scenario: Agent not enabled
- **WHEN** a client posts to the agent search route and `AGENT_ENABLED` is not true
- **THEN** the response is 501

#### Scenario: Unauthenticated
- **WHEN** authentication is enabled and no valid credentials are sent
- **THEN** the response is 401

### Requirement: Generic error responses
Errors SHALL use `ErrorResponse` with a stable `ErrorCode`. Responses MUST NOT contain stack traces, store hostnames, SQL text, exception strings from drivers, or credentials. Details are logged server-side with the transaction id.

#### Scenario: Store unreachable
- **WHEN** every store fails
- **THEN** the response status is `error` or 502 with code `retrieval_upstream_failed` and a generic message

### Requirement: Ignored container parameters
`container_id` and `container_type` SHALL be accepted in the body and ignored.

#### Scenario: Container fields present
- **WHEN** a request includes `container_id` and `container_type`
- **THEN** results are identical to the same request without them
