## ADDED Requirements

### Requirement: Ingest source requires a provider
Flow validation through CLI, Python library, and execution entry points SHALL reject an ingest source whose provider is absent, null, empty, or whitespace-only with the message "Provider not added. Select a provider for the ingest source operator." Ingestion SHALL reject the same inputs before storage or source access even when flow validation is disabled.

#### Scenario: Missing provider fails validation
- **WHEN** a flow contains an ingest source with an absent, null, empty, or whitespace-only provider
- **THEN** validation reports a provider-selection error without a NoneType error

#### Scenario: Validation disabled
- **WHEN** ingestion starts without a provider and flow validation is disabled
- **THEN** ingestion raises the provider-selection error before storage or source access

#### Scenario: Valid provider preserves ingestion contract
- **WHEN** a configured ingest source executes with a valid provider
- **THEN** its existing PyArrow table output schema and transform metadata contract are preserved
