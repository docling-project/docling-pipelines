# Spec Delta

## Purpose

A bounded, stateless agent that answers a question over a document library by choosing which stores to query, looking at the evidence, and refining within a budget. It reuses the retrieval engine's store queries, SQL path, ACL filtering, and summary rules, and never bypasses `backend/retrieval-sql`. Behavior follows retrieval-v2 PRs #30 (plan mode), #32 (tool mode), and #33 (hardened SQL), with the scope reductions listed in the proposal.

## ADDED Requirements

### Requirement: Agent availability
The agent SHALL be available only when `AGENT_ENABLED` is true, `retrieval.enabled` is true, and an inference adapter other than the no-op adapter is configured. Otherwise the agent routes SHALL respond 501 with code `retrieval_agent_disabled`.

#### Scenario: Master switch off
- **WHEN** `AGENT_ENABLED` is not true
- **THEN** the agent routes respond 501 and the non-agent retrieval routes are unaffected

#### Scenario: No LLM configured
- **WHEN** no inference adapter is configured
- **THEN** the agent routes respond 501

### Requirement: Mode selection
The agent SHALL support `plan`, `tool`, and `auto` modes, configured by `retrieval.agent.mode` with default `plan`. `auto` SHALL use tool mode only when the active model is confirmed to support tool calling, otherwise plan mode. A failed capability lookup SHALL select plan mode and record the reason in the trace.

#### Scenario: Forced mode
- **WHEN** the operator sets mode `plan` or `tool`
- **THEN** that mode is used without a capability lookup

#### Scenario: Auto with a capable model
- **WHEN** mode is `auto` and the model supports tool calling
- **THEN** tool mode runs and the trace records `tool`

#### Scenario: Auto with lookup failure
- **WHEN** mode is `auto` and the capability lookup raises
- **THEN** plan mode runs and the trace records the reason

#### Scenario: Tool mode without support
- **WHEN** mode is `tool` and the adapter does not implement tool calling
- **THEN** the run ends as an error with code `retrieval_agent_unsupported_model` before any retrieval

### Requirement: Prepare step without an LLM
The agent SHALL begin by resolving the library through derivatives, applying the access rules of `backend/retrieval-api`, building the schema text from the allowed entity tables, and listing usable stores, all without an LLM call. A library fetch failure or denied access SHALL end the run as an error before any retrieval.

#### Scenario: Library not found
- **WHEN** the library does not exist
- **THEN** the run ends as an error with no LLM call and no store query

#### Scenario: No usable store
- **WHEN** no store is usable
- **THEN** no LLM call is made and the answer states that nothing is searchable, with status `partial`

### Requirement: Run budget
Every run SHALL be bounded by `max_iterations` (refinement rounds, default 2), `max_llm_calls` (default 10), `deadline_seconds` (default 120), tool calls (3 times `max_llm_calls`), and `max_concurrency` (default 2). One LLM call SHALL be reserved for synthesis, so no other step or JSON retry may use the last remaining call. Request overrides SHALL only lower these limits.

#### Scenario: Override above the operator limit
- **WHEN** a request asks for `max_llm_calls` above the operator maximum
- **THEN** the operator maximum is used

#### Scenario: Reserved synthesis
- **WHEN** one LLM call remains
- **THEN** only synthesis may use it

#### Scenario: Budget scope
- **WHEN** the budget is counted
- **THEN** it counts the agent's own calls (plan, evaluate, refine, tool chat, synthesis, JSON retries) and not the text-to-SQL or reranker calls inside the retrieval engine

### Requirement: Time reserve for synthesis
Non-synthesis work SHALL stop early enough to leave time for synthesis: plan work at the lesser of 5 seconds and 10 percent of the deadline before the end, tool exploration at the lesser of 10 seconds and 20 percent. Every LLM call and every tool call SHALL be bounded by the remaining time, and no step SHALL start after the deadline.

#### Scenario: Deadline reached during exploration
- **WHEN** the exploration reserve is reached
- **THEN** no new tool call starts and synthesis runs in the remaining time

### Requirement: Plan mode steps
Plan mode SHALL run `plan` (one JSON call: sub-questions, store `sql`, `vector` or `both`, `depends_on`, `ref_column`), then rounds of `retrieve`, `evaluate`, `refine`, then `synthesize`. Independent sub-questions SHALL run concurrently in dependency waves. A single sub-question SHALL use the original question text unchanged.

#### Scenario: Dependent sub-questions
- **WHEN** sub-question 2 depends on sub-question 1
- **THEN** 2 runs only after 1 completes

#### Scenario: Independent sub-questions
- **WHEN** two sub-questions have no dependency
- **THEN** they run in the same wave

#### Scenario: Cyclic or malformed plan
- **WHEN** the plan has a cycle, an unknown label, an empty `ref_column`, or a vector-only upstream
- **THEN** it is rejected, and after retries all available stores are queried once with the original question and the run is `partial`

### Requirement: Evaluation and refinement
After each retrieval round, one call SHALL judge per sub-question whether the evidence is sufficient. One call SHALL then rewrite the query or switch store for each insufficient sub-question. A repeated store and query pair (case-folded, whitespace-collapsed) SHALL stop refinement of that sub-question. Successful evidence SHALL be kept when a refinement returns nothing or fails.

#### Scenario: Insufficient evidence
- **WHEN** a sub-question is judged insufficient and rounds remain
- **THEN** it is refined and retrieved again

#### Scenario: Duplicate attempt
- **WHEN** a refinement repeats an earlier store and query
- **THEN** that sub-question stops refining and the run is `partial`

#### Scenario: Evidence retained
- **WHEN** a refinement returns an empty or failed result
- **THEN** the earlier successful evidence is still used

### Requirement: Safe substitution of upstream values
A dependent sub-question SHALL receive upstream values only from the named column of upstream SQL rows, at most 20 distinct values of at most 64 characters, with control characters removed and every single quote doubled. Labels SHALL match whole (`$var_1` MUST NOT match inside `$var_10`). Truncation SHALL mark the run `partial`. Vector text MUST NOT be substituted.

#### Scenario: Apostrophe in a value
- **WHEN** an upstream value is `O'Connor`
- **THEN** it is rendered as `O''Connor`

#### Scenario: Similar labels
- **WHEN** a template contains `$var_1` and `$var_10`
- **THEN** each is replaced independently

#### Scenario: Empty upstream
- **WHEN** the upstream result is empty or failed
- **THEN** its dependents are skipped, a `skipped` trace entry is recorded, and the run is `partial`

### Requirement: Tool mode
Tool mode SHALL send the question, a library overview, and the tool schemas to a tool-calling chat. The model picks the next calls after reading each result. A batch SHALL run under `max_concurrency`, identical calls in a batch SHALL run once, and each result SHALL be paired with its original call id. Exploration SHALL stop when the model returns no tool calls or a limit is reached. The shared synthesizer, not the model's closing text, SHALL write the answer.

#### Scenario: Duplicate calls
- **WHEN** a batch contains two identical calls
- **THEN** the tool runs once and both calls receive the result

#### Scenario: Unknown tool or invalid arguments
- **WHEN** the model requests an unknown tool or invalid arguments
- **THEN** it receives a generic error and the run continues if budget remains

#### Scenario: Model stops
- **WHEN** the model returns no tool calls
- **THEN** exploration ends and the shared synthesis runs

### Requirement: Read-only tools
Tool mode SHALL offer exactly `describe_library`, `describe_table`, `query_table`, `column_values`, and `search_passages`. Every tool SHALL stay within the prepared library and its access checks. Arguments SHALL reject unknown fields, and numeric bounds SHALL be clamped. Model arguments MUST NOT select a connection or another library. A set SHALL be named by id or an unambiguous case-insensitive exact name.

#### Scenario: Set outside the library
- **WHEN** a tool names a set that is not in the prepared library
- **THEN** it fails with a generic unavailable result and runs no query

#### Scenario: Bounds clamped
- **WHEN** a limit is outside its range
- **THEN** the nearest supported bound is used

#### Scenario: Passage-only set
- **WHEN** a set has no SQL tables
- **THEN** its description says so and structured queries are not routed to it

### Requirement: query_table
`query_table` SHALL accept exactly one of `question` or `sql`. A question SHALL follow the engine's text-to-SQL path. Supplied SQL SHALL go through `validate_and_authorize` against only the selected set's tables, SHALL run without a generation call, and a rejection SHALL be returned to the model with the safe message and no correction model call. Results SHALL be at most 50 rows with the executed SQL and row count.

#### Scenario: Both or neither
- **WHEN** both or neither of `question` and `sql` are supplied
- **THEN** the tool returns an invalid-arguments error naming the exactly-one rule

#### Scenario: SQL outside the set
- **WHEN** supplied SQL reads a table outside the selected set
- **THEN** it is rejected before the engine is called

#### Scenario: Zero rows
- **WHEN** a query returns no rows
- **THEN** the result is an observation that says text comparisons are exact and points to `column_values`

### Requirement: column_values
`column_values` SHALL return the most frequent distinct stored values of one column of one allowed table with counts, up to the limit, with an optional case-insensitive substring filter. The statement SHALL be built from validated identifiers in the connector dialect and pass `validate_and_authorize`.

#### Scenario: Unknown identifier
- **WHEN** the table or column is unknown or malformed
- **THEN** the tool returns an error and runs no query

#### Scenario: Filter with wildcards
- **WHEN** the filter contains `%`, `_`, or a quote
- **THEN** those characters match only themselves

### Requirement: search_passages
`search_passages` SHALL run the engine's vector search for a query, optionally restricted to up to 100 document ids, with limit 1 to 10. An explicit empty id list SHALL match nothing and MUST NOT fall back to an unrestricted search. ACL filtering SHALL apply as for normal search.

#### Scenario: Narrowed by SQL evidence
- **WHEN** document ids from a prior query are given
- **THEN** only those documents are searched

#### Scenario: Empty id list
- **WHEN** `document_ids` is an empty list
- **THEN** no passage is returned

### Requirement: Tool result bounds and privacy
Tool results shown to the model SHALL be JSON with `data`, `count`, `truncated`, and tool-specific fields, serialized to at most 12,000 characters with strings cut at 8,000 and lists at 50. Only returned, non-cached result items SHALL become answer evidence; metadata and errors MUST NOT. Tool history MUST NOT be returned to the client.

#### Scenario: Oversized result
- **WHEN** a result exceeds the serialization limit
- **THEN** it is truncated and `truncated` is true

#### Scenario: Metadata is not evidence
- **WHEN** `describe_library` runs
- **THEN** its output is never cited or summarized as evidence

### Requirement: Synthesis and citations
Synthesis SHALL run once from the gathered evidence with duplicate excerpts removed and evidence delimited as untrusted data. The context SHALL be capped (32,000 characters in tool mode, 30,000 in plan mode) with a visible shown-of-total notice. The answer SHALL cite `[document_id: ...]`; known ids are kept, a unique returned name maps to its id, and unknown or ambiguous citations are removed.

#### Scenario: Unknown citation
- **WHEN** the model cites an id that was not returned
- **THEN** the citation is removed

#### Scenario: Zero-row observation
- **WHEN** the only evidence is a successful SQL query with no rows
- **THEN** the answer can say none were found and the run is not treated as having no evidence

### Requirement: Numeric reconciliation
Numeric figures SHALL be taken from structured SQL rows when present. A material disagreement between SQL rows and document text SHALL be reported as unresolved with both values, and the model SHALL NOT silently prefer either source.

#### Scenario: SQL and document disagree
- **WHEN** a figure differs materially between SQL rows and document text
- **THEN** the answer reports both values as unresolved

### Requirement: Deterministic fallback answer
When the reserve is unavailable, the deadline has passed, or synthesis fails or returns empty text, the agent SHALL return a deterministic answer built from the evidence (SQL rows as Markdown tables, excerpts cut to 500 characters, fixed header) with status `partial`.

#### Scenario: Synthesis call fails
- **WHEN** the synthesis call raises
- **THEN** the deterministic answer is returned with status `partial`

### Requirement: Status rules
The run status SHALL be `success` only when every sub-question (or the tool exploration) produced at least one evidence item or a zero-row observation, nothing was skipped, no store failed, no fallback was taken, no limit was hit, and synthesis used the LLM. Any other completed run SHALL be `partial`. Denied access, a library fetch failure, or an unexpected exception SHALL be an error.

#### Scenario: Limit hit
- **WHEN** the call budget is exhausted before evidence was judged sufficient
- **THEN** the status is `partial` and the budget report names the limit

#### Scenario: Unanswerable synthesis
- **WHEN** the synthesized answer states it cannot determine the result
- **THEN** the status is `partial`

### Requirement: Degraded behavior on model or store failure
Invalid JSON from the model SHALL be retried up to `retrieval.agent.json_retries` (default 1) within the budget. After that: an invalid plan falls back to querying all stores once; an invalid evaluation is treated as sufficient; an invalid refinement stops refining. One failing store SHALL keep the other's evidence. Each case SHALL set status `partial`.

#### Scenario: Evaluation output invalid
- **WHEN** the evaluation reply is invalid after retries
- **THEN** the evidence is treated as sufficient and the run is `partial`

#### Scenario: One store fails
- **WHEN** one store errors during retrieval
- **THEN** the other store's evidence is kept and the run is `partial`

### Requirement: Step trace
The response SHALL include an ordered trace with `step`, `label`, `template`, `store`, `outcome`, `count`, `elapsed_ms`, and for evaluation `verdict` and a reason cut to 200 characters. The trace SHALL record dependent sub-questions as the template before substitution. It MUST NOT contain tokens, row values, excerpt text, or generated SQL, and the caller's token SHALL be scrubbed from every string.

#### Scenario: Template kept
- **WHEN** a dependent sub-question was substituted
- **THEN** the trace holds the template with `$var_N`, not the values

#### Scenario: Token scrubbed
- **WHEN** a string in the trace contains the caller's bearer token
- **THEN** the token is replaced before the trace is returned

### Requirement: Budget report
The response SHALL include used and maximum rounds and calls, elapsed and deadline time, and `stopped_on` (`iterations`, `llm_calls`, `deadline`, or null).

#### Scenario: Stopped on calls
- **WHEN** the call limit ends the run
- **THEN** `stopped_on` is `llm_calls`

### Requirement: Stateless and uncached
A run SHALL keep no state between requests. Agent responses MUST NOT be cached, and `disable_cache`, `evaluate`, and `search_config` SHALL be ignored.

#### Scenario: Repeated request
- **WHEN** the same question is submitted twice
- **THEN** each run is independent and neither is served from cache

### Requirement: Access parity
The agent SHALL apply the same authentication, library access, and vector ACL filtering as non-agent search, SHALL add no data access, and MUST NOT forward the caller's token to an LLM provider that does not need it.

#### Scenario: Restricted chunk
- **WHEN** a chunk is not allowed for the caller
- **THEN** neither plan retrieval nor `search_passages` returns it

### Requirement: Tool-calling port
The system SHALL define an optional `LLMToolChatPort` with `chat_tools(messages, tools, ...)` returning text and normalized tool calls, and `supports_tool_calling(model)`. Provider message shapes SHALL be normalized inside adapters. Existing `LLMInferencePort` behavior MUST NOT change.

#### Scenario: Adapter without support
- **WHEN** an adapter does not implement the port
- **THEN** `auto` mode uses plan mode

#### Scenario: Normalized call
- **WHEN** a provider returns a tool call
- **THEN** the agent receives an id, a name, and a parsed argument object regardless of provider
