## ADDED Requirements

### Requirement: Missing ingest provider produces an actionable alert
The validation endpoint SHALL return HTTP 200 with status FAILED and an INGEST_PROVIDER_MISSING message code for ingest sources whose provider is absent, null, empty, or whitespace-only. The error SHALL identify the ingest node and instruct the user to select a provider in both authoring and Elyra formats, including validation invoked after a Canvas save.

#### Scenario: Authoring flow missing provider
- **WHEN** an authoring flow with a missing ingest provider is submitted for validation
- **THEN** the response contains the provider-selection error and ingest node identification

#### Scenario: Elyra flow missing provider
- **WHEN** an Elyra flow with a missing ingest provider is submitted for validation
- **THEN** the response contains the provider-selection error and ingest node identification
