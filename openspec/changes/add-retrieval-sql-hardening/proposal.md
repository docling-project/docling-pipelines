# Proposal: Retrieval SQL Hardening & Diagnostics (Phase 2)

## Why

Phase 1 (`add-retrieval-service`) introduces safe DuckDB Text-to-SQL with `sqlglot` read-only validation, table allowlisting, timeout/cancellation, and a retry loop. In production RAG over extracted document tables, however, three recurring failure modes degrade SQL answer quality:
1. **Case/spelling mismatches**: Exact string predicates (`WHERE vendor = 'Acme'`) silently return 0 rows when the table stores `'ACME Corp.'`.
2. **Opaque or unsafe engine errors**: Raw driver exceptions can either leak local file paths or give the self-correction LLM unhelpful stack traces instead of structured, actionable error categories.
3. **Missing direct table inspection primitives**: Downstream consumers (and Phase 4's tool-mode agent) need bounded, read-only helpers to inspect distinct column values and search stored document text without hand-writing arbitrary SQL.

This change ports `retrieval-v2`'s SQL hardening capabilities (`add-literal-check`, `er0-safe-engine-diagnostics`, `item2b-sql-error-feedback`, `query-table-direct-sql`) natively onto `DuckDBSqlEngine` and `SqlRetriever`.

**Layer:** `backend-only`. Extends `src/docpipe/core/retrieval/` (`application/` and `adapters/sql/`) and `ResultMetadata` fields (`literal_check`, `literal_check_skipped`, `sql_error`). No REST route paths change and no frontend changes are included.

## What Changes

- **Executed SQL literal checks**: After an authorized SQL query executes against DuckDB, inspect eligible string-literal predicates in `WHERE` / `HAVING` via bounded, `sqlglot`-generated case-insensitive probes and attach matching stored spellings + row counts to `ResultMetadata.literal_check` (or record skips in `literal_check_skipped`) without rewriting or rerunning the user's SQL.
- **Safe engine diagnostics & structured SQL error feedback**: Classify DuckDB errors (syntax, missing column/table, type mismatch, timeout/cancelled, permission/access) into sanitized diagnostic codes (`sql_error` in `ResultMetadata`) that strip local filesystem paths and feed targeted hints into `SqlRetriever`'s self-correction loop.
- **Direct read-only table helpers**: Add scoped, `sqlglot`-AST-built helpers on `DuckDBSqlEngine` for:
  - `column_values(table, column, substring, limit)`: distinct stored values with frequency counts, most frequent first.
  - `find_documents(table, text, case_sensitive, limit, after_document_id)`: literal substring search over stored document text with keyset paging (no `OFFSET`), returning `document_id`, name, match count, and up to 3 snippets with 0-based character offsets.

## Capabilities

### New Capabilities
- `backend/retrieval-sql-hardening`: Executed SQL literal-spelling probes, sanitized engine error classification and self-correction feedback, and read-only DuckDB column-value and keyset-paged document text search helpers.

## Non-goals

- Presto, PostgreSQL, or OpenSearch SQL dialects (DuckDB only in this change).
- Automatically rewriting or re-executing the user's SQL query when literal checks find alternate spellings (literal checks are informational only).
- Exposing new HTTP endpoints (the new helpers are internal application/adapter capabilities consumed by `SqlRetriever` and Phase 4's agent tools).
- Frontend UI changes.

## Impact

- **Core modules**: Adds `literal_check.py`, `error_feedback.py`, `engine_errors.py`, `value_query.py`, and `content_search.py` under `src/docpipe/core/retrieval/adapters/sql/`; updates `SqlRetriever` and `ResultMetadata`.
- **REST routes**: None added; `ResultMetadata` already reserves `literal_check`, `literal_check_skipped`, and `sql_error` fields from `retrieval-v2`.
- **Tests**: Unit tests under `tests/unit/core/retrieval/sql/` against real temporary DuckDB databases.
