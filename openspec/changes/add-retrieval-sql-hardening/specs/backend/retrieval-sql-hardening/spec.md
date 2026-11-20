# backend/retrieval-sql-hardening Specification

## Purpose

Defines post-execution SQL literal-spelling probes, sanitized DuckDB error classification and self-correction feedback, and read-only column-value and document-text search helpers for the Docling Pipelines retrieval engine.

## ADDED Requirements

### Requirement: Executed SQL literal checks
After an authorized DuckDB SQL query executes, the engine SHALL run bounded, information-only case-insensitive probes for eligible string literals in text-column comparisons in `WHERE` or `HAVING` without modifying or rerunning the original SQL.

#### Scenario: Alternate spellings reported after execution
- **WHEN** an executed text predicate has fewer exact matches than its bounded case-insensitive probe
- **THEN** `ResultMetadata.literal_check` includes the column, written literal, matching stored spellings with row counts, and a plain explanation, while the SQL rows remain unchanged

#### Scenario: Exact and case-insensitive results agree
- **WHEN** the probe finds no additional matching rows or spellings
- **THEN** no `literal_check` entry is added and the SQL result is unchanged

#### Scenario: Probe budget exceeded or probe fails
- **WHEN** the literal count bound is exceeded, the probe times out, or the probe errors
- **THEN** the engine records the skipped literal in `ResultMetadata.literal_check_skipped` and returns the original SQL result intact

### Requirement: Sanitized SQL error diagnostics and correction feedback
The engine SHALL classify DuckDB execution errors into sanitized diagnostic categories (never leaking local file paths or credentials) and pass structured schema-aware hints into `SqlRetriever`'s self-correction prompt.

#### Scenario: Missing column error produces actionable feedback
- **WHEN** DuckDB raises a binder error for an unknown column and retries remain
- **THEN** `error_feedback` passes the sanitized error category and valid schema columns to the correction prompt

#### Scenario: Terminal SQL failure records sanitized sql_error
- **WHEN** retries are exhausted on a DuckDB error
- **THEN** `ResultMetadata.sql_error` contains the sanitized diagnostic category and message with no local filesystem paths

### Requirement: Scoped read-only column value lookup
The engine SHALL provide a read-only `column_values` helper returning distinct stored values with row counts (most frequent first) for a single allowlisted table and column, with optional case-insensitive substring filter and row limit.

#### Scenario: Distinct values returned most frequent first
- **WHEN** `column_values` is called for an authorized table and column with `limit=10`
- **THEN** it returns at most 10 distinct values ordered by descending row count

#### Scenario: Unknown table or column rejected without execution
- **WHEN** `column_values` is called with a table or column not in the authorized `DocumentSet` schema
- **THEN** it raises a validation error without executing any DuckDB query

### Requirement: Helpers and probes honor the Phase 1 access and authorization boundary
Literal-spelling probes, `column_values`, and `find_documents` SHALL execute under the same DuckDB access mode, connection hardening, resource limits, timeout, and `max_rows` cap as Phase 1 SQL retrieval, and SHALL NOT be available for ACL-protected document sets (`acl_protected` true from the derivative resolver), because DuckDB tables cannot enforce per-document ACLs.

#### Scenario: Helpers and probes unavailable for ACL-protected document sets
- **WHEN** `column_values`, `find_documents`, or a literal-spelling probe targets an ACL-protected document set
- **THEN** the helper refuses with a generic unavailable error (or the probe is skipped), no DuckDB query is executed, and no stored values or snippets are returned

#### Scenario: Helper results respect the row cap and lock budget
- **WHEN** `column_values` or `find_documents` is called in `locked` access mode and the per-file lock is not acquired within `retrieval.sql.lock_timeout_seconds`
- **THEN** the helper fails with a sanitized `unavailable` error and does not block ingestion

### Requirement: Keyset-paged literal document text search
The engine SHALL provide a read-only `find_documents` helper that searches stored document text in an authorized DuckDB table for a literal substring (case-insensitive by default), treating `%`, `_`, and quotes literally and paging by `after_document_id` with no `OFFSET` clause.

#### Scenario: Literal substring matches return snippets and offsets
- **WHEN** `find_documents` searches for a substring present in stored documents
- **THEN** each match includes `document_id`, document name, match count, and up to three snippets with 0-based character offsets

#### Scenario: Wildcards and quotes match literally
- **WHEN** the search text contains `%`, `_`, or single/double quotes
- **THEN** those characters match only themselves and cannot alter query structure

#### Scenario: Keyset pagination returns cursor when more matches exist
- **WHEN** more than `limit` documents match after `after_document_id`
- **THEN** the result sets `more_available: true` and `next_after_document_id` to the last returned `document_id`
