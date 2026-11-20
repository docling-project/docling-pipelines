# Design: Opt-in Agentic Retrieval Service (Phase 4)

## 1. Architecture & DDD Placement

```text
src/docpipe/
├── core/ports/
│   └── tool_calling_llm_port.py              # ToolCallingLLMPort ABC (chat_tools + supports_tools)
├── api/
│   ├── dto/retrieval_dto.py                  # AgentQueryRequest, AgentTraceEntry, AgentBudgetUsage
│   └── routes/retrieval.py                   # POST /v2/retrieval/agent/search + GET .../result/{query_id}
└── core/retrieval/agent/
    ├── runner.py                             # AgentRunner: concurrency semaphore, mode selection, budget clamp
    ├── budget.py                             # Call/iteration/deadline tracker with synthesis reserve
    ├── state.py                              # Immutable/bounded evidence & history state
    ├── trace.py                              # Safe public trace builder (redacts args, SQL, evidence)
    ├── steps.py                              # Plan-mode driver (plan -> retrieve -> evaluate -> refine -> synthesize)
    ├── substitution.py                       # Safe upstream SQL value substitution (<=20 values, <=64 chars)
    ├── llm_json.py                           # Strict JSON parser with bounded retry
    ├── tool_loop.py                          # Native tool-calling loop with paired tool_call_id results
    ├── tool_thinking.py                      # Optional strategy turn, batch review, and coverage check
    ├── tools.py                              # JSON schemas + dispatcher for authorized read-only tools
    ├── tool_retrieval.py                     # query_table, column_values, search_passages (DuckDB + Vector)
    ├── tool_documents.py                     # list_documents, find_documents, read_document (DuckDB)
    └── prompts.py                            # Grounded synthesis, conflict reporting, and citation prompts
```

## 2. Key Decisions

- **D1. Opt-in & zero new dependencies**: Disabled by default (`retrieval.agent.enabled: false`). When disabled or no inference LLM is configured, both agent endpoints return `501 Not Implemented` and all Phase 1–3 endpoints remain unaffected.
- **D2. Budget clamping & synthesis reserve**: Request-level `max_iterations`, `max_llm_calls`, and `deadline_seconds` are clamped to `min(request_val, configured_val)` so callers can only tighten limits. `Budget` always reserves 1 LLM call for final synthesis; if the soft deadline elapses, synthesis falls back to a deterministic evidence summary without another LLM call and sets `status: "partial"`.
- **D3. Shared authorization boundary**: Every tool in `tools.py` operates strictly on the `LibraryDescriptor` resolved by `LocalDocumentLibraryCatalogAdapter` for the authenticated caller. Model arguments cannot pass connection strings, file paths, or foreign library/set IDs. The agent inherits the Phase 1 authorization model (Phase 1 D7) unchanged:
  - Both agent routes depend on `get_current_user`; a poll by a user other than the submitter returns `404`.
  - The agent is a new, model-driven path to the same data, so it MUST NOT be able to reach anything the Phase 1 engine would skip. For an ACL-protected document set (Phase 1 D7), every DuckDB-backed tool (`query_table`, `column_values`, `find_documents`, `list_documents`, `read_document`) is unavailable and returns the same generic unavailable error as an unauthorized set; `search_passages` only targets OpenSearch with the `allowed_users` filter and never targets Milvus or Weaviate. In plan mode the equivalent SQL sub-questions are skipped. Each skip sets `status: "partial"` and is recorded as `acl_protected_store_skipped`.
  - The `retrieval.sql.enabled` kill-switch also disables every DuckDB-backed agent tool and plan-mode SQL step, not just the Phase 1 SQL retriever.
  - DuckDB access goes through the Phase 1 `DuckDBConnectionManager` path (`access_mode`, `lock_timeout_seconds`), and user-supplied SQL passes the same Phase 1 allowlist validator; the agent has no separate or looser SQL path.
- **D4. Safe traces**: `trace.py` records only step index, mode (`plan` | `tool`), tool/action name, chosen store, hit/row counts, verdict, and duration — never raw tool arguments, generated SQL, or retrieved document text.
- **D5. Per-tool output caps**: Because tool output is fed back to the model and then into the synthesis prompt, each tool result is truncated before it reaches the model: at most `retrieval.sql.max_rows` rows and `retrieval.agent.max_tool_result_chars` characters (default 8,000) per call. `read_document` additionally returns at most `retrieval.agent.max_document_chars` characters (default 8,000) per call. Truncation is traced as a boolean and sets `status: "partial"`. The 30,000-character synthesis cap still applies to the total evidence.

## 3. Risk Mitigations

| Risk | Mitigation |
|---|---|
| Runaway LLM token/cost loops | Hard `max_llm_calls` (3–50), `max_iterations` (0–10), duplicate `(store, query)` deduplication, and `max_concurrency` semaphore returning `503`. |
| Prompt injection via retrieved document text | Never substitute vector text into SQL queries; pair tool results cleanly in `tool` role messages; cap synthesis context at 30,000 chars. |
| Hallucinated document citations | Post-validate citations against retrieved `document_id`s; omit unresolved names. |
| Agent bypasses Phase 1 access controls (ACL-protected sets, SQL kill-switch, SQL allowlist) through model-chosen tools | Tools share the Phase 1 authorization boundary (D3): ACL-protected sets expose only filtered OpenSearch passage search, DuckDB-backed tools honor `retrieval.sql.enabled`, and direct SQL uses the Phase 1 allowlist validator and `DuckDBConnectionManager`. |
| Oversized tool results inflate prompts and leak bulk data to the model | Per-tool row and character caps (D5) with traced truncation. |
| Model claims tool support but returns malformed JSON/tool calls | Bounded `json_retries` (default 1) within call budget; fall back to `status: "partial"` on invalid output. |
