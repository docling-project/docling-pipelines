# Spec Delta

## MODIFIED Requirements

### Requirement: Vector store resource metadata and flow enrichment
The vector database adapters SHALL provide live resource introspection for flow enrichment endpoints, retrieving available indices/collections, existing schema definitions (including dense, sparse, and binary vector dimensions and index information), supporting collections with `FLOAT_VECTOR` or `BINARY_VECTOR` fields, and resolving default feature mappings.

#### Scenario: Live resources discovered during enrichment
- **WHEN** flow feature enrichment is requested for a vectordb node with valid connection configuration
- **THEN** available indices or collections are fetched from the vector store and returned in `available_resources`

#### Scenario: Selected resource schema and feature mapping resolution
- **WHEN** an existing index or collection name is selected in provider config
- **THEN** its schema is retrieved in `selected_resource_schema` and feature mappings are aligned with the incoming available features

#### Scenario: Binary vector collection schema and metadata inspection
- **WHEN** an existing Milvus collection contains a `BINARY_VECTOR` field
- **THEN** its bit dimension and index metadata (such as `HAMMING` / `JACCARD` metric and binary index type) are extracted into `selected_resource_schema` and `stored_resource_metadata`

#### Scenario: Binary vector collection support check
- **WHEN** an existing Milvus collection contains a `BINARY_VECTOR` field with an index created
- **THEN** `is_docpipe_supported_resource` evaluates to `supported: True` without requiring a `FLOAT_VECTOR` field

#### Scenario: Unreachable vector store during enrichment
- **WHEN** the vector database is unreachable or connection fails during enrichment
- **THEN** an empty fallback metadata structure is returned without raising an unhandled exception or breaking flow enrichment
