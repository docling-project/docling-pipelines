# Spec Delta

## ADDED Requirements

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
Provider configuration validators SHALL NOT interpolate rejected input that can carry a credential into error messages. The only permitted reflected value is the local filesystem path in the filesystem source's `Root path does not exist` error.

#### Scenario: Credentials in a web source URL
- **WHEN** a web source configuration contains a URL with embedded credentials and an unsupported scheme
- **THEN** the validator-authored message, the `format_pydantic_errors` output and the `sanitize_exception` output do not contain those credentials, while the raw `str(ValidationError)` may still contain them in Pydantic's own input diagnostics

#### Scenario: Permitted filesystem path diagnostic
- **WHEN** a filesystem source configuration names a root path that does not exist
- **THEN** the message may include that path, and this is the only provider validator message that reflects its input

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
