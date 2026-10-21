# backend/document-sets-api Specification

## Purpose

The document-sets-api capability manages document sets — named, persistent collections of processed document rows stored in DuckDB. A document set is the output storage target for pipeline runs: operators such as `DocumentSetOperator` and `StorageOutputOperator` write their pyarrow Table results into a named document set. The API provides idempotent creation, retrieval, listing, metadata updates, deletion, and a paginated data preview endpoint.

## Requirements

### Requirement: Create or retrieve a document set (idempotent)
`POST /api/v1/document-sets` SHALL implement an idempotent get-or-create pattern: returning existing records or creating a new record with a generated UUID, always returning status 201 for safe repeated invocations.

#### Scenario: New document set created
- **WHEN** `POST /api/v1/document-sets` is called with a name that does not yet exist
- **THEN** the response is 201 with a new `DocumentSetResponse` containing a generated `id`

#### Scenario: Existing document set returned on duplicate name
- **WHEN** `POST /api/v1/document-sets` is called with a name that already exists
- **THEN** the response is 201 with the existing `DocumentSetResponse` — no error, no duplicate created

#### Scenario: Missing name returns 400
- **WHEN** `POST /api/v1/document-sets` is called without a `name` field
- **THEN** the response is 400

### Requirement: Get document set by ID
`GET /api/v1/document-sets/{document_set_id}` SHALL retrieve a single document set by its UUID. The response SHALL include `id`, `name`, `description`, `storage_backend`, `database_path`, `table_name`, `total_documents`, `total_size_bytes`, `total_pages`, `created_at`, `updated_at`, `metadata`, and an `attachment_ref` for external consumers to locate the storage artefact. An unknown `document_set_id` SHALL return 404. An invalid UUID format SHALL return 400.

#### Scenario: Known document set returned with attachment ref
- **WHEN** `GET /api/v1/document-sets/{document_set_id}` is called for an existing set
- **THEN** the response is 200 with a `DocumentSetResponse` including `attachment_ref`

#### Scenario: Unknown ID returns 404
- **WHEN** `GET /api/v1/document-sets/{unknown_id}` is called
- **THEN** the response is 404

#### Scenario: Malformed UUID returns 400
- **WHEN** `GET /api/v1/document-sets/not-a-uuid` is called
- **THEN** the response is 400

### Requirement: List document sets with pagination
`GET /api/v1/document-sets` SHALL return a `DocumentSetListResponse` with an `items` array, `total` (count of items returned in this page), `limit`, and `offset`. Query parameters `limit` (1–1000, default 100) and `offset` (default 0) SHALL control pagination.

#### Scenario: All document sets returned
- **WHEN** `GET /api/v1/document-sets` is called with no parameters
- **THEN** the response is 200 with a `DocumentSetListResponse` containing all sets up to the default limit

#### Scenario: Pagination respected
- **WHEN** `GET /api/v1/document-sets?limit=5&offset=10` is called
- **THEN** at most 5 items are returned starting from position 10

### Requirement: Update document set metadata (PATCH)
`PATCH /api/v1/document-sets/{document_set_id}` SHALL update the mutable fields `description` and `metadata` of an existing document set. Only the fields present in the request body are changed. `name`, `id`, storage fields, document counts, and timestamps are not mutable via this endpoint. On success the response SHALL be 200 with the complete updated `DocumentSetResponse`. An unknown `document_set_id` SHALL return 404.

#### Scenario: Description updated, other fields unchanged
- **WHEN** `PATCH /api/v1/document-sets/{document_set_id}` is called with only `{"description": "new desc"}`
- **THEN** the response is 200, `description` is updated, and `name`, `total_documents`, and `metadata` are unchanged

#### Scenario: Metadata updated independently
- **WHEN** `PATCH /api/v1/document-sets/{document_set_id}` is called with only `{"metadata": {"owner": "team-a"}}`
- **THEN** the response is 200 with the new `metadata` value

#### Scenario: Unknown ID returns 404
- **WHEN** `PATCH /api/v1/document-sets/{unknown_id}` is called
- **THEN** the response is 404

### Requirement: Delete a document set
`DELETE /api/v1/document-sets/{document_set_id}` SHALL delete a document set metadata record and conditionally remove underlying stored DuckDB rows according to the boolean `delete_data` parameter (defaulting to true), returning 204 on success.

#### Scenario: Delete with data removes metadata and stored rows
- **WHEN** `DELETE /api/v1/document-sets/{document_set_id}?delete_data=true` is called
- **THEN** the response is 204, the document set is no longer retrievable, and the stored DuckDB rows are deleted

#### Scenario: Delete without data removes only metadata
- **WHEN** `DELETE /api/v1/document-sets/{document_set_id}?delete_data=false` is called
- **THEN** the response is 204 and the metadata record is gone, but the underlying DuckDB table data is preserved

#### Scenario: Default delete_data is true
- **WHEN** `DELETE /api/v1/document-sets/{document_set_id}` is called without specifying `delete_data`
- **THEN** both the metadata and stored data are deleted (equivalent to `delete_data=true`)

#### Scenario: Unknown ID returns 404
- **WHEN** `DELETE /api/v1/document-sets/{unknown_id}` is called
- **THEN** the response is 404

### Requirement: Preview stored document rows
`GET /api/v1/document-sets/{document_set_id}/preview` SHALL return a paginated snapshot of the rows stored in the document set's DuckDB table. The response SHALL be a `DocumentSetPreviewResponse` containing `columns` (list of column names), `data` (list of row dicts), and `total_rows`. Query parameters `limit` (default 100) and `offset` (default 0) SHALL control pagination. An unknown `document_set_id` SHALL return 404.

#### Scenario: Preview returns columns and row data
- **WHEN** `GET /api/v1/document-sets/{document_set_id}/preview` is called for a set with stored rows
- **THEN** the response is 200 with `columns`, `data` (array of row objects), and `total_rows`

#### Scenario: Empty document set returns empty data
- **WHEN** `GET /api/v1/document-sets/{document_set_id}/preview` is called for a set with no rows
- **THEN** the response is 200 with `columns` (schema columns), `data=[]`, and `total_rows=0`

#### Scenario: Pagination limits rows returned
- **WHEN** `GET /api/v1/document-sets/{document_set_id}/preview?limit=10&offset=5` is called
- **THEN** at most 10 rows are returned starting from row 5

#### Scenario: Unknown ID returns 404
- **WHEN** `GET /api/v1/document-sets/{unknown_id}/preview` is called
- **THEN** the response is 404
