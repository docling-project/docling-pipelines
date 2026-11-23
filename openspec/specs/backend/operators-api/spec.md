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

### Requirement: Standardized Pydantic configuration error rendering
Pydantic configuration validation errors SHALL be rendered by one shared formatter, without Pydantic's `input`, `ctx` or `url` diagnostics, wherever they are returned in validation alerts, logs, failure metadata or exception messages. The formatter SHALL NOT read `ctx["error"]`.

#### Scenario: Missing field
- **WHEN** a required field is absent from an operator configuration
- **THEN** the message is `<field_path> is not provided`

#### Scenario: Nested field and list index
- **WHEN** an error location is `("connection_params", "paths", 0)`
- **THEN** the field path is rendered as `connection_params.paths[0]`

#### Scenario: Field-level error
- **WHEN** a built-in constraint, type check, validator or custom error fails on a field with a non-empty path
- **THEN** the message is `<field_path>: <message>`, even when the message repeats the field name

#### Scenario: Model-level error
- **WHEN** a model validator fails with an empty location and no configuration prefix is supplied
- **THEN** the message is the normalized message body without a leading label or colon

#### Scenario: Value error prefix normalization
- **WHEN** an error has type `value_error` and its message begins with `Value error, `
- **THEN** that prefix is rendered as `Value error: `, and other error types keep their message unchanged

#### Scenario: Configuration prefix
- **WHEN** the sanitizer supplies a configuration key as the prefix
- **THEN** each field path is `<config_key>.<field_path>` and a model-level error is `<config_key>: <message>`

### Requirement: Sanitizer behavior is preserved
`sanitize_exception` SHALL render a `ValidationError` through the shared formatter and SHALL keep its fixed categories, its `<config_key>:` prefix, its cause-chain handling and its wrapper-message redaction.

#### Scenario: Validation error in a cause chain
- **WHEN** a wrapper exception is raised from a `ValidationError` whose input is a sentinel
- **THEN** the sentinel does not appear in the sanitized text and the text names the configuration key

### Requirement: Validators do not reflect credential-bearing input
Provider configuration validators SHALL NOT interpolate rejected input that can carry a credential into error messages. The only permitted reflected values are the local filesystem path in the filesystem source's `Root path does not exist` error and the Hugging Face HAP `model_id` in its missing-`toxic_labels` error.

#### Scenario: Credentials in a web source URL
- **WHEN** a web source configuration contains a URL with embedded credentials and an unsupported scheme
- **THEN** the validator-authored message, the `format_pydantic_errors` output and the `sanitize_exception` output do not contain those credentials, while the raw `str(ValidationError)` may still contain them in Pydantic's own input diagnostics

#### Scenario: Environment reference in a vector store credential
- **WHEN** a Weaviate configuration uses an environment reference for `api_key`, `bearer_token`, `username` or `password` whose variable is not set
- **THEN** the validator-authored message names the failing field and does not contain the reference name, and the `format_pydantic_errors` and `sanitize_exception` output do not contain it either

#### Scenario: Permitted filesystem path diagnostic
- **WHEN** a filesystem source configuration names a root path that does not exist
- **THEN** the message may include that path as a permitted non-sensitive diagnostic

#### Scenario: Permitted Hugging Face model identifier diagnostic
- **WHEN** a Hugging Face HAP configuration uses a non-default `model_id` without `toxic_labels`
- **THEN** the message may include that model identifier, and both `format_pydantic_errors` and `sanitize_exception` preserve it as a permitted non-sensitive diagnostic

### Requirement: Handlers render configuration failures without raw text
Adapters, validation boundaries and local log handlers that handle a constructor or configuration failure SHALL render it through the shared formatter or `sanitize_exception` rather than `str(exc)`, and SHALL NOT emit a raw traceback or chained exception text.

#### Scenario: Presidio or Watsonx provider configuration error
- **WHEN** a Presidio or Watsonx provider configuration is rejected with a sentinel input value
- **THEN** the returned message includes the provider prefix and field path and does not contain the sentinel, `input_value` or the Pydantic documentation URL

#### Scenario: Operator constructor failure during flow validation
- **WHEN** an operator constructor raises a `ValidationError` during flow validation
- **THEN** the resulting validation alert contains a rendered message without the rejected input

#### Scenario: ACL adapter initialization failure
- **WHEN** ACL adapter configuration is rejected and the failing field holds a sentinel value
- **THEN** the raised `FlowExecutionFailedException` message and every emitted log record, including any attached traceback text, do not contain the sentinel, and the original exception remains available as `__cause__`

#### Scenario: Swallowed lazy-fetch or OCR option error
- **WHEN** Google Drive or Box lazy binary fetch, or Docling OCR option construction, hits a `ValidationError` whose input is a sentinel and handles it by returning `None` or falling back to defaults
- **THEN** the return value or fallback is unchanged and no emitted log record, including any traceback text, contains the sentinel or Pydantic's `input_value`

### Requirement: Adapter-owned error selection
Adapters SHALL keep their own error-selection policy while rendering messages through the shared formatter.

#### Scenario: Hugging Face unknown keys during flow validation
- **WHEN** the Hugging Face HAP adapter validates a provider configuration with unknown keys during flow validation
- **THEN** unknown-key errors are not reported by the adapter and are still reported on direct construction
