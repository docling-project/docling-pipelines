# backend/operators-api Specification

## Purpose

The operators-api capability is the REST API surface for operator introspection and flow validation. It exposes three endpoints: one to retrieve metadata for all registered operators (categories, features, parameters), one to validate a flow definition without persisting it, and one to enrich an Elyra flow definition with feature propagation metadata for each node. Together these endpoints power the UI palette, the node properties panel, and the real-time validation notification bar.

## Requirements

### Requirement: Get all operator metadata
`GET /api/v1/operators/metadata` SHALL return a cached singleton dictionary keyed by operator `short_name`, providing metadata (labels, categories, features, attributes, availability) for all registered operators while excluding internal features.

#### Scenario: All registered operators returned
- **WHEN** `GET /api/v1/operators/metadata` is called
- **THEN** the response is 200 with a dict containing one entry per registered operator, keyed by `short_name`

#### Scenario: Internal features excluded
- **WHEN** `GET /api/v1/operators/metadata` is called
- **THEN** no internal features (e.g. `doc_id_hash`) appear in any operator's `features` dict

#### Scenario: Attribute defaults and types included
- **WHEN** `GET /api/v1/operators/metadata` is called for an operator with configurable attributes
- **THEN** each attribute entry includes `type`, `description`, `required`, and `default` (when defined)

#### Scenario: Unavailable operator flagged
- **WHEN** an operator's `is_available()` returns `False`
- **THEN** `is_operator_available` is `False` for that operator in the response

### Requirement: Validate a flow definition
`POST /api/v1/validation/validate_flow` SHALL validate an authoring or Elyra flow definition without persisting it, returning a 200 response with a `FlowValidationResponse` body containing status, errors, and warnings.

#### Scenario: Valid authoring flow returns SUCCEEDED
- **WHEN** `POST /api/v1/validation/validate_flow` is called with a structurally valid authoring-format flow
- **THEN** the response is 200 with `status="SUCCEEDED"`, `errors=[]`, and `warnings=[]`

#### Scenario: Invalid flow returns FAILED with error details
- **WHEN** `POST /api/v1/validation/validate_flow` is called with a flow referencing an unknown operator
- **THEN** the response is 200 with `status="FAILED"` and `errors` containing an entry with `code="OPERATOR_NOT_FOUND"`

#### Scenario: Flow with warnings returns SUCCEEDED_WITH_WARNINGS
- **WHEN** `POST /api/v1/validation/validate_flow` is called with a flow that has non-fatal issues
- **THEN** the response is 200 with `status="SUCCEEDED_WITH_WARNINGS"` and a non-empty `warnings` list

#### Scenario: Elyra format accepted when is_elyra=true
- **WHEN** `POST /api/v1/validation/validate_flow?is_elyra=true` is called with a valid Elyra pipeline JSON
- **THEN** the response is 200 with `status="SUCCEEDED"`

#### Scenario: Malformed request body returns 400
- **WHEN** `POST /api/v1/validation/validate_flow` is called with an empty body or missing required fields
- **THEN** the response is 400

### Requirement: Enrich flow with feature metadata
`POST /api/v1/validation/enrich_flow_features` SHALL accept an Elyra pipeline JSON and return an enriched copy with `available_features`, `input_features`, and `output_features` merged into each node's parameters, tolerating incomplete flows with warnings.

#### Scenario: Each node enriched with feature metadata
- **WHEN** `POST /api/v1/validation/enrich_flow_features` is called with a valid Elyra pipeline
- **THEN** the response is 200 with the input JSON enriched with `available_features`, `input_features`, and `output_features` in each node's `parameters`

#### Scenario: Partial flow tolerated (warnings-only)
- **WHEN** `POST /api/v1/validation/enrich_flow_features` is called with an incomplete flow that would only produce warnings
- **THEN** the response is 200 with feature metadata enriched for the nodes that are valid

#### Scenario: Original body not mutated
- **WHEN** `POST /api/v1/validation/enrich_flow_features` is called
- **THEN** the returned JSON is a deep copy; the original request payload is not modified in place

#### Scenario: Empty body returns 400
- **WHEN** `POST /api/v1/validation/enrich_flow_features` is called with an empty `{}`
- **THEN** the response is 400

### Requirement: Missing ingest provider produces an actionable alert
The validation endpoint SHALL return HTTP 200 with status FAILED and an INGEST_PROVIDER_MISSING message code for ingest sources whose provider is absent, null, empty, or whitespace-only. The error SHALL identify the ingest node and instruct the user to select a provider in both authoring and Elyra formats, including validation invoked after a Canvas save.

#### Scenario: Authoring flow missing provider
- **WHEN** an authoring flow with a missing ingest provider is submitted for validation
- **THEN** the response contains the provider-selection error and ingest node identification

#### Scenario: Elyra flow missing provider
- **WHEN** an Elyra flow with a missing ingest provider is submitted for validation
- **THEN** the response contains the provider-selection error and ingest node identification
