# Tasks: Retrieval SQL Hardening & Diagnostics (Phase 2)

All tasks are `[backend]` and scoped to <= 2 hours each. Depends on `add-retrieval-service`.

- [ ] 1.1 `[backend]` Implement `engine_errors.py` and `error_feedback.py` under `src/docpipe/core/retrieval/adapters/sql/` to classify DuckDB exceptions, scrub local paths, and format schema-aware correction hints.
- [ ] 1.2 `[backend]` Implement `literal_check.py` using `sqlglot` (`duckdb` dialect) AST extraction and bounded parameterized case-insensitive probes, populating `ResultMetadata.literal_check` and `literal_check_skipped`.
- [ ] 1.3 `[backend]` Wire `error_feedback` and `literal_check` into `SqlRetriever` (`application/sql_retriever.py`) and add config keys `retrieval.sql.literal_check_timeout_seconds` and `retrieval.sql.literal_check_max_literals`.
- [ ] 1.4 `[backend]` Implement `value_query.py` (`column_values`) and `content_search.py` (`find_documents` with keyset paging and literal matching) using `sqlglot` AST generation and `DuckDBSqlEngine`.
- [ ] 1.5 `[backend]` Add unit tests in `tests/unit/core/retrieval/sql/` against temporary DuckDB databases covering literal checks, error scrubbing/feedback, `column_values`, and `find_documents` (wildcards, quotes, keyset paging).
- [ ] 1.6 `[backend]` Run `uv run ruff check --fix .`, `uv run mypy .`, `uv run pytest tests/unit/core/retrieval/sql/ -v`, and `openspec validate add-retrieval-sql-hardening --strict`.
