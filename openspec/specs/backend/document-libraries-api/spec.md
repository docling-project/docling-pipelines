# backend/document-libraries-api Specification

## Purpose

The document-libraries-api capability manages document libraries — named collections that group document sets via many-to-many relationships. A library holds references to document sets but does not own their data: deleting a library removes the library record and its associations, but the document sets themselves are unaffected. Libraries support optional metadata (description, purpose, sizes, tags) and expose sub-resource endpoints to manage their document set memberships in bulk.

## Requirements

### Requirement: Create a document library
`POST /api/v1/document-libraries` SHALL create a new library with a generated UUID `library_id` and zero initial metrics. The request body accepts unique `name` (3–128 chars starting with a letter), optional `description`, `purpose`, size estimates, and `tags`.

#### Scenario: Library created successfully
- **WHEN** `POST /api/v1/document-libraries` is called with a valid unique name
- **THEN** the response is 201 with a `DocumentLibraryResponse` containing a generated `library_id` and zero initial metrics

#### Scenario: Duplicate name returns 409
- **WHEN** `POST /api/v1/document-libraries` is called with a `name` that already exists
- **THEN** the response is 409

#### Scenario: Name shorter than 3 chars returns 400
- **WHEN** `POST /api/v1/document-libraries` is called with a `name` of fewer than 3 characters
- **THEN** the response is 400

#### Scenario: Name not starting with a letter returns 400
- **WHEN** `POST /api/v1/document-libraries` is called with a `name` that starts with a digit or special character
- **THEN** the response is 400

### Requirement: Get document library by ID
`GET /api/v1/document-libraries/{library_id}` SHALL retrieve a single library by its UUID. The response SHALL include all library metadata and the list of associated document set IDs (`document_set_ids`). An unknown `library_id` SHALL return 404. An invalid UUID format SHALL return 400.

#### Scenario: Known library returned with document set IDs
- **WHEN** `GET /api/v1/document-libraries/{library_id}` is called for an existing library
- **THEN** the response is 200 with a `DocumentLibraryResponse` including the `document_set_ids` list

#### Scenario: Unknown library returns 404
- **WHEN** `GET /api/v1/document-libraries/{unknown_id}` is called
- **THEN** the response is 404

#### Scenario: Malformed UUID returns 400
- **WHEN** `GET /api/v1/document-libraries/not-a-uuid` is called
- **THEN** the response is 400

### Requirement: List document libraries with pagination and filtering
`GET /api/v1/document-libraries` SHALL return a list of library responses (not wrapped in a paginated envelope). Query parameters `limit` (default 100, max 1000), `offset` (default 0), and `name` (partial match) SHALL filter results.

#### Scenario: All libraries returned
- **WHEN** `GET /api/v1/document-libraries` is called with no filters
- **THEN** the response is 200 with a JSON array of `DocumentLibraryResponse` objects up to the default limit

#### Scenario: Name filter narrows results
- **WHEN** `GET /api/v1/document-libraries?name=Research` is called
- **THEN** only libraries whose name contains "Research" are returned

#### Scenario: Empty result returns empty array
- **WHEN** `GET /api/v1/document-libraries` is called and no libraries exist
- **THEN** the response is 200 with an empty array `[]`

### Requirement: Partial update document library (PATCH)
`PATCH /api/v1/document-libraries/{library_id}` SHALL update only the fields provided in the request body. Protected fields (`library_id`, `created_at`, `document_set_ids`) SHALL NOT be modifiable via this endpoint. When `name` is changed it must still be unique; a conflict SHALL return 409. On success the response SHALL be 200 with the complete updated library including a refreshed `updated_at` timestamp. An unknown `library_id` SHALL return 404.

#### Scenario: Partial update changes only supplied fields
- **WHEN** `PATCH /api/v1/document-libraries/{library_id}` is called with only `{"tags": ["new-tag"]}`
- **THEN** the response is 200, `tags` is updated, and `name`, `description`, and `document_set_ids` are unchanged

#### Scenario: Name change to existing name returns 409
- **WHEN** `PATCH /api/v1/document-libraries/{library_id}` is called with a `name` that belongs to another library
- **THEN** the response is 409

#### Scenario: updated_at refreshed on successful update
- **WHEN** `PATCH /api/v1/document-libraries/{library_id}` is called with any valid update
- **THEN** `updated_at` in the response is later than the pre-update value

#### Scenario: Unknown library returns 404
- **WHEN** `PATCH /api/v1/document-libraries/{unknown_id}` is called
- **THEN** the response is 404

### Requirement: Delete a document library
`DELETE /api/v1/document-libraries/{library_id}` SHALL delete the library record and remove all its associations with document sets. The document sets themselves SHALL NOT be deleted — only the library-to-set relationships are removed. This is the inverse of project deletion (which cascades). On success the response SHALL be 204 with no body. An unknown `library_id` SHALL return 404.

#### Scenario: Library deleted, document sets preserved
- **WHEN** `DELETE /api/v1/document-libraries/{library_id}` is called for a library with associated document sets
- **THEN** the response is 204, the library is no longer retrievable, and the previously associated document sets still exist and are retrievable

#### Scenario: Unknown library returns 404
- **WHEN** `DELETE /api/v1/document-libraries/{unknown_id}` is called
- **THEN** the response is 404

### Requirement: Bulk-add document sets to a library
`PUT /api/v1/document-libraries/{library_id}/document-sets?document_sets_ids=id1,id2,…` SHALL associate one or more document set UUIDs with a library in a single request, supporting many-to-many relationships and returning 204 on success.

#### Scenario: Document sets added to library
- **WHEN** `PUT /api/v1/document-libraries/{library_id}/document-sets?document_sets_ids=id1,id2` is called with valid IDs
- **THEN** the response is 204 and both document sets appear in `GET /document-libraries/{library_id}/document-sets`

#### Scenario: Already-associated document set returns 400
- **WHEN** `PUT /api/v1/document-libraries/{library_id}/document-sets?document_sets_ids={already_added_id}` is called
- **THEN** the response is 400

#### Scenario: Non-existent document set returns 404
- **WHEN** `PUT /api/v1/document-libraries/{library_id}/document-sets?document_sets_ids={unknown_set_id}` is called
- **THEN** the response is 404

### Requirement: Bulk-remove document sets from a library
`DELETE /api/v1/document-libraries/{library_id}/document-sets?document_sets_ids=id1,id2,…` SHALL remove the specified associations between the library and document sets. The document sets themselves are NOT deleted. A referenced document set that is not currently associated with the library SHALL return 400. On success the response SHALL be 204.

#### Scenario: Document sets removed from library
- **WHEN** `DELETE /api/v1/document-libraries/{library_id}/document-sets?document_sets_ids=id1` is called for an associated set
- **THEN** the response is 204 and the set no longer appears in `GET /document-libraries/{library_id}/document-sets`; the set itself is still retrievable via `GET /document-sets/{id}`

#### Scenario: Document set not in library returns 400
- **WHEN** `DELETE /api/v1/document-libraries/{library_id}/document-sets?document_sets_ids={not_associated_id}` is called
- **THEN** the response is 400

### Requirement: List document sets in a library
`GET /api/v1/document-libraries/{library_id}/document-sets` SHALL return a `DocumentSetsRetrieved` response containing metadata for all document sets associated with the library, or an empty list if none are linked.

#### Scenario: Document set metadata returned for each associated set
- **WHEN** `GET /api/v1/document-libraries/{library_id}/document-sets` is called for a library with associated sets
- **THEN** the response is 200 with full metadata for each document set including document counts

#### Scenario: Library with no associations returns empty array
- **WHEN** `GET /api/v1/document-libraries/{library_id}/document-sets` is called for a library with no sets
- **THEN** the response is 200 with an empty `document_sets` array

#### Scenario: documents field is null for sets with no stored documents
- **WHEN** `GET /api/v1/document-libraries/{library_id}/document-sets` includes a set with `total_documents = 0`
- **THEN** the `documents` field for that entry is `null`

#### Scenario: Unknown library returns 404
- **WHEN** `GET /api/v1/document-libraries/{unknown_id}/document-sets` is called
- **THEN** the response is 404
