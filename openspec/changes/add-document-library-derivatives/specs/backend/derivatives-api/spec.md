# Spec Delta

## Purpose

The read-only REST contract that lists, for a document library, the derived data (vector stores and entity tables) produced from each of its document sets. Consumers such as the retrieval service use it, directly or through `DerivativeResolverPort`, to discover where a library's searchable data lives. Records are created by the system (see `backend/derivative-recording`); this API never creates, updates, or deletes them.

## ADDED Requirements

### Requirement: List derivatives of a document library
The system SHALL expose `GET /api/v1/document-libraries/{library_id}/derivatives` returning a `DocumentLibraryDerivatives` body with `total_count`, `limit`, `next` (opaque bookmark or null) and `documentset_derivatives`, one entry per document set in the order of the library's `document_set_ids`. Each entry SHALL contain `id`, `name`, and `derivative_stores` (`vector_stores`, `entity_tables`, `correlation_details`). A document set with no recorded derivative SHALL have three empty lists.

#### Scenario: Library with recorded derivatives
- **WHEN** a client requests the derivatives of a library whose document sets were produced by a completed flow with a `vectordb` and an `entity_store_operator` node
- **THEN** the response status is 200 and the matching entry contains one `vector_stores` item and one `entity_tables` item

#### Scenario: Document set without derivatives
- **WHEN** a library contains a document set created before derivative recording existed
- **THEN** its entry is returned with `vector_stores`, `entity_tables`, and `correlation_details` all empty

#### Scenario: Library not found
- **WHEN** the `library_id` does not exist
- **THEN** the response is 404 with the standard `ErrorResponse` body and code `document_library_not_found`

#### Scenario: Library without document sets
- **WHEN** the library has no document sets
- **THEN** the response is 200 with `total_count` 0 and an empty `documentset_derivatives`

### Requirement: Pagination
The endpoint SHALL accept `limit` (integer, default 100, minimum 1, maximum 1000) and `bookmark` (opaque string). `next` SHALL be null on the last page. A `bookmark` SHALL encode only the position in the library's document set order, and an invalid, tampered, or out-of-range bookmark MUST be rejected with 400 and code `derivative_invalid_bookmark` without exposing the decoded content.

#### Scenario: Second page
- **WHEN** a library has 5 document sets and a client requests `limit=2`, then repeats with the returned `next` as `bookmark`
- **THEN** the first response has 2 entries and a non-null `next`, the second response has the following 2 entries, and the third request returns the last entry with `next` null

#### Scenario: Invalid bookmark
- **WHEN** a client sends `bookmark=not-a-bookmark`
- **THEN** the response is 400 with code `derivative_invalid_bookmark`

#### Scenario: Limit out of range
- **WHEN** a client sends `limit=0` or `limit=1001`
- **THEN** the response is 422 from request validation

### Requirement: Derivative response content
Vector store items SHALL contain `provider`, `collection`, `connection` (host, port, TLS flag only), `embeddings`, `chunk_type`, `chunk_size` when known, `column_mapping`, `id_field`, `correlatable`, and `vector_params`. Entity table items SHALL contain `backend`, `schema`, `tables`, and `retrievable`.

#### Scenario: Vector store item shape
- **WHEN** a derivative has a Milvus vector store with sparse search enabled
- **THEN** the item reports `provider: "milvus"`, the collection name, `vector_params.sparse: true`, and `embeddings` with provider, model, and dimension

### Requirement: Derivative response redaction
The response MUST NOT contain passwords, tokens, API keys, `${VAR}` or `vault://` references, connection strings, filesystem paths, or a DuckDB `database_path`.

#### Scenario: Credentials never returned
- **WHEN** the flow that produced a derivative used `provider_config` with `password`, `api_key`, and a `vault://` reference
- **THEN** none of those keys or values appear anywhere in the response body

#### Scenario: Database path hidden
- **WHEN** an entity store used a file-backed DuckDB database
- **THEN** the entity table item reports `backend: "duckdb"` and `retrievable: true` and contains no path

### Requirement: Correlation details
For every document set that has both a correlatable vector store and a retrievable entity table, `correlation_details` SHALL contain one item naming `vectorstore_column` (the vector store's `id_field`) and `entity_column` (`id`) and `rule` set to `"id-prefix"`, meaning an entity row belongs to the document `D` when its `id` equals `D:<table>` or `D:<table>:<n>`. When either side is missing or not correlatable the list SHALL be empty.

#### Scenario: Both sides present
- **WHEN** a derivative has a correlatable vector store and a retrievable entity table
- **THEN** `correlation_details` has one item with `vectorstore_column` equal to the vector store's `id_field` and `rule` equal to `id-prefix`

#### Scenario: Uncorrelatable vector store
- **WHEN** a derivative has a vector store with `correlatable: false` and an entity table
- **THEN** `correlation_details` is empty

### Requirement: Authentication and access
The endpoint SHALL require an authenticated user through `get_current_user` and SHALL be available at viewer level when `add-authn-authz` roles are active. It MUST respond only with data of the requested library.

#### Scenario: Unauthenticated request
- **WHEN** authentication is enabled and no valid credentials are supplied
- **THEN** the response is 401 using the existing authentication error shape

### Requirement: Query parameters from other platforms are tolerated
The endpoint SHALL accept the optional query parameters `container_id` and `container_type`, SHALL ignore them, and MUST NOT fail when they are present.

#### Scenario: Container parameters ignored
- **WHEN** a client sends `container_id=x&container_type=project`
- **THEN** the response is identical to the one without those parameters
