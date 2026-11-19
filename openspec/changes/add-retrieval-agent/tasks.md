# Tasks: Opt-in Agentic Retrieval Service (Phase 4)

All tasks are `[backend]` and scoped to <= 2 hours each. Depends on `add-retrieval-service` and `add-retrieval-sql-hardening`.

- [ ] 1.1 `[backend]` Define `ToolCallingLLMPort` (`chat_tools`, `supports_tools`) in `src/docpipe/core/ports/tool_calling_llm_port.py` and implement it in `InferenceBridge` for Ollama, LiteLLM/OpenAI-compatible, and Watsonx adapters.
- [ ] 1.2 `[backend]` Add `retrieval.agent.*` configuration keys (`enabled`, `mode`, `tool_models`, `tool_thinking`, `max_iterations`, `max_llm_calls`, `deadline_seconds`, `max_concurrency`, `json_retries`) to `docling-pipelines-config.yaml.example` and `retrieval/factories/config.py`.
- [ ] 1.3 `[backend]` Implement `budget.py`, `state.py`, `trace.py`, `llm_json.py`, and `substitution.py` under `src/docpipe/core/retrieval/agent/`.
- [ ] 1.4 `[backend]` Implement plan-mode driver (`steps.py`, `prompts.py`) with intent routing, DAG decomposition, safe SQL substitution, sufficiency evaluation, duplicate-guarded refinement, and grounded synthesis (30,000-char cap, citation validation).
- [ ] 1.5 `[backend]` Implement authorized read-only tools (`tools.py`, `tool_retrieval.py`, `tool_documents.py`) bridging DuckDB (`column_values`, `find_documents`, `list_documents`, `read_document`, `query_table`) and Milvus/OpenSearch/Weaviate (`search_passages`).
- [ ] 1.6 `[backend]` Implement native tool-calling loop (`tool_loop.py`), optional `tool_thinking.py`, and `AgentRunner` (`runner.py`) with concurrency semaphore and mode selection.
- [ ] 1.7 `[backend]` Add `AgentQueryRequest`, `AgentTraceEntry`, and `AgentBudgetUsage` DTOs in `retrieval_dto.py` and expose `POST /v2/retrieval/agent/search` and `GET /v2/retrieval/agent/search/result/{query_id}` in `routes/retrieval.py` (`501` when disabled, `503` when full, never cached).
- [ ] 1.8 `[backend]` Add unit and API tests in `tests/unit/core/retrieval/agent/` and `tests/unit/api/routes/test_retrieval_agent.py`, then run `ruff`, `mypy`, `pytest`, and `openspec validate add-retrieval-agent --strict`.
