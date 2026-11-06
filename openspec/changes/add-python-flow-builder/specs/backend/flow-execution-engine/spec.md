# Spec Delta

## ADDED Requirements

### Requirement: Parameter preflight precedes runtime resource initialization
After the existing cancellation check, execution SHALL validate effective built-in operator parameters using the shared configuration contracts before initializing operator resources. Parameter failures SHALL identify the node and field. Existing graph-validation controls SHALL NOT bypass mandatory parameter safety checks.

#### Scenario: Invalid value before vector connection
- **WHEN** a flow contains an invalid built-in parameter and its vector database is unavailable
- **THEN** execution reports the parameter error before connecting to that database or running an operator

#### Scenario: Already cancelled
- **WHEN** the job run is already cancelling before execution
- **THEN** existing cancellation handling aborts execution before parameter preflight

#### Scenario: Graph validation disabled
- **WHEN** a flow disables graph validation and supplies an invalid built-in parameter
- **THEN** mandatory parameter preflight still rejects that parameter while the configured graph-validation bypass remains effective

### Requirement: Resolved values receive execution checks
Execution SHALL retain existing environment and provider checks after secret resolution. Deferred schema constraints SHALL be checked against resolved values before the affected resource is used. Diagnostics SHALL NOT reveal resolved secret values.

#### Scenario: Invalid referenced value
- **WHEN** an environment reference resolves to a value incompatible with its declared field
- **THEN** execution reports the node and parameter without displaying the secret value or using the affected resource

### Requirement: Schema checks preserve execution data contracts
Shared parameter validation SHALL preserve existing PyArrow operator inputs, outputs, metadata counters, and feature propagation semantics. Runtime-injected fields SHALL remain available to operators without being interpreted as unknown authored parameters.

#### Scenario: Existing compiled flow
- **WHEN** a valid compiled flow includes available-feature metadata and generated branch links
- **THEN** parameter validation accepts those internal fields and operators receive their existing runtime configuration and table contracts
