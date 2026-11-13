# Tasks

Depends on `add-retrieval-service` (engine, SQL path, queue, config) being merged.

## 1. Foundations

- [ ] 1.1 [backend] Add `retrieval.agent.*` config (`enabled`, `mode`, budgets, `max_concurrency`, `json_retries`) and `AGENT_ENABLED` handling
- [ ] 1.2 [backend] Add error codes (`RETRIEVAL_AGENT_DISABLED`, `RETRIEVAL_AGENT_UNSUPPORTED_MODEL`) and exceptions
- [ ] 1.3 [backend] Add agent domain models (`AgentRun`, `SubQuestion`, `Evidence`, `TraceEntry`, `BudgetReport`, `AgentMode`)
- [ ] 1.4 [backend] Add `LLMToolChatPort` (`chat_tools`, `supports_tool_calling`, `ToolCall`, `ToolChatResult`) without changing `LLMInferencePort`
- [ ] 1.5 [backend] Implement the port in the LiteLLM adapter with provider-neutral tools and cached capability lookup; tests with mocked LiteLLM

## 2. Pure helpers

- [ ] 2.1 [backend] Implement `Budget` (calls, tools, rounds, deadline, synthesis reserve, time reserves, clamped overrides) and tests
- [ ] 2.2 [backend] Implement topological waves and cycle detection and tests
- [ ] 2.3 [backend] Implement substitution (cap 20 values, 64 chars, control chars removed, quotes doubled, whole-label matching, truncation flag) and tests incl. apostrophes and `$var_1` vs `$var_10`
- [ ] 2.4 [backend] Implement `TraceRecorder` with token scrubbing and tests
- [ ] 2.5 [backend] Implement validated JSON call helper with retry inside the budget and tests

## 3. Shared engine seam

- [ ] 3.1 [backend] Add `SearchService.search_stores` (no cache, no summary, no evaluate; same ACL and SQL path) and tests that ACL and partial results still apply
- [ ] 3.2 [backend] Implement `Synthesizer`: dedupe, context cap with shown-of-total notice, delimited evidence, citation filtering, deterministic fallback, unanswerable detection, SQL-versus-document disagreement wording

## 4. Plan mode

- [ ] 4.1 [backend] Implement the plan step with validation (unknown label, cycle, empty `ref_column`, vector-only upstream) and fallback
- [ ] 4.2 [backend] Implement the retrieve step in waves with skip-on-empty-upstream and partial marking
- [ ] 4.3 [backend] Implement evaluate and refine with duplicate-attempt detection and evidence retention
- [ ] 4.4 [backend] Tests: dependent and independent waves, empty upstream, invalid plan fallback, refinement keeps evidence, invalid evaluation and refinement degrade to `partial`

## 5. Tool mode

- [ ] 5.1 [backend] Implement `ToolRegistry` with argument models (extra forbidden, clamping), set selection by id or unambiguous name
- [ ] 5.2 [backend] Implement `describe_library` and `describe_table` (metadata only, never evidence)
- [ ] 5.3 [backend] Implement `query_table` (exactly one of `question`/`sql`; direct SQL through `validate_and_authorize` for the selected set only; no correction model call; zero-row note)
- [ ] 5.4 [backend] Implement `column_values` (sqlglot builder from validated identifiers, wildcard-safe filter, authorization)
- [ ] 5.5 [backend] Implement `search_passages` (document id narrowing up to 100, empty list matches nothing, ACL via `search_stores`)
- [ ] 5.6 [backend] Implement `ToolDriver` loop (batch concurrency, identical call dedupe, call-id pairing, tool cap, exploration time reserve, generic errors) and result bounds (12,000 / 8,000 / 50)
- [ ] 5.7 [backend] Tests: unknown tool, invalid args, both/neither of question and sql, SQL outside the set, empty id list, bounds clamped, duplicates run once

## 6. Runner and API

- [ ] 6.1 [backend] Implement `AgentRunner` (prepare without LLM, mode selection incl. `auto` lookup failure, status rules, budget report, fallback)
- [ ] 6.2 [backend] Add the agent job queue instance (reject when full, concurrency cap, redacted errors) and wiring in `retrieval_factory.py`
- [ ] 6.3 [backend] Add DTOs, mapper, and routes `agent-search-jobs` submit/poll replacing the 501 stubs; DI providers
- [ ] 6.4 [backend] API tests: 202, 422 (`max_llm_calls` < 3, target rules), 404 for other user, 500 fixed message, 503 queue full, 501 disabled, 401, ignored `search_config`/`disable_cache`, `include_sql` behavior
- [ ] 6.5 [backend] Security tests: restricted chunk via both modes, prompt-injection text in a chunk does not reach SQL or change tool arguments, no token/row/SQL in trace and logs

## 7. Evaluation gate

- [ ] 7.1 [backend] Add an offline evaluation script and small fixture set comparing fixed search, plan, and tool mode on correctness and latency; record results in the guide before recommending `auto` (no default change without data)

## 8. Docs

- [ ] 8.1 [backend] Add the agent section to `docs/guides/RETRIEVAL_GUIDE.md` (modes, budgets, tools, cost formula, limitations, non-goals)

## 9. Validation

- [ ] 9.1 [backend] `uv run ruff check --fix .`
- [ ] 9.2 [backend] `uv run mypy .`
- [ ] 9.3 [backend] `uv run pytest tests/unit -m "unit and not integration"`
- [ ] 9.4 [backend] `openspec validate add-retrieval-agent --strict`
