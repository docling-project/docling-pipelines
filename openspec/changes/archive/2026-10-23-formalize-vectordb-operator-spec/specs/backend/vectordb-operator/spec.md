# Spec Delta

## Purpose

The VectorDB operator ingests vectorized chunk embeddings and document metadata from PyArrow tables into supported vector database backends (OpenSearch, Milvus). It supports dense, sparse, and hybrid vector indexing, automatic embedding dimension detection, index/collection lifecycle management, schema validation, stale chunk cleanup, flow enrichment resource introspection, and detailed execution failure metrics.

## ADDED Requirements

### Requirement: Operator table and metadata contract
The VectorDB operator SHALL accept a PyArrow table containing a document ID/hash column, chunked text, and vector embedding columns. It SHALL return the input table with execution metadata reporting processed documents, failed document details, indexed chunk counts, and node execution status.

#### Scenario: Successful table transform
- **WHEN** a valid PyArrow table with document IDs, chunks, and embeddings is transformed
- **THEN** the operator indexes the documents into the configured vector store and returns the table with `status="SUCCEEDED"` and `processed_docs` count matching unique input document IDs

#### Scenario: Empty input table
- **WHEN** an empty PyArrow table is provided to the operator
- **THEN** the operator returns the empty table immediately with zero processed documents without issuing database index requests

#### Scenario: Missing required document ID column
- **WHEN** the input table lacks the configured document ID/hash column
- **THEN** the operator logs an error, marks node status as `FAILED`, and returns the table without indexing

### Requirement: Vector dimension auto-detection
The operator SHALL inspect configured vector features in `available_features` and automatically detect vector dimensions from in-memory arrays or memory-mapped embedding files for all dense vector columns.

#### Scenario: Dense embeddings dimension detection
- **WHEN** one or more dense embedding columns are present in `available_features`
- **THEN** the operator detects dimensions for each column and maps them to their respective target vector fields

#### Scenario: Dimension detection failure
- **WHEN** vector dimensions cannot be determined from the table or embedding metadata
- **THEN** the transform fails with node status `FAILED` and records failures for all input documents

### Requirement: Sparse and hybrid vector indexing
The operator SHALL support pure dense vectors, pure sparse vectors (BM25), and dual dense-sparse hybrid vector configurations via `add_sparse_vector`.

#### Scenario: Pure sparse vector mode
- **WHEN** `add_sparse_vector` is enabled and no dense vector columns are configured
- **THEN** the operator creates sparse vector fields and indexes documents without requiring dense embeddings

#### Scenario: Hybrid dense and sparse vector mode
- **WHEN** `add_sparse_vector` is enabled and dense vector columns are configured
- **THEN** the operator indexes both dense vector embeddings and sparse text representations into the target vector store

### Requirement: Index and collection lifecycle management
The operator SHALL manage the target vector store index or collection lifecycle according to operator configuration, checking if the resource exists and performing schema validation or index creation.

#### Scenario: Index creation when absent
- **WHEN** `create_index` is true and the target index or collection does not exist
- **THEN** the operator creates the index or collection with detected vector dimensions and feature mappings

#### Scenario: Schema validation on existing index
- **WHEN** `create_index` is true and the target index or collection already exists
- **THEN** the operator validates the existing schema against detected dimensions and feature mappings

#### Scenario: Index creation disabled
- **WHEN** `create_index` is false
- **THEN** the operator bypasses index creation and schema validation checks

#### Scenario: Index creation or schema validation failure
- **WHEN** index creation or schema validation raises an exception
- **THEN** all unique documents in the batch are recorded as failed with the error reason, `processed_docs` is set to 0, and node status is marked `FAILED`

### Requirement: Stale primary key cleanup
The operator SHALL identify existing document primary keys in the vector database for the file IDs being processed and delete stale chunks prior to inserting updated document chunks.

#### Scenario: Re-indexing updated document
- **WHEN** a document with an existing file ID is indexed with new chunks
- **THEN** any preexisting chunks associated with that file ID that are not part of the new chunk set are deleted from the vector database

### Requirement: Batch document indexing and error isolation
The operator SHALL index documents in batches according to configured batch size, aggregating chunk-level failures and associating them with their corresponding parent document IDs.

#### Scenario: Partial chunk indexing failure
- **WHEN** specific chunks fail during bulk indexing
- **THEN** the parent documents of the failed chunks are recorded in metadata as failed documents, and successful documents are recorded in `processed_docs`

### Requirement: Operator metadata and parameter introspection
The operator SHALL expose its configurable parameters, defaults, and data types via `get_metadata()` for API introspection.

#### Scenario: Operator metadata query
- **WHEN** `GET /api/v1/operators/metadata` is called
- **THEN** the metadata response includes parameter definitions for provider, doc ID column, create index, vector dimensions, and sparse vector settings

### Requirement: Vector store resource metadata and flow enrichment
The vector database adapters SHALL provide live resource introspection for flow enrichment endpoints, retrieving available indices/collections, existing schema definitions, and resolving default feature mappings.

#### Scenario: Live resources discovered during enrichment
- **WHEN** flow feature enrichment is requested for a vectordb node with valid connection configuration
- **THEN** available indices or collections are fetched from the vector store and returned in `available_resources`

#### Scenario: Selected resource schema and feature mapping resolution
- **WHEN** an existing index or collection name is selected in provider config
- **THEN** its schema is retrieved in `selected_resource_schema` and feature mappings are aligned with the incoming available features

#### Scenario: Unreachable vector store during enrichment
- **WHEN** the vector database is unreachable or connection fails during enrichment
- **THEN** an empty fallback metadata structure is returned without raising an unhandled exception or breaking flow enrichment
