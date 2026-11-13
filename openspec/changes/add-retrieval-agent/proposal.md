# Proposal

## Why

`add-retrieval-service` runs one fixed pass: query every store, return the results. A question such as "which overdue purchase orders have contracts with penalty clauses?" needs a decision about which store to use, a look at the first result, and often a second, narrower lookup. A fixed pass cannot do that.

retrieval-v2 added exactly this in three stacked PRs (jjojo/retrieval-v2 #30 plan mode, #32 native tool mode, #33 SQL hardening). Their measurements on a held-out split (483 questions, gpt-oss-120b on watsonx) show tool mode raising correctness from 0.64 to 0.75 (procurement) and 0.57 to 0.69 (MACCROBAT), at +13 s to +14 s latency, and abstaining worse on MACCROBAT (0.75 down to 0.47). Plan mode is faster. Neither is strictly better, so both modes ship, selectable.

The SQL hardening from #33 is already part of `add-retrieval-service`. This change adds the agent on top of it.

**Layer:** backend-only.

**Affected REST routes:** `POST /api/v1/retrieval/agent-search-jobs`, `GET /api/v1/retrieval/agent-search-jobs/{query_id}` (these replace the 501 stubs from `add-retrieval-service`).
**Affected operators:** none.
**Affected storage adapters:** none new; the agent calls the retrieval engine services only.

## What Changes

- **Agent runner** (application layer) with three modes: `plan` (prepare, plan, retrieve in dependency waves, evaluate, refine, synthesize), `tool` (the model calls read-only tools and reads each result), and `auto` (tool when the model supports function calling, otherwise plan). Default mode is `plan`.
- **Bounded runs.** Maximum refinement rounds, maximum agent LLM calls with one reserved for synthesis, tool-call cap, concurrency cap, and a deadline with time reserved for synthesis. Request overrides can only lower operator limits. On exhaustion the agent synthesizes from the evidence so far and returns `status: "partial"`; a deterministic evidence summary is used if synthesis is impossible.
- **Five read-only tools** scoped to the prepared library: `describe_library`, `describe_table`, `query_table` (exactly one of `question` or `sql`), `column_values`, `search_passages`. Arguments are validated, unknown fields rejected, numeric bounds clamped, results bounded.
- **Direct SQL** in `query_table(sql=...)` goes through `validate_and_authorize` against only the selected document set's tables, with no generation call and safe diagnostics returned to the model.
- **Safe dependency substitution** for plan mode: values from an upstream SQL result enter a dependent sub-question only through a capped, cleaned, quote-doubled rendering.
- **Evidence handling.** Retrieved text is untrusted data inside delimited evidence blocks. Zero-row SQL success is kept as an observation. Citations use `[document_id: ...]`; unknown or ambiguous citations are removed.
- **Structured step trace** and budget report in `additional_info`, containing no tokens, row values, excerpt text or generated SQL.
- **Dedicated agent job queue** with a concurrency cap, 503 when full, owner-only polling, and generic error bodies. Agent responses are never cached; `disable_cache`, `evaluate` and `search_config` are ignored.
- **Tool-calling LLM port.** A new optional `LLMToolChatPort` (`chat_tools`, `supports_tool_calling`) implemented by the LiteLLM adapter. Adapters without it force plan mode.
- **Configuration** `retrieval.agent.*` (enabled, mode, budgets, concurrency) with `AGENT_ENABLED` as the master switch.

No **BREAKING** changes. The agent is off by default.

## Capabilities

### New Capabilities

- `backend/retrieval-agent`: modes and mode selection, budgets, plan-mode steps, tool mode and tools, substitution, evidence and citation rules, status rules, trace, degraded behavior.
- `backend/retrieval-agent-api`: submit and poll routes, availability, ownership, queue behavior, response additions, and what is ignored.

### Modified Capabilities

None.

## Dependencies on other changes

- `add-retrieval-service` (engine, SQL path, job queue pattern, config, error codes, auth) and, through it, `add-document-library-derivatives`.
- Role-based access (`require_role`) when that change exists; until then `get_current_user`.

## Non-goals

- No thinking arm (strategy turn, result review, coverage self-check). Its benefit is unmeasured here; revisit after the evaluation harness exists.
- No document text tools (`list_documents`, `read_document`, `find_documents`). They need a verified document-text store and an access model for document tables that docpipe's document sets do not define yet.
- No stored-spelling (literal) check and no document-class context in text-to-SQL; `column_values` covers the common case.
- No sessions, memory across requests, streaming, checkpointing, or human-in-the-loop.
- No agent-side planning across Document Sets beyond naming one set per tool call.
- No new vector or SQL backends, no Presto/Iceberg, no change to reranker or embedding internals.
- No ACL filtering of entity rows (same limitation as `add-retrieval-service`).
- No OpenAI-compatible provider work; providers come through LiteLLM.
- No port of the retrieval-v2 substitution helper's backslash escaping.
- No quality benchmark claims. The retrieval-v2 numbers above are cited as context, not as results for docpipe.

## Impact

- New: `src/docpipe/core/retrieval/agent/{domain,application}/`, `src/docpipe/core/ports/llm_tool_chat_port.py`, LiteLLM adapter extension, agent routes and DTOs in `api/`, config keys, error codes.
- Changed: `retrieval_factory.py`, `dependencies.py`, `error_codes.py`.
- Dependencies: none new (LiteLLM already present). Any `pyproject.toml` change is followed by `uv lock`.
- Docs: agent section in `docs/guides/RETRIEVAL_GUIDE.md`.
- Cost: an agent run makes several LLM calls instead of one: plan mode `2R + 3` for `R` refinement rounds plus JSON retries; tool mode up to the call budget (default 10).
