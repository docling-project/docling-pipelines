# backend/retrieval-agent Specification

## Purpose

Defines the opt-in bounded agentic retrieval capability for Docling Pipelines: async submit/poll API endpoints, plan and native tool-calling modes, read-only library-scoped tools over DuckDB and vector stores, optional tool thinking, budget enforcement, and safe traceable synthesis.

## ADDED Requirements

### Requirement: Opt-in agentic search endpoints
The service SHALL expose `POST /v2/retrieval/agent/search` (`202 Accepted` with `query_id`) and `GET /v2/retrieval/agent/search/result/{query_id}` (`202`, `200`, `404`, `500`). Both endpoints SHALL require an authenticated user, SHALL return `501` when the agent is disabled or no LLM is configured, and `POST` SHALL return `503` when `max_concurrency` is saturated.

#### Scenario: Agent disabled returns 501
- **WHEN** `retrieval.agent.enabled` is false and a client calls `POST /v2/retrieval/agent/search`
- **THEN** the service returns `501 Not Implemented`

#### Scenario: Saturated agent concurrency returns 503
- **WHEN** `max_concurrency` agent runs are already executing
- **THEN** a new `POST /v2/retrieval/agent/search` returns `503 Service Unavailable` immediately

#### Scenario: Blank query or missing document_library_id returns 400
- **WHEN** a client submits an agent request with a blank `query` or missing `document_library_id`
- **THEN** the service returns `400 Bad Request` (via Docling Pipelines' global validation error handler)

#### Scenario: Unauthenticated agent request returns 401
- **WHEN** a client calls either agent endpoint without a valid bearer token
- **THEN** the service returns `401 Unauthorized` and no agent run is started

#### Scenario: Poll returns 404 when owned by another user
- **WHEN** an authenticated user polls an agent `query_id` submitted by a different user
- **THEN** the service returns `404 Not Found`

### Requirement: Agent mode selection
The agent SHALL support `auto`, `tool`, and `plan` modes (default `auto`). `auto` SHALL select `tool` mode only when the active model is confirmed to support native tool calling; otherwise it SHALL select `plan` mode.

#### Scenario: Tool-capable model selects tool mode in auto
- **WHEN** `mode` is `auto` and the active model is in the configured tool-capable allowlist
- **THEN** the agent runs the native tool loop and records `tool` mode in `additional_info.agent_trace`

#### Scenario: Non-tool model falls back to plan mode in auto
- **WHEN** `mode` is `auto` and the active model is not confirmed tool-capable
- **THEN** the agent runs the plan loop and records `plan` mode in `additional_info.agent_trace`

### Requirement: Authorized read-only retrieval tools
In `tool` mode, the agent SHALL expose only read-only tools scoped to the authorized `DocumentLibrary` (`describe_library`, `query_table`, `column_values`, `search_passages`, `list_documents`, `find_documents`, `read_document`). SQL SHALL pass the Phase 1 allowlist validator and run through the Phase 1 `DuckDBConnectionManager` path. The agent SHALL NOT reach any store or document set that the Phase 1 engine would skip for the same caller.

#### Scenario: query_table accepts exactly one input form
- **WHEN** the model calls `query_table`
- **THEN** it must supply exactly one of a plain-language question or read-only DuckDB SQL, otherwise the tool returns a validation error

#### Scenario: Tool referencing an unauthorized document set fails closed
- **WHEN** the model calls any tool with a `document_set_id` outside the target `DocumentLibrary`
- **THEN** the tool returns a generic unavailable error without querying any store

#### Scenario: DuckDB-backed tools are unavailable for ACL-protected document sets
- **WHEN** the model calls `query_table`, `column_values`, `find_documents`, `list_documents`, or `read_document` for a document set that is ACL-protected
- **THEN** the tool returns the same generic unavailable error as for an unauthorized set, no DuckDB connection is opened, and the run status is `"partial"`

#### Scenario: Passage search on ACL-protected sets is OpenSearch-only and filtered
- **WHEN** `search_passages` targets an ACL-protected document set
- **THEN** only OpenSearch targets are queried, with the `allowed_users` filter for the authenticated user, and Milvus and Weaviate targets are skipped with an `acl_protected_store_skipped` note

#### Scenario: SQL kill-switch disables DuckDB-backed agent tools
- **WHEN** `retrieval.sql.enabled` is false
- **THEN** every DuckDB-backed agent tool and plan-mode SQL step is unavailable, while `search_passages` continues to work

#### Scenario: Oversized tool result is truncated
- **WHEN** a tool result exceeds `retrieval.sql.max_rows` rows or `retrieval.agent.max_tool_result_chars` characters
- **THEN** the result returned to the model is truncated to the cap, truncation is traced as a boolean, and the run status is `"partial"`

#### Scenario: Passage search narrows to SQL-derived document IDs
- **WHEN** `search_passages` is called with `document_ids` from a prior SQL query
- **THEN** vector search restricts hits to those `document_ids` and never falls back to an unrestricted search

### Requirement: Plan mode decomposition, safe substitution, and bounded refinement
In `plan` mode, the agent SHALL route by intent, decompose multi-hop questions into a dependency-checked DAG (rejecting cycles), substitute upstream SQL column values safely (at most 20 distinct values, 64 chars each, escaped, never vector text), evaluate evidence sufficiency, and refine without repeating a `(store, query)` pair.

#### Scenario: Upstream SQL substitution is bounded and sanitized
- **WHEN** an upstream SQL column has more than 20 distinct values or contains quotes/newlines
- **THEN** at most 20 sanitized values are substituted, truncation is traced, and the run status is `"partial"`

#### Scenario: Duplicate refinement attempt prevented
- **WHEN** refinement proposes a `(store, query)` already tried for that sub-question
- **THEN** the agent skips the duplicate attempt, moves to synthesis, and sets `status: "partial"`

### Requirement: Budget enforcement, optional tool thinking, and safe traces
Each agent run SHALL enforce configured `max_iterations`, `max_llm_calls` (with 1 call always reserved for synthesis), and soft `deadline_seconds` (request overrides may only lower limits). Optional `tool_thinking` (`on`) SHALL share the same budgets. Public `additional_info.agent_trace` and logs SHALL exclude raw tool arguments, generated SQL, credentials, and retrieved evidence.

#### Scenario: Synthesis call reserved when call budget is reached
- **WHEN** the next non-synthesis step would consume the final remaining LLM call
- **THEN** exploration stops, synthesis runs using the reserved call, and `status` is `"partial"`

#### Scenario: Evidence-grounded synthesis with safe trace
- **WHEN** an agent run finishes with gathered evidence
- **THEN** `QueryResponse` includes `additional_info.agent_trace` and `additional_info.agent_budget`, cites only retrieved `document_id`s, reports unresolved SQL-vs-document numeric disagreements, and never leaks raw tool arguments or credentials
