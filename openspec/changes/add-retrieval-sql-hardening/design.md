# Design: Retrieval SQL Hardening & Diagnostics (Phase 2)

## 1. Module Placement (DDD)

```text
src/docpipe/core/retrieval/
├── domain/models/query.py                 # Populates ResultMetadata.literal_check / literal_check_skipped / sql_error
├── application/sql_retriever.py           # Feeds structured error feedback into correction prompt; runs post-exec literal probe
└── adapters/sql/
    ├── duckdb_sql_engine.py               # Uses classified errors + exposes value/content helpers
    ├── engine_errors.py                   # Exception -> sanitized SqlErrorDiagnostic mapper
    ├── error_feedback.py                  # Formats structured correction hints from SqlErrorDiagnostic + schema
    ├── literal_check.py                   # sqlglot AST predicate extractor + bounded DuckDB ILIKE/LOWER probe
    ├── value_query.py                     # Scoped distinct column-value frequency query builder (sqlglot AST)
    └── content_search.py                  # Literal substring document text search with keyset paging (no OFFSET)
```

## 2. Key Decisions

- **D1. Bounded, informational literal checks**: Extract string equality/`IN` predicates on text columns from the executed `sqlglot` AST (`WHERE`/`HAVING`). Cap probes per query (default 5 literals) and enforce a bounded probe timeout (`min(literal_check_timeout_seconds, max(5, sql_timeout_seconds))`, default cap 30s). Generate every probe query via `sqlglot` AST (`duckdb` dialect) with parameter binding so literal values never interpolate raw SQL.
- **D2. Path-free sanitized diagnostics**: `engine_errors.py` maps DuckDB `CatalogException`, `BinderException`, `ParserException`, `ConversionException`, `InterruptException`, and `IOException` to structured categories (`missing_column`, `missing_table`, `syntax_error`, `type_mismatch`, `timeout`, `unavailable`), stripping absolute file paths before logging or returning `sql_error`.
- **D3. Keyset-paged literal content search**: `content_search.py` escapes `%`, `_`, and `\` (or uses DuckDB `strpos`/`contains`) so wildcards and quotes match literally, orders by `document_id > :after_document_id`, and extracts up to 3 short snippets per document with 0-based character offsets.

## 3. Risk Mitigations

| Risk | Mitigation |
|---|---|
| Literal probe slows down fast SQL queries | Cap probe count and probe budget; skip on timeout and record in `literal_check_skipped` without failing the SQL result. |
| Local filesystem paths leaked in DuckDB `IOException` | Classify errors by type and regex-scrub paths in `engine_errors.py` before emitting `sql_error` or logs. |
| SQL injection via `column_values` or `find_documents` inputs | Validate table/column identifiers strictly against the authorized `DocumentSet` schema allowlist and bind search text as parameters. |
