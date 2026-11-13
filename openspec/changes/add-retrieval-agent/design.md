# Design

## Context

`add-retrieval-service` provides `SearchService` (store queries, partial results, correlation, summary), the SQL path with `validate_and_authorize`, a job queue pattern, config, and errors. This change adds a bounded loop on top. retrieval-v2 implements the same idea (jjojo/retrieval-v2 #30, #32, #33) as plain async functions over a typed state, with no agent framework. docpipe's ports are synchronous, so the same design is written with synchronous steps and the engine's thread pool.

## Goals / Non-Goals

Goals: plan mode and tool mode with shared retrieval, synthesis, SQL path and budget; opt-in; stateless; bounded; safe by construction.
Non-goals: see proposal (thinking arm, document text tools, literal check, class context, sessions).

## DDD layers

```
core/retrieval/agent/
  domain/
    models/        AgentRun (mutable state), SubQuestion, Evidence, TraceEntry, BudgetReport, AgentMode
    ports/         AgentModelPort (JSON chat + tool chat facade over LLM ports)
  application/
    services/
      agent_runner.py       AgentRunner  (prepare -> mode driver -> synthesize -> status)
      budget.py             Budget       (calls, tools, rounds, deadline, reserves)
      plan_driver.py        PlanDriver   (plan, waves, evaluate, refine)
      tool_driver.py        ToolDriver   (tool chat loop)
      tools.py              ToolRegistry (5 tools, schemas, validation, dispatch)
      substitution.py       pure @staticmethods
      waves.py              topological waves (pure)
      llm_json.py           validated JSON calls with retry
      synthesizer.py        Synthesizer  (dedupe, cap, citations, fallback)
      trace.py              TraceRecorder (scrubs token)
core/ports/llm_tool_chat_port.py     LLMToolChatPort (optional)
core/adapters/litellm/               chat_tools, supports_tool_calling
api/routes/retrieval_agent.py, api/dto/retrieval_agent_dto.py
```

The runner depends on `SearchService` methods for store-targeted search (`search_stores`), not on engine adapters. No application code imports adapters. Pure helpers are `@staticmethod`. Multi-parameter functions are keyword-only. Logging via `get_logger()` with `%s`.

## Decisions

### D1. Plan default, tool opt-in
retrieval-v2 defaults to `auto`, which silently switches models with function calling to tool mode on deploy and also changes the SQL path. Its own evidence is mixed: tool mode is more correct but 13 to 14 s slower and abstains worse on one dataset. docpipe defaults to `plan`; operators opt into `tool` or `auto`.

### D2. Shared `search_stores`
Add `SearchService.search_stores(*, stores, query, context)` that runs a chosen set of stores with the full engine behavior (ACL, partial results, SQL path) but without cache, summary, or evaluate. Plan retrieval, `query_table(question=)`, and `search_passages` call it. This keeps one SQL path and one ACL path.

### D3. Synchronous steps, thread pool
Sub-questions in a wave run on a bounded `ThreadPoolExecutor(max_concurrency)`. Each LLM call and tool call is bounded by `min(remaining_time, per_call_limit)`. The context passes the deadline as an absolute monotonic instant; the SQL engine already receives it (`add-retrieval-service` D8a), so an abandoned wait cancels the running statement.

### D4. Budget
`Budget` counts agent LLM calls only. `reserve_for_synthesis` blocks any non-synthesis call (including JSON retries) when one call remains. Tool invocations are capped at `3 * max_llm_calls` and count duplicates and cached results. Time reserves per spec. Request overrides are clamped with `min(requested, operator_max)`.

### D5. Validated JSON steps
Every LLM JSON step (plan, evaluate, refine) is validated against a Pydantic model, rejects stores the library does not offer, and retries within the budget. Failures degrade per the spec instead of failing the run.

### D6. Tools
Five tools only. Schemas are plain JSON schemas generated from Pydantic argument models with `extra = forbid`. `query_table(sql=)` calls `validate_and_authorize` with the selected set's tables and then the engine, bypassing generation. `column_values` builds its statement with sqlglot from validated identifiers (identifier must exist in the set's described columns), then also goes through `validate_and_authorize`. Set selection accepts an id or an unambiguous case-insensitive exact name; ambiguity returns a generic error.

### D7. Quote handling
Upstream values are inserted into a natural-language sub-question for text-to-SQL, not into SQL text. They are still cleaned and quotes are doubled (`'` to `''`), because retrieval-v2's backslash escaping breaks on Presto and ANSI SQL and a doubled quote reads correctly to the model. The resulting SQL is separately validated and authorized.

### D8. Evidence and prompts
Evidence is wrapped in delimited blocks with a fixed notice that the content is data. Replies are validated, never executed. Retrieved text never reaches SQL generation except through the capped substitution. Zero-row SQL success is kept as an observation; errored SQL is not. The synthesis prompt asks to report material SQL versus document disagreements as unresolved.

### D9. Tool-calling port
`LLMToolChatPort.chat_tools(*, messages, tools, model_name, **kwargs) -> ToolChatResult(text, tool_calls[ToolCall(id, name, arguments)])` and `supports_tool_calling(*, model_name) -> bool`. The LiteLLM adapter implements both using the provider-neutral `tools` argument; `supports_tool_calling` uses LiteLLM's model capability helper and caches by model. The existing `LLMInferencePort` is not changed.

### D10. Queue and API
A second `InProcessJobQueue` instance configured with `reject_when_full`, `max_concurrency`, and `redact_errors`. Poll returns a fixed generic message on error. Ownership by `User.username`. Responses are not cached. The submit route also validates that the agent is enabled before queueing.

### D11. Trace privacy
`TraceRecorder` stores labels, templates, outcomes, counts and timings only, and scrubs the caller's token from every string. Row values, excerpts, and generated SQL never enter the trace or events.

### D12. Status
Computed once in the runner from flags set by steps: skipped, store failed, fallback taken, limit hit, partial synthesis, unanswerable text.

## Risks and trade-offs

| Risk | Mitigation |
|---|---|
| Latency and cost from many LLM calls | Opt-in, budgets, default `plan`, budget report shown |
| Prompt injection from chunk text or entity values | Delimited evidence, validated replies, no tool with write effect, SQL always through `validate_and_authorize`, values capped |
| Agent bypasses ACL | All retrieval goes through `search_stores`; test with restricted chunk through both modes |
| Direct SQL by the model | Same authorization as generated SQL, only selected set's tables, read-only engines |
| Tool-call support differs per provider/model | Capability check, forced `plan` on lookup failure, normalization in adapters |
| Starving normal search | Dedicated queue and concurrency cap |
| Quality claims not transferable | Numbers cited as context only; add an evaluation task before enabling by default |
| Runaway run | Hard budgets, reserved synthesis, deadline reserves, statement cancellation |
| Entity rows not ACL-filtered | Same documented limitation; `retrieval.sql.enabled=false` disables SQL for agent too |

## Rollout

Flag `AGENT_ENABLED=false` by default. Order: `add-document-library-derivatives`, `add-retrieval-service`, then this change. Rollback: flag off.

## Open questions

None blocking. Assumptions recorded: D1 default mode, D3 sync design, D6 five-tool scope, D9 port shape.
