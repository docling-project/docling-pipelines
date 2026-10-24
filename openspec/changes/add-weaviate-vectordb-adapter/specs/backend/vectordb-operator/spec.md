# Spec Delta

## Purpose

The `vectordb` operator persists chunked documents and their dense embeddings into a configured vector database so downstream retrieval systems can search them. This capability defines the provider-agnostic contract: provider selection, the input table, and the output metadata. Provider-specific behavior is specified in separate capabilities, such as `backend/vectordb-weaviate`.

## ADDED Requirements

### Requirement: Provider selection
The operator SHALL route all writes to the vector database selected by `provider` and described by `provider_config`. Operator metadata SHALL list every registered provider among the `provider` valid values and SHALL publish a `provider_config` field schema for each. Selecting one provider MUST NOT change the behavior of another.

#### Scenario: Unknown provider rejected
- **WHEN** a flow sets `provider` to a value that is not a registered provider
- **THEN** the operator fails to initialize with an error that names the unknown provider and lists the available providers

### Requirement: Input table contract
The operator SHALL require the document ID column (`doc_id_column`, default `doc_id_hash`) in its input table. It SHALL write every dense vector column that `available_features` marks as `type: "vector"` and `available_for_vector_db: true`. Chunked rows SHALL be read from `chunked_content`, either as an in-memory list or as memory-mapped file references. The `id` and `name` columns are optional and are used for document attribution.

#### Scenario: Missing document ID column
- **WHEN** the input table lacks the configured document ID column
- **THEN** no objects are written, the input table is returned unchanged, and `node_status` is `FAILED`

#### Scenario: No dense vector column
- **WHEN** `available_features` declares no dense vector column available for the vector database and `add_sparse_vector` is false
- **THEN** no objects are written and `node_status` is `FAILED`

#### Scenario: Chunked row expands to one object per chunk
- **WHEN** a row has N chunks in `chunked_content` and N embeddings in each vector column
- **THEN** N objects are written for that document, each carrying its chunk text and one vector per vector column

### Requirement: Transform output and metadata contract
The operator SHALL return its input table unchanged as the single output table. It SHALL return metadata containing `documents_in_scope` (unique documents), `processed_docs`, `failed_docs_count`, `failed_docs`, `skipped_docs_count`, `skipped_docs`, `total_chunks_to_index`, `chunks_indexed_successfully`, `chunks_failed_to_index`, `number_of_batches`, and `node_status`.

#### Scenario: Successful write
- **WHEN** every chunk of every document is written
- **THEN** `chunks_indexed_successfully` equals `total_chunks_to_index`, `failed_docs_count` is 0, and the output table equals the input table

#### Scenario: Row without a document ID is skipped
- **WHEN** a row's document ID value is empty
- **THEN** that row is recorded in `skipped_docs` with reason "Missing document ID" and the remaining rows are still written
