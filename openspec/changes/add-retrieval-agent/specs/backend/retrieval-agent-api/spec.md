# Spec Delta

## Purpose

The REST contract of the retrieval agent. It follows the job pattern of `backend/retrieval-api` with a dedicated queue so agent load cannot starve normal search.

## ADDED Requirements

### Requirement: Submit an agent search
The system SHALL expose `POST /api/v1/retrieval/agent-search-jobs`. The body SHALL contain `query` (1 to 4000 characters), exactly one of `document_library_id` or `asset_id`, and MAY contain `max_iterations` (at least 0), `max_llm_calls` (at least 3), `deadline_seconds`, `search_inference_config`, `container_id`, and `container_type`. The response SHALL be 202 with `query_id`.

#### Scenario: Accepted
- **WHEN** a valid body is posted
- **THEN** the response is 202 with a `query_id`

#### Scenario: Budget too small
- **WHEN** `max_llm_calls` is below 3
- **THEN** the response is 422

#### Scenario: Target rules
- **WHEN** neither or both targets are given
- **THEN** the response is 422

### Requirement: Poll an agent search
`GET /api/v1/retrieval/agent-search-jobs/{query_id}` SHALL return 202 while pending, 200 with the agent response when done, 404 when unknown, expired, or owned by another user, and 500 with a fixed generic message when the run ended in error.

#### Scenario: Completed
- **WHEN** a job finished
- **THEN** the response is 200 with `generated_text`, `results`, `status`, `additional_info.agent_trace`, and `additional_info.agent_budget`

#### Scenario: Error run
- **WHEN** the run ended in error
- **THEN** the response is 500 with a fixed message and no stored error text

#### Scenario: Another user's job
- **WHEN** user B polls user A's `query_id`
- **THEN** the response is 404

### Requirement: Agent queue behavior
The agent SHALL use its own queue with TTL, capacity, and a concurrency cap equal to `retrieval.agent.max_concurrency`. When the queue is full, submission SHALL return 503 with code `retrieval_queue_full` and `Retry-After`, without blocking. Errors stored with jobs SHALL be redacted.

#### Scenario: Queue full
- **WHEN** the agent queue is at capacity
- **THEN** submission returns 503 immediately

#### Scenario: Isolation from normal search
- **WHEN** the agent queue is saturated
- **THEN** non-agent search jobs are still accepted

### Requirement: Availability and access
Agent routes SHALL require an authenticated user with the same access level as other retrieval routes and SHALL return 501 `retrieval_agent_disabled` when the agent is unavailable, and 503 `retrieval_disabled` when retrieval is disabled.

#### Scenario: Unauthenticated
- **WHEN** authentication is enabled and credentials are missing
- **THEN** the response is 401

#### Scenario: Agent disabled
- **WHEN** the agent is not enabled
- **THEN** the response is 501

### Requirement: Response additions
Agent responses SHALL reuse the search response shape. `additional_info` SHALL add `agent_trace`, `agent_budget`, and `agent_mode`. Result items MUST NOT include generated SQL unless `search_inference_config.include_sql` is true.

#### Scenario: Mode reported
- **WHEN** a run completes
- **THEN** `additional_info.agent_mode` is `plan` or `tool`

#### Scenario: SQL hidden by default
- **WHEN** a SQL item is returned without `include_sql`
- **THEN** `metadata.sql` is absent
