# Proposal: Opt-in Agentic Retrieval Service (Phase 4)

## Why

Single-pass hybrid search (Phase 1) works well for direct questions, but multi-hop analytical questions (e.g., *"Which vendor has the highest invoice total and what do their contracts say about termination?"*) require iterative decomposition, cross-checking SQL aggregations against document excerpts, and refining queries when initial evidence is insufficient.

`retrieval-v2` solves this with a bounded, stateless opt-in retrieval agent (`POST /v2/retrieval/agent/search` + `GET /v2/retrieval/agent/search/result/{query_id}`) supporting both **plan mode** (for any LLM) and **native tool mode** (with optional **tool thinking** for tool-capable models), while strictly enforcing call/iteration/deadline budgets and safe traces. This change brings that exact agentic retrieval contract natively into Docling Pipelines over DuckDB, Milvus, OpenSearch, and Weaviate.

**Layer:** `backend-only`. Adds `ToolCallingLLMPort` (`chat_tools`) in `src/docpipe/core/ports/`, adds `src/docpipe/core/retrieval/agent/`, extends `retrieval:` config with `retrieval.agent.*`, and exposes `/v2/retrieval/agent/search` and `/v2/retrieval/agent/search/result/{query_id}` in `src/docpipe/api/routes/retrieval.py`. No frontend changes are included.

## What Changes

- **Provider-neutral tool-calling port**: Add `ToolCallingLLMPort` (or optional `chat_tools` capability on `LLMInferencePort` adapters for Ollama, LiteLLM/OpenAI-compatible, and Watsonx) returning structured assistant text + tool call records while preserving existing `LLMInferencePort` callers unchanged.
- **Opt-in agentic retrieval engine (`src/docpipe/core/retrieval/agent/`)**:
  - **Modes (`auto` | `tool` | `plan`, default `auto`)**: Selects `tool` mode only when the active model is confirmed tool-capable (via configured allowlist); otherwise falls back to `plan` mode.
  - **Plan mode**: Intent-based routing → DAG decomposition with safe upstream SQL value substitution (max 20 distinct values, 64 chars each, escaped, never vector text) → evidence sufficiency evaluation → bounded non-repeating refinement → grounded synthesis.
  - **Tool mode**: Exposes strictly read-only, library-scoped tools (`describe_library`, `query_table` accepting question OR direct DuckDB SQL validated by the Phase 1 allowlist validator, `column_values`, `search_passages` with optional SQL-derived `document_ids` narrowing, `list_documents`, `find_documents`, `read_document`) powered by Phase 1 & Phase 2 adapters. The agent inherits the Phase 1 authorization model: authentication is required, DuckDB-backed tools are unavailable for ACL-protected document sets and when `retrieval.sql.enabled` is false, and tool results are capped in rows and characters.
  - **Optional tool thinking (`tool_thinking: off | on`, default `off`)**: Adds one short strategy turn, batch result review, and structured coverage check within the existing call/time budget and synthesis reserve.
  - **Budgets & concurrency**: Enforces `max_iterations` (0–10, default 2), `max_llm_calls` (3–50, default 10, with 1 call always reserved for synthesis), soft `deadline_seconds` (default 120s), and `max_concurrency` (default 2, returning `503` when full). Request overrides may only lower configured limits.
  - **Safe traces & citations**: Populates `additional_info.agent_trace` and `additional_info.agent_budget` with safe step metadata (never leaking tool arguments, SQL text, retrieved evidence, or credentials); synthesis cites only retrieved `document_id`s and caps evidence at 30,000 characters.
- **REST API endpoints**:
  - `POST /v2/retrieval/agent/search` → `202 Accepted` `{query_id, status: "pending"}`, `401` unauthenticated, `501` when `retrieval.agent.enabled` is false or no LLM is configured, `503` when concurrency queue is full.
  - `GET /v2/retrieval/agent/search/result/{query_id}` → `202` pending / `200` `QueryResponse` / `404` unknown, expired, or owned by another user / `500` generic error.
  - Agent responses are never cached (`disable_cache`, `evaluate`, `search_config` accepted and ignored).

## Capabilities

### New Capabilities
- `backend/retrieval-agent`: Opt-in bounded agentic retrieval API (`/v2/retrieval/agent/search`), plan and native tool-calling execution modes, authorized read-only retrieval tools, optional tool thinking, budget enforcement, and safe tracing.

## Non-goals

- Adding new external dependencies (agent runs entirely on existing `docpipe` LLM/storage adapters).
- Write or mutating tools (all agent tools are strictly read-only and scoped to the authorized `DocumentLibrary`).
- Caching agent responses or running offline RAGAS scoring inside agent runs.
- Frontend UI / trace viewer components.

## Impact

- **Ports & LLM adapters**: Adds `src/docpipe/core/ports/tool_calling_llm_port.py` and implements `chat_tools` in `InferenceBridge` (Ollama, LiteLLM/OpenAI-compatible, Watsonx).
- **Core modules**: Adds `src/docpipe/core/retrieval/agent/` (`runner.py`, `steps.py`, `tool_loop.py`, `tools.py`, `tool_retrieval.py`, `tool_documents.py`, `tool_thinking.py`, `budget.py`, `state.py`, `trace.py`, `substitution.py`, `llm_json.py`, `prompts.py`).
- **REST routes & DTOs**: Adds `AgentQueryRequest`, `AgentTraceEntry`, `AgentBudgetUsage` in `retrieval_dto.py` and `/v2/retrieval/agent/search` + `/result/{query_id}` in `routes/retrieval.py`.
- **Observability (if Phase 3 installed)**: Emits `docpipe_retrieval_agent_runs_total`, `docpipe_retrieval_agent_run_duration_seconds`, `docpipe_retrieval_agent_iterations`, `docpipe_retrieval_agent_llm_calls`, `docpipe_retrieval_agent_budget_exhausted_total`.
- **Tests**: Unit and API tests under `tests/unit/core/retrieval/agent/` and `tests/unit/api/routes/test_retrieval_agent.py`.
