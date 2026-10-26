# Spec Delta

## MODIFIED Requirements

### Requirement: Index and collection lifecycle management
The operator SHALL manage the target vector store index or collection lifecycle automatically during transform, creating the index/collection when absent and validating schema compatibility when present, without exposing a user-configurable `create_index` option. When legacy configurations provide `create_index`, the operator SHALL log a deprecation warning and proceed with automatic index lifecycle handling.

#### Scenario: Index creation when absent
- **WHEN** the target index or collection does not exist at transform time
- **THEN** the operator creates the index or collection with detected vector dimensions and feature mappings before inserting documents

#### Scenario: Schema validation on existing index
- **WHEN** the target index or collection already exists at transform time
- **THEN** the operator validates the existing schema against detected dimensions and feature mappings without recreating the index

#### Scenario: Index creation disabled
- **WHEN** `create_index` is provided in operator configuration
- **THEN** the operator logs a deprecation warning that `create_index` is deprecated and proceeds with automatic index lifecycle handling

#### Scenario: Index creation or schema validation failure
- **WHEN** index creation or schema validation raises an exception
- **THEN** all unique documents in the batch are recorded as failed with the error reason, `processed_docs` is set to 0, and node status is marked `FAILED`

### Requirement: Operator metadata and parameter introspection
The operator SHALL expose its configurable parameters, defaults, and data types via `get_metadata()` for API introspection without including `create_index`.

#### Scenario: Operator metadata query
- **WHEN** `GET /api/v1/operators/metadata` is called
- **THEN** the metadata response includes parameter definitions for provider, doc ID column, vector dimensions, and sparse vector settings, and excludes `create_index`
