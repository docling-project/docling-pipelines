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
- **D3. Shared authorization boundary**: Every tool in `tools.py` operates strictly on the `LibraryDescriptor` already resolved and ACL-checked by `LocalDocumentLibraryCatalogAdapter` and `RetrievalACLPort`. Model arguments cannot pass connection strings, file paths, or foreign library/set IDs.
- **D4. Safe traces**: `trace.py` records only step index, mode (`plan` | `tool`), tool/action name, chosen store, hit/row counts, verdict, and duration — never raw tool arguments, generated SQL, or retrieved document text.

## 3. Risk Mitigations

| Risk | Mitigation |
|---|---|
| Runaway LLM token/cost loops | Hard `max_llm_calls` (3–50), `max_iterations` (0–10), duplicate `(store, query)` deduplication, and `max_concurrency` semaphore returning `503`. |
| Prompt injection via retrieved document text | Never substitute vector text into SQL queries; pair tool results cleanly in `tool` role messages; cap synthesis context at 30,000 chars. |
| Hallucinated document citations | Post-validate citations against retrieved `document_id`s; omit unresolved names. |
| Model claims tool support but returns malformed JSON/tool calls | Bounded `json_retries` (default 1) within call budget; fall back to `status: "partial"` on invalid output. |
