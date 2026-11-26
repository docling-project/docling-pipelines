# Spec Delta

## Purpose

The read-only REST contract that returns the derived data (vector stores and entity tables) of one document set and of every document set in a document library. The data is resolved from each document set's data card at request time (see `backend/derivative-resolution`). The API never creates, updates, or deletes anything. Consumers such as the retrieval service use `DerivativeResolverPort` directly and do not call these routes.

## ADDED Requirements

### Requirement: Derivatives of a document set
The system SHALL expose `GET /api/v1/document-sets/{document_set_id}/derivatives` returning a `DocumentSetDerivatives` body with `id`, `name`, and `derivative_stores` (`vector_stores`, `entity_tables`, `correlation_details`, `conflicts`), plus `acl_state`, `acl_protected`, `purpose`, `summary`, and `language`. A document set without a data card SHALL return empty lists and `acl_state` `unknown`.

#### Scenario: Document set with a card
- **WHEN** a client requests the derivatives of a document set whose card lists one `vectordb` and one `entity_store` entry
- **THEN** the response is 200 with one `vector_stores` item and one `entity_tables` item

#### Scenario: Document set without a card
- **WHEN** a client requests the derivatives of a document set that has no data card
- **THEN** the response is 200 with empty lists, `acl_state` `unknown`, and `acl_protected` true

#### Scenario: Unknown document set
- **WHEN** the `document_set_id` does not exist
- **THEN** the response is 404 with the standard `ErrorResponse` body and code `document_set_not_found`

### Requirement: Derivatives of a document library
The system SHALL expose `GET /api/v1/document-libraries/{library_id}/derivatives` returning a `DocumentLibraryDerivatives` body with `total_count`, `limit`, `next` (opaque bookmark or null), and `documentset_derivatives`, one entry per document set in the order of the library's `document_set_ids`. Each entry SHALL have the shape of the document set response.

#### Scenario: Library with derivatives
- **WHEN** a client requests the derivatives of a library whose document sets have cards with a `vectordb` and an `entity_store` entry
- **THEN** the response is 200 and the matching entry has one `vector_stores` item and one `entity_tables` item

#### Scenario: Document set without a card in a library
- **WHEN** a library contains a document set with no data card
- **THEN** its entry is returned with empty lists and `acl_state` `unknown`

#### Scenario: Library without document sets
- **WHEN** the library has no document sets
- **THEN** the response is 200 with `total_count` 0 and an empty `documentset_derivatives`

#### Scenario: Unknown library
- **WHEN** the `library_id` does not exist
- **THEN** the response is 404 with the standard `ErrorResponse` body and code `document_library_not_found`

### Requirement: Pagination
The library route SHALL accept `limit` (integer, default 100, minimum 1, maximum 1000) and `bookmark` (opaque string). `next` SHALL be null on the last page. A `bookmark` SHALL encode only a position in the library's document set order. A malformed, wrong-version, or negative-offset bookmark MUST be rejected with 400 and code `derivative_invalid_bookmark` without echoing its decoded content.

#### Scenario: Second page
- **WHEN** a library has 5 document sets and a client requests `limit=2`, then repeats with the returned `next` as `bookmark`
- **THEN** the first response has 2 entries and a non-null `next`, the second has the next 2 entries, and the third has the last entry with `next` null

#### Scenario: Invalid bookmark
- **WHEN** a client sends `bookmark=not-a-bookmark`
- **THEN** the response is 400 with code `derivative_invalid_bookmark`

#### Scenario: Bookmark beyond the end
- **WHEN** a client sends a well-formed bookmark whose offset is past the last document set
- **THEN** the response is 200 with an empty `documentset_derivatives` and `next` null

#### Scenario: Limit out of range
- **WHEN** a client sends `limit=0` or `limit=1001`
- **THEN** the response is 400 with code `validation_error`, as for every request validation failure in the API

### Requirement: Vector store item content
Each vector store item SHALL contain `provider`, `collection`, `embedding` (`provider`, `model_id`, `dimension_size`, or null), `add_sparse_vector`, `column_mapping` (`document_id`, `text`, `vector`, `sparse`, `allowed_users`, each nullable), and `correlatable`. Values the card holds as null SHALL be null in the response.

#### Scenario: Vector store item shape
- **WHEN** a card lists a Milvus `vectordb` with sparse search on and an embeddings entry from `watsonx`
- **THEN** the item shows `provider` `milvus`, the collection name, `add_sparse_vector` true, and the embedding provider, model, and dimension

#### Scenario: Null stays null
- **WHEN** the card has no `feature_mappings` for the vectordb
- **THEN** every `column_mapping` value in the item is null

### Requirement: Entity table and correlation content
Each entity table item SHALL contain `backend`, `schema` (Postgres only), `table_prefix`, and `retrievable`, and MUST NOT list table names. `correlation_details` items SHALL contain `vectorstore_column`, `entity_column`, and `rule`.

#### Scenario: Entity table item
- **WHEN** a card lists a file-backed DuckDB `entity_store` with prefix `entity_`
- **THEN** the item shows `backend` `duckdb`, `table_prefix` `entity_`, and `retrievable` true

#### Scenario: Correlation item
- **WHEN** the set has a correlatable vector store and a retrievable entity table
- **THEN** `correlation_details` has one item with `entity_column` `id` and `rule` `id-prefix`

### Requirement: Conflicts and ACL state in the response
The response SHALL carry `conflicts` as items with only `provider` and `kind` (`embedding_model` or `embedding_dimension`), and SHALL carry `acl_state` (`protected`, `unprotected`, or `unknown`) and the fail-closed `acl_protected` from the resolver.

#### Scenario: Conflict shown without model names
- **WHEN** two flows write one index with different embedding models
- **THEN** `conflicts` has one item with `kind` `embedding_model` and no model name

#### Scenario: Unknown ACL state
- **WHEN** the card's `propagate_source_acls` is null
- **THEN** the response has `acl_state` `unknown` and `acl_protected` true

### Requirement: Derivative response redaction
The response MUST NOT contain passwords, tokens, API keys, `${VAR}` or `vault://` references, hosts, ports, connection strings, filesystem paths, or a DuckDB `database_path`. The DTOs SHALL be built from an explicit field list so that a field added to the domain model is hidden until it is listed.

#### Scenario: Secret-like card values
- **WHEN** a card holds values shaped like `${DB_PASSWORD}`, `vault://secret/x`, or `/var/data/x.duckdb` in any derivative field
- **THEN** none of them appears in the response body

#### Scenario: Database path hidden
- **WHEN** an entity store is a file-backed DuckDB database
- **THEN** the item reports `backend` `duckdb` and `retrievable` true and contains no path

### Requirement: Authentication and access
Both routes SHALL require an authenticated user through `get_current_user` and SHALL be available at viewer level when `add-authn-authz` roles are active. A route MUST respond only with data of the requested document set or library.

#### Scenario: Unauthenticated request
- **WHEN** authentication is enabled and no valid credentials are supplied
- **THEN** the response is 401 using the existing authentication error shape

### Requirement: Query parameters from other platforms are tolerated
The library route SHALL accept the optional query parameters `container_id` and `container_type`, SHALL ignore them, and MUST NOT fail when they are present.

#### Scenario: Container parameters ignored
- **WHEN** a client sends `container_id=x&container_type=project`
- **THEN** the response is identical to the one without those parameters
