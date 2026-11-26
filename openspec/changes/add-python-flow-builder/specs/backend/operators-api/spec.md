# Spec Delta

## ADDED Requirements

### Requirement: Flow validation uses shared parameter contracts
`POST /api/v1/validation/validate_flow` SHALL apply the same built-in parameter contracts as Python authoring to both authoring and Elyra inputs. Schema errors SHALL retain the existing HTTP 200 validation response envelope, identify node and parameter paths, and return FAILED without persisting the flow or initializing runtime resources.

#### Scenario: Equivalent invalid input formats
- **WHEN** authoring and Elyra flows contain the same chunker parameter typo
- **THEN** both return HTTP 200 with FAILED and diagnostics identifying the same node and invalid parameter

#### Scenario: Missing provider contract retained
- **WHEN** an ingest provider is absent, null, empty, or whitespace-only
- **THEN** existing INGEST_PROVIDER_MISSING diagnostics and provider-selection guidance remain intact

#### Scenario: Offline configuration validation
- **WHEN** a schema-valid flow references an unavailable vector service
- **THEN** validation does not fail solely because the service cannot be reached

### Requirement: Parameter metadata agrees with shared schemas
`GET /api/v1/operators/metadata` SHALL expose existing parameter names, types, defaults, requiredness, provider choices, and representable constraints consistently with shared configuration schemas. Labels, categories, availability flags, internal-feature filtering, and response shape SHALL remain compatible.

#### Scenario: Schema and metadata agreement
- **WHEN** metadata describes a configurable built-in operator
- **THEN** its declared types, defaults, and required fields agree with static parameter validation

### Requirement: Feature enrichment retains incomplete-flow tolerance
`POST /api/v1/validation/enrich_flow_features` SHALL continue tolerating incomplete editor flows and returning an enriched copy without runtime initialization. Strict execution validation SHALL NOT make incomplete feature enrichment a persistence operation or a hard failure solely for missing configuration.

#### Scenario: Incomplete editor node
- **WHEN** a flow contains a partially configured node during feature enrichment
- **THEN** the service preserves supported enrichment and warning behavior without mutating the request body or creating operator resources
