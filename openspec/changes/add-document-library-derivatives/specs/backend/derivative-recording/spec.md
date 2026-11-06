# Spec Delta

## Purpose

How derivative records are produced and stored. When a flow finishes successfully, docpipe records for each document set the vector stores and entity tables that the same flow derived from it, without credentials. A resolver port gives other capabilities (retrieval) read access to these records without depending on document set internals.

## ADDED Requirements

### Requirement: Record derivatives on successful flow completion
On successful completion of a flow, the system SHALL create a derivative record for every `document_set` node in the flow. The record SHALL include the stores written by `vectordb` and `entity_store_operator` nodes that are ancestors of that `document_set` node in the flow DAG, and SHALL ignore nodes that are not ancestors. Recording MUST NOT run when the flow fails, is aborted, or is cancelled.

#### Scenario: Linear flow
- **WHEN** a flow `ingest_source -> extract_operator -> chunker -> embeddings -> vectordb -> document_set` completes
- **THEN** the document set named by the `document_set` node has a derivative with one vector store and no entity tables

#### Scenario: Branch not feeding the document set
- **WHEN** a flow has two `vectordb` nodes and only one is an ancestor of the `document_set` node
- **THEN** only the ancestor's store appears in that document set's derivative

#### Scenario: Failed flow
- **WHEN** a flow fails after the `vectordb` node wrote chunks
- **THEN** no derivative record is written or changed

#### Scenario: Flow without a document set node
- **WHEN** a completed flow has no `document_set` node
- **THEN** nothing is recorded and one warning is logged naming the flow

### Requirement: No secrets in derivative records
The recorder SHALL build records from an allowlist of fields. It MUST NOT persist `password`, `api_key`, tokens, `${VAR}` or `vault://` references, connection strings, URLs with embedded credentials, or any `provider_config` key outside the allowlist. A DuckDB `database_path` MAY be kept internally to let the retrieval service open the database but SHALL NOT be returned by the REST API.

#### Scenario: Allowlist enforced
- **WHEN** `provider_config` contains an unknown key `custom_secret`
- **THEN** the persisted record does not contain `custom_secret` or its value

#### Scenario: Variable references dropped
- **WHEN** `provider_config.password` is `${OPENSEARCH_PASSWORD}`
- **THEN** neither the key nor the reference is persisted

### Requirement: Vector store record content
For each `vectordb` ancestor the record SHALL capture `provider`, the collection or index name, non-secret connection fields (`host`, `port`, TLS flag), the sparse flag, the distance metric, and the effective feature mappings. The embedding provider, model id, and dimension SHALL be taken from the nearest ancestor `embeddings` node. If the dimension is not in the configuration, it SHALL be taken from the vector feature mapping when available, otherwise left null.

#### Scenario: Embedding model captured
- **WHEN** the `embeddings` ancestor uses provider `ollama` and model `nomic-embed-text`
- **THEN** the vector store record has `embeddings.provider = "ollama"` and `embeddings.model = "nomic-embed-text"`

#### Scenario: Sparse flag
- **WHEN** the `vectordb` node has `add_sparse_vector: true`
- **THEN** the record's `vector_params.sparse` is true

### Requirement: Ingest identifier mapping
The recorder SHALL determine `id_field`, the chunk field that carries the ingest document `id`, from the effective feature mappings of the `vectordb` node. When no mapped field carries the ingest `id`, the store SHALL be recorded with `id_field` null and `correlatable` false, and a warning SHALL be logged. Default mappings (`id` mapped to `document_id`) SHALL yield `id_field = "document_id"` and `correlatable = true`.

#### Scenario: Default mappings
- **WHEN** the `vectordb` node has no explicit feature mappings
- **THEN** the record has `id_field = "document_id"` and `correlatable = true`

#### Scenario: Explicit mappings without id
- **WHEN** the explicit feature mappings map only `doc_id_hash`, `content`, embeddings, and `document_type`
- **THEN** the record has `id_field = null` and `correlatable = false`

### Requirement: Entity table record content
For each `entity_store_operator` ancestor the record SHALL capture `backend` (`duckdb` or `postgres`), `schema` for Postgres, the table name for each entity key (`table_prefix` plus key), and the file-backed DuckDB `database_path` for internal use. A store whose `database_path` is `:memory:` SHALL be recorded with `retrievable` false. Postgres connection details MUST NOT be recorded, because the retrieval service reads them from the `DOCPIPE_POSTGRES_*` environment variables.

#### Scenario: Persisted DuckDB
- **WHEN** `data_backend` is `duckdb` and `database_path` is a file path
- **THEN** the record has `retrievable = true` and one table name per entity key

#### Scenario: In-memory DuckDB
- **WHEN** `database_path` is `:memory:`
- **THEN** the record has `retrievable = false`

#### Scenario: Postgres
- **WHEN** `data_backend` is `postgres` with schema `docpipe_entities`
- **THEN** the record has `backend = "postgres"`, `schema = "docpipe_entities"`, and no host, user, or password

### Requirement: Merge persistence
The recorder SHALL persist the record under the reserved key `derivatives` of the document set `metadata`, merging with existing metadata keys and leaving them unchanged. When a re-run produces a store already present (same provider and collection or same backend and table set), the entry SHALL be replaced, not duplicated. Entries for other stores SHALL be kept.

#### Scenario: Existing metadata preserved
- **WHEN** the document set already has `metadata = {"owner": "team-a"}`
- **THEN** after recording, `metadata` contains `owner` unchanged and `derivatives`

#### Scenario: Re-run replaces entry
- **WHEN** a flow runs twice against the same collection
- **THEN** the document set has exactly one vector store entry for that collection

### Requirement: Recorder failure isolation
A failure in recording MUST NOT change the flow result, status, or duration semantics. The failure SHALL be logged at warning level with the job run id and without secrets. When `DOCPIPE_LINEAGE_STRICT` is not true, errors are swallowed; the recorder's strictness SHALL be independent of lineage strictness.

#### Scenario: Metadata repository unavailable
- **WHEN** the metadata repository raises during recording after a successful flow
- **THEN** the job run still ends as successful and a warning is logged

### Requirement: Derivative resolver port
The domain SHALL define `DerivativeResolverPort` with `list_for_library(*, library_id, limit, offset)` and `get_for_document_set(*, document_set_id)`. Results SHALL be domain objects that include internal fields (such as the DuckDB path) that the REST DTO hides. Consumers MUST depend on the port, not on `DocumentSetService` or repositories.

#### Scenario: Retrieval resolves a library
- **WHEN** a consumer calls `list_for_library` for a library with three document sets
- **THEN** it receives three `DocumentSetDerivative` objects in library order

#### Scenario: Unknown document set
- **WHEN** `get_for_document_set` is called with an id that does not exist
- **THEN** it raises `DocumentSetNotFoundException`
