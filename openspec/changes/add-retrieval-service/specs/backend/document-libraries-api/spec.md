# Spec Delta: backend/document-libraries-api

## Purpose

Adds a read-only derivatives view (`GET /api/v1/document-libraries/{library_id}/derivatives`) to the existing `document-libraries-api` capability so callers can inspect the credential-free vector store and SQL table derivatives resolved for each document set in a library.

## ADDED Requirements

### Requirement: List derivatives of a document library
`GET /api/v1/document-libraries/{library_id}/derivatives` SHALL return a `DocumentLibraryDerivativesResponse` with `total_count`, `limit`, `next` (opaque bookmark or null), and `documentset_derivatives` ordered by `document_set_ids`. Each entry SHALL contain `id`, `name`, and `derivative_stores` (`vector_stores`, `entity_tables`, `correlation_details`) resolved from `DataCard`, DuckDB attachments, and optional overrides. Unknown IDs SHALL return 404; malformed UUIDs SHALL return 400.

#### Scenario: Library with resolved derivatives
- **WHEN** `GET /api/v1/document-libraries/{library_id}/derivatives` is called for a library whose document sets have DuckDB tables and `DataCard` vector store derivatives (`milvus`, `opensearch`, or `weaviate`)
- **THEN** the response is 200 with each entry containing its `vector_stores`, `entity_tables`, and `correlation_details`

#### Scenario: Document set without derivatives returns empty lists
- **WHEN** a library contains a document set with no DuckDB table and no vector store derivative
- **THEN** its entry is returned with `vector_stores`, `entity_tables`, and `correlation_details` all empty

#### Scenario: Unknown library returns 404
- **WHEN** `GET /api/v1/document-libraries/{unknown_id}/derivatives` is called
- **THEN** the response is 404 with code `document_library_not_found`

#### Scenario: Library without document sets
- **WHEN** the library has no associated document sets
- **THEN** the response is 200 with `total_count` 0, `next` null, and an empty `documentset_derivatives` list

### Requirement: Derivatives pagination and platform query parameter tolerance
The endpoint SHALL accept `limit` (integer 1–1000, default 100), opaque `bookmark`, and optional `container_id` and `container_type` (accepted and ignored for client compatibility). Invalid or out-of-range `bookmark` values SHALL return 400 with code `derivative_invalid_bookmark`; out-of-range `limit` values SHALL return 400.

#### Scenario: Paginating through document set derivatives
- **WHEN** a library has 5 document sets and a client requests `limit=2`, then repeats with `bookmark=<next>`
- **THEN** the first two pages return 2 entries each with non-null `next`, and the final page returns 1 entry with `next` null

#### Scenario: Invalid bookmark returns 400
- **WHEN** a client sends `bookmark=not-a-valid-bookmark`
- **THEN** the response is 400 with code `derivative_invalid_bookmark`

#### Scenario: Container query parameters tolerated
- **WHEN** a client sends `container_id=proj-1&container_type=project`
- **THEN** the response is identical to calling without those parameters

### Requirement: Derivatives response redaction and authentication
The endpoint SHALL require authentication via `get_current_user` and SHALL NEVER include passwords, tokens, API keys, `${VAR}` or `vault://` references, connection strings, or local filesystem / DuckDB `database_path` values in the response body.

#### Scenario: Credentials and database paths are redacted
- **WHEN** a library's document sets reference a file-backed DuckDB table and a vector store configured with credentials or `$VAR` references
- **THEN** `entity_tables` reports `backend: "duckdb"` without any filesystem path, and `vector_stores` omits all secrets, tokens, and connection strings
