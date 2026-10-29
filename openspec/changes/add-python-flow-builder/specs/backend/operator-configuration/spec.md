# Spec Delta

## Purpose

Provide consistent, typed configuration contracts for document pipeline operators and providers, so authoring tools can reject invalid parameters before runtime resources are initialized.

## ADDED Requirements

### Requirement: Cover the public built-in catalog
The public `docpipe.config` namespace SHALL provide named configuration models for every public built-in operator. Models SHALL use existing authoring parameter names, defaults, supported aliases, and nested structures. Internal `doc_id_hash` SHALL remain excluded from the public catalog.

#### Scenario: Catalog coverage
- **WHEN** the baseline built-in registry is compared to public configuration exports
- **THEN** typed coverage exists for ingest_source, extract_operator, branching, chunker, embeddings, merge, noop, entity_curation, document_classifier, doc_quality, ededup, lang_detect, ml_enrichment, pii_and_hap, readability, redaction, sql_filter, vectordb, document_set, acl_operator, and storage_output

#### Scenario: Optional dependencies absent
- **WHEN** configuration models are imported with optional model/provider packages absent
- **THEN** configurations can still be authored and serialized while runtime availability remains separately reportable

### Requirement: Validate authored values strictly
Configuration validation SHALL reject unknown authored keys, wrong scalar/container types, invalid enum values, missing required fields, out-of-range values, and invalid cross-field combinations. Booleans SHALL NOT satisfy integer fields. Error details SHALL identify a parameter path without exposing secret values.

#### Scenario: Typo and type errors
- **WHEN** a chunker is configured with `chunk_szie` or `chunk_size="large"`
- **THEN** validation identifies the unknown key or incorrect type instead of ignoring or coercing it

#### Scenario: Cross-field constraint
- **WHEN** chunk overlap violates the active chunker's declared relationship with chunk size
- **THEN** validation rejects the combination before an operator is instantiated

#### Scenario: Multiple errors
- **WHEN** a dictionary contains multiple invalid fields
- **THEN** flow validation reports all schema errors with node and field paths rather than stopping at the first field

### Requirement: Select nested schemas by provider
Nested provider dictionaries SHALL be validated against the schema selected by the corresponding provider field. Existing aliases SHALL resolve consistently. Provider-declared passthrough settings SHALL be retained; unknown keys for closed providers SHALL fail. Provider discovery for static validation SHALL NOT instantiate adapters.

#### Scenario: Required provider parameter missing
- **WHEN** an OpenSearch configuration omits its required resource name
- **THEN** validation identifies the missing provider parameter before creating a vector-store adapter

#### Scenario: Explicit passthrough
- **WHEN** a LiteLLM provider accepts additional request options under its documented passthrough policy
- **THEN** those options survive validation and serialization

#### Scenario: Closed provider typo
- **WHEN** a closed provider configuration contains an undeclared parameter
- **THEN** validation reports the nested path and rejects the configuration

### Requirement: Static validation has no resource side effects
Configuration construction, schema inspection, serialization, and static validation SHALL NOT load models, download resources, open databases, probe remote services, inspect path existence, or write files. Environment-dependent checks SHALL run during execution preflight or existing runtime checks.

#### Scenario: Author on a different machine
- **WHEN** a filesystem source is configured with a syntactically valid path absent locally
- **THEN** configuration construction succeeds and path availability is checked only for execution

#### Scenario: Inspect model settings offline
- **WHEN** extraction and embedding configurations are created without models installed
- **THEN** no model loading or downloads occur

### Requirement: Preserve deferred secret references
Existing environment and vault reference syntax SHALL survive static validation and serialization unchanged. Checks requiring resolved values SHALL be deferred and repeated after existing secret resolution. A reference SHALL defer only dependent checks, not validation of unrelated literal fields.

#### Scenario: Reference credentials
- **WHEN** a provider credential is `${OPENSEARCH_PASSWORD}` or a supported vault reference
- **THEN** static validation retains the reference without contacting its resolver

#### Scenario: Invalid literal alongside reference
- **WHEN** a provider has referenced credentials and a literal port with an invalid type
- **THEN** validation still reports the invalid port

### Requirement: Share validation across authoring surfaces
Equivalent built-in configurations SHALL have the same parameter acceptance and rejection rules in typed Python, authoring JSON, CLI validation, and REST authoring/Elyra validation. Runtime graph fields and recognized global settings SHALL be separated from authored operator parameters before strict checking.

#### Scenario: Consistent invalid chunk size
- **WHEN** equivalent flows specify an invalid chunk size through each supported authoring surface
- **THEN** all surfaces reject that field with equivalent node and parameter identification

#### Scenario: Runtime-injected metadata
- **WHEN** compiled nodes contain generated link data or injected available-feature metadata
- **THEN** strict authored-key validation does not reject those recognized runtime fields

### Requirement: Preserve global inheritance and overrides
Validation SHALL use the effective configuration formed by recognized global settings and node overrides. Explicit node values SHALL take precedence. Schema defaults SHALL NOT accidentally mask inherited values. Unknown operator keys SHALL NOT be hidden by moving them into global configuration.

#### Scenario: Inherited content column
- **WHEN** the flow declares a custom global content column and the node omits its column setting
- **THEN** validation and execution use the inherited column

#### Scenario: Explicit node override
- **WHEN** a node explicitly declares its content column
- **THEN** that value overrides the global setting in both validation and execution

### Requirement: Preserve declared configuration on export
Configuration export SHALL preserve supplied values and supported aliases without mutating caller dictionaries. It SHALL distinguish omitted fields from explicitly supplied defaults when inheritance depends on that distinction. Exported nested values SHALL be JSON-compatible.

#### Scenario: Default-valued override
- **WHEN** a user explicitly supplies an operator default that differs from the inherited global value
- **THEN** export retains that explicit override

### Requirement: Extend schemas without hard-coded provider switches
Registered custom operators and providers SHALL be able to supply pure configuration schemas. Schema resolution SHALL follow the same operator/provider selection as execution. An extension without a schema SHALL retain legacy execution validation and receive a static coverage warning.

#### Scenario: Custom override schema
- **WHEN** a selected custom operator uses a built-in short name and declares a different schema
- **THEN** its own schema validates the generic configuration

### Requirement: Keep metadata aligned with validation
Public parameter descriptions, defaults, choices, and required-field metadata SHALL be derived from or checked against the same configuration contracts used for validation. Existing labels, categories, feature descriptors, and internal-feature filtering SHALL be preserved.

#### Scenario: Shared declared constraint
- **WHEN** a chunker parameter declares a supported set of choices
- **THEN** introspection and validation agree about those choices

### Requirement: Preserve processing contracts
Configuration modernization SHALL NOT change built-in PyArrow input/output column contracts or transform metadata counters. Tables SHALL remain the inter-operator data format, and transformation results SHALL retain `tuple[list[pa.Table], dict]` semantics.

#### Scenario: Existing valid flow
- **WHEN** an existing valid flow uses the new shared configuration checks
- **THEN** its required columns, output columns, and execution metadata remain compatible with the existing operator contract
