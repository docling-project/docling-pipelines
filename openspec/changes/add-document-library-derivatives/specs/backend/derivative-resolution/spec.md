# Spec Delta

## Purpose

How the data card of a document set (`add-document-set-data-card`) is resolved into the credential-free derivatives that consumers use: the vector stores and entity tables built from the document set, how each vector store is paired with its embedding model, which index columns it uses, whether it can be correlated with entity rows, and whether the set must be treated as access-controlled. Resolution reads the card at request time and stores nothing.

## ADDED Requirements

### Requirement: Derivatives are resolved from the data card only
The system SHALL resolve the derivatives of a document set from its data card and SHALL NOT read the flow definition, `DocumentSet.metadata`, or any store to do so. A document set without a card, or with a card that has no flows, SHALL resolve to empty `vector_stores`, `entity_tables`, `correlation_details`, and `conflicts`.

#### Scenario: Set without a card
- **WHEN** a document set has no data card
- **THEN** its derivatives have empty lists and `acl_state` `unknown`

#### Scenario: Metadata is ignored
- **WHEN** a document set's `metadata` holds keys named `derivatives` or `retrieval_derivatives`
- **THEN** the resolved derivatives are the same as without them

### Requirement: Latest run per flow, unioned and de-duplicated
For each flow in the card, the resolver SHALL use only the run with the greatest `executed_at` across all of the flow's jobs, treating an unparsable timestamp as the oldest. It SHALL return the union of the `vectordb` and `entity_store` stores of those runs, once each, where a vector store is identified by provider and path and an entity store by backend, path, and table prefix. When a store appears in several flows, the occurrence from the newest run SHALL win.

#### Scenario: Older run of the same flow ignored
- **WHEN** one flow has two runs and only the older run lists a `vectordb` with index `docs_old`
- **THEN** `docs_old` is not in the derivatives

#### Scenario: Two flows write different stores
- **WHEN** two flows each list a different `vectordb` index
- **THEN** both stores are returned

#### Scenario: Same store written by two flows
- **WHEN** two flows list a `vectordb` with the same provider and index
- **THEN** one store is returned, taken from the newer run

### Requirement: Cross-flow conflicts are reported
When a vector store recorded by several flows has different embedding `model_id` values or different `dimension_size` values, the resolver SHALL return the newest occurrence and SHALL add one conflict per differing property to `conflicts`, naming the provider and the kind (`embedding_model` or `embedding_dimension`) and not the model, index, or path.

#### Scenario: Model differs across flows
- **WHEN** two flows write the same index with embedding models `a` and `b`
- **THEN** the newest model is returned and one `embedding_model` conflict is reported

#### Scenario: Identical across flows
- **WHEN** two flows write the same index with the same model and dimension
- **THEN** no conflict is reported

### Requirement: Vector store is paired with its embedding model
For each `vectordb` entry the resolver SHALL select an `embeddings` entry of the same run. When the entry's `feature_mappings` is non-empty, it SHALL take the first embeddings entry whose `feature` equals the `feature_name` of a mapping item. Otherwise it SHALL take the last `embeddings` entry that precedes the `vectordb` entry in the run's operator order. A store with no embeddings entry SHALL be returned with a null embedding.

#### Scenario: Mapped feature selects the embedding
- **WHEN** a run lists two embeddings entries with features `emb_a` and `emb_b` and the vectordb mapping names `emb_b`
- **THEN** the store's embedding is the one with feature `emb_b`

#### Scenario: Nearest preceding embedding
- **WHEN** the vectordb entry has no mappings and one embeddings entry precedes it
- **THEN** that entry supplies the embedding provider, `model_id`, and `dimension_size`

#### Scenario: Embedding after the document set
- **WHEN** the flow is embeddings, document set, then vectordb
- **THEN** the store is paired with the embeddings entry

#### Scenario: No embeddings entry
- **WHEN** a run lists a vectordb entry and no embeddings entry
- **THEN** the store has a null embedding

### Requirement: Column mapping from explicit feature mappings
The resolver SHALL set the store's `column_mapping` keys `document_id`, `text`, `vector`, `sparse`, and `allowed_users` to the `mapped_column_name` of the explicit mapping item whose `feature_name` is respectively `id`, `content`, the paired embedding's `feature`, `sparse_embeddings`, and `allowed_users`. A key without such an item SHALL be null. The resolver SHALL NOT compute default column names, and SHALL NOT use an embedding's `feature` as an index column.

#### Scenario: Explicit mappings
- **WHEN** a vectordb maps `id` to `doc_id`, `embeddings` to `vec`, and `allowed_users` to `acl`
- **THEN** the store reports `document_id` `doc_id`, `vector` `vec`, `allowed_users` `acl`, and null `text` and `sparse`

#### Scenario: No mappings recorded
- **WHEN** the card records `feature_mappings` as null for the vectordb
- **THEN** every `column_mapping` key is null

#### Scenario: Embedding feature is not an index column
- **WHEN** the paired embedding's `feature` is `embeddings` and no mapping names it
- **THEN** `column_mapping.vector` is null

### Requirement: Sparse mode and provider from the card
A resolved vector store SHALL carry `add_sparse_vector` from the card's derivative store, and its embedding SHALL carry `provider`, `model_id`, and `dimension_size` from the paired embeddings entry. A value the card holds as null SHALL stay null in the derivative and SHALL NOT be replaced by a default.

#### Scenario: Provider recorded
- **WHEN** the paired embeddings entry has provider `watsonx`, model `m1`, and dimension 768
- **THEN** the store's embedding shows those three values

#### Scenario: Enterprise-shaped card
- **WHEN** a card has embeddings without `provider` and a derivative store without `add_sparse_vector`
- **THEN** both are null in the derivative

### Requirement: Correlation between vector stores and entity tables
A vector store SHALL be `correlatable` unless explicit feature mappings exist and none maps `id`. When a document set has at least one correlatable vector store and at least one retrievable entity table, `correlation_details` SHALL hold one item with `vectorstore_column` set to the first such store's mapped `document_id` column or `document_id` when unmapped, `entity_column` `id`, and `rule` `id-prefix`. Otherwise it SHALL be empty.

#### Scenario: Default mappings are correlatable
- **WHEN** a vector store has no recorded mappings and the set has a file-backed DuckDB entity store
- **THEN** `correlation_details` has one `id-prefix` item with `vectorstore_column` `document_id`

#### Scenario: Mappings without id
- **WHEN** explicit mappings do not map `id`
- **THEN** the store is not correlatable and `correlation_details` is empty

#### Scenario: Only an in-memory entity store
- **WHEN** the only entity store is DuckDB with path `:memory:`
- **THEN** `correlation_details` is empty

### Requirement: Entity tables are reported by location
Each `entity_store` entry SHALL resolve to an entity table group with `backend`, `schema` (Postgres only), `table_prefix`, and `retrievable`. `retrievable` SHALL be false for a DuckDB store whose path is `:memory:` and true otherwise. The resolver SHALL NOT enumerate table names. The domain object SHALL keep the DuckDB `database_path` so a consumer can open it.

#### Scenario: File-backed DuckDB
- **WHEN** an entity store entry has backend `duckdb` and path `data/duckdb/entities.duckdb`
- **THEN** the group is retrievable, has prefix `entity_`, and its domain object keeps the path

#### Scenario: In-memory DuckDB
- **WHEN** an entity store entry has backend `duckdb` and path `:memory:`
- **THEN** the group is not retrievable

#### Scenario: Postgres
- **WHEN** an entity store entry has backend `postgres` and path `docpipe_entities`
- **THEN** the group has schema `docpipe_entities`, is retrievable, and carries no connection details

### Requirement: ACL state fails closed
The resolver SHALL set `acl_state` to `protected` when the card's `propagate_source_acls` is true, `unprotected` when it is false, and `unknown` when it is null or the set has no card. It SHALL set `acl_protected` to true for `protected` and `unknown`, and to false only for `unprotected`.

#### Scenario: Card says true
- **WHEN** `propagate_source_acls` is true
- **THEN** `acl_state` is `protected` and `acl_protected` is true

#### Scenario: Card says false
- **WHEN** `propagate_source_acls` is false
- **THEN** `acl_state` is `unprotected` and `acl_protected` is false

#### Scenario: Never recorded
- **WHEN** `propagate_source_acls` is null
- **THEN** `acl_state` is `unknown` and `acl_protected` is true

### Requirement: Descriptive hints are passed through
The resolver SHALL return the card's `purpose`, `summary`, and `language` unchanged, or null when absent.

#### Scenario: Hints available
- **WHEN** the card has a `purpose` and a `summary`
- **THEN** the derivative carries both

### Requirement: Derivative resolver port
The domain SHALL define `DerivativeResolverPort` with `list_for_library(*, library_id, limit, offset)` and `get_for_document_set(*, document_set_id)`. Results SHALL be domain objects that include fields a REST DTO hides, such as the DuckDB `database_path`. Consumers MUST depend on the port and MUST NOT depend on the data card service, document set repositories, or adapters.

#### Scenario: Library resolved in order
- **WHEN** a consumer calls `list_for_library` for a library with three document sets
- **THEN** it receives three derivatives in the library's `document_set_ids` order

#### Scenario: Unknown document set
- **WHEN** `get_for_document_set` is called with an id that does not exist
- **THEN** it raises `DocumentSetNotFoundException`

#### Scenario: Unknown library
- **WHEN** `list_for_library` is called with an id that does not exist
- **THEN** it raises `DocumentLibraryNotFoundException`
