# Spec Delta

## Purpose

The `vectordb` operator persists chunked documents and their dense embeddings, and optionally enables sparse retrieval, into a configured vector database so downstream retrieval systems can search them. This capability defines the provider-agnostic contract: provider selection, the input table, document identity, sparse (`add_sparse_vector`) mode, the output metadata, and release of the adapter after flow validation. Provider-specific behavior is specified in separate capabilities, such as `backend/vectordb-weaviate`.

These requirements describe behavior the operator already has for OpenSearch and Milvus, with two exceptions, each described in its own requirement: document identity when `id` is missing or null, and releasing the adapter after flow validation. The change that adds this capability pins the remaining behavior with tests so that every future provider is held to the same contract.

## ADDED Requirements

### Requirement: Provider selection
The operator SHALL route all writes to the vector database selected by `provider` and described by `provider_config`. Operator metadata SHALL list every registered provider among the `provider` valid values and SHALL publish a `provider_config` field schema for each. Selecting one provider MUST NOT change the behavior of another.

#### Scenario: Unknown provider rejected
- **WHEN** a flow sets `provider` to a value that is not a registered provider
- **THEN** the operator fails to initialize with an error that names the unknown provider and lists the available providers

### Requirement: Input table contract
The operator SHALL require the document ID column (`doc_id_column`, default `doc_id_hash`) in its input table. It SHALL write every dense vector column that `available_features` marks as `type: "vector"` and `available_for_vector_db: true`. Chunked rows SHALL be read from `chunked_content`, either as an in-memory list or as memory-mapped file references. The `id` and `name` columns are optional; `name` is used for attribution and `id` for document identity (next requirement).

#### Scenario: Missing document ID column
- **WHEN** the input table lacks the configured document ID column
- **THEN** no objects are written, the input table is returned unchanged, and `node_status` is `FAILED`

#### Scenario: No dense vector column
- **WHEN** `available_features` declares no dense vector column available for the vector database and `add_sparse_vector` is false
- **THEN** no objects are written and `node_status` is `FAILED`

#### Scenario: Chunked row expands to one object per chunk
- **WHEN** a row has N chunks in `chunked_content` and N embeddings in each vector column
- **THEN** N objects are written for that document, each carrying its chunk text and one vector per vector column

### Requirement: Document identity
The operator SHALL identify a document by its `id` value when that value is present and non-empty, and by its document ID column value otherwise. That identity SHALL generate the document's chunk keys and drive the lookup and deletion of its stale chunks. Documents without a usable `id` MUST NOT share an identity.

#### Scenario: Null id on several documents
- **WHEN** two documents in one table have a null `id` and different document IDs
- **THEN** their chunk keys differ and the chunks of both documents are persisted

#### Scenario: Missing id column still requests cleanup
- **WHEN** the input table has no `id` column
- **THEN** the stale-chunk lookup is called with each document's document ID, and chunk keys are generated from that same value

#### Scenario: Null id still requests cleanup
- **WHEN** a document's `id` is null
- **THEN** the stale-chunk lookup is called with that document's document ID, and chunks that the lookup returns and the run no longer produces are deleted

### Requirement: Sparse retrieval mode
The operator SHALL read the top-level `add_sparse_vector` flag (default false) and pass it to the provider. When it is true, dense vector columns are optional: with none, the operator SHALL detect no dimensions and continue, and with some, it SHALL detect dimensions for them as usual. The `sparse_embeddings` feature MAY be mapped. Whether a provider stores sparse vectors or scores text on the server is defined by that provider's own capability.

#### Scenario: Sparse-only run
- **WHEN** `add_sparse_vector` is true, `available_features` declares no dense vector column, and the chunks are provided in memory
- **THEN** the dimension mapping is empty, the run is not marked `FAILED` for lack of vectors, and each chunk is written with its text and no dense vector

#### Scenario: Sparse and dense run
- **WHEN** `add_sparse_vector` is true and `available_features` declares a dense vector column
- **THEN** the dimensions of the dense columns are detected and each chunk is written with its dense vector as well

#### Scenario: Provider that stores no sparse vector
- **WHEN** `add_sparse_vector` is true and the mappings include `sparse_embeddings`
- **THEN** a provider that does not store sparse vectors accepts the mapping and ignores it

### Requirement: Adapter release after flow validation
When the operator is constructed for flow validation (the `validating_flow` configuration key is set), `validate()` SHALL release the adapter's resources before it returns, whether validation succeeds or raises. The release SHALL NOT depend on `transform()` running. A provider that fails after opening a connection during construction SHALL release that connection before raising.

#### Scenario: Validation completes
- **WHEN** an operator constructed for flow validation finishes `validate()` without error
- **THEN** the adapter's `close()` has been called exactly once

#### Scenario: Validation raises
- **WHEN** an operator constructed for flow validation raises from `validate()`
- **THEN** the adapter's `close()` has been called before the error propagates

#### Scenario: Normal run is unaffected
- **WHEN** an operator constructed for a normal run calls `validate()` and then `transform()`
- **THEN** `validate()` does not close the adapter and `transform()` still closes it once in its `finally` block

### Requirement: Transform output and metadata contract
The operator SHALL return its input table unchanged as the single output table. It SHALL return metadata containing `documents_in_scope` (unique documents), `processed_docs`, `failed_docs_count`, `failed_docs`, `skipped_docs_count`, `skipped_docs`, `total_chunks_to_index`, `chunks_indexed_successfully`, `chunks_failed_to_index`, `number_of_batches`, and `node_status`.

#### Scenario: Successful write
- **WHEN** every chunk of every document is written
- **THEN** `chunks_indexed_successfully` equals `total_chunks_to_index`, `failed_docs_count` is 0, and the output table equals the input table

#### Scenario: Row without a document ID is skipped
- **WHEN** a row's document ID value is empty
- **THEN** that row is recorded in `skipped_docs` with reason "Missing document ID" and the remaining rows are still written
