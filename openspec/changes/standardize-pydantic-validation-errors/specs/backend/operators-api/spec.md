# Spec Delta

## ADDED Requirements

### Requirement: Standardized Pydantic configuration validation errors
Flow validation, operator execution, and orchestration boundaries SHALL format Pydantic configuration errors uniformly across all operators without emitting separate diagnostic dictionaries or stringifying raw exceptions. Missing fields SHALL be formatted as `<field_path> is not provided`.

#### Scenario: Missing configuration field formatting
- **WHEN** flow validation encounters a missing required field in an operator configuration
- **THEN** the validation error message for that field is formatted as `<field_path> is not provided` without separate input diagnostics

#### Scenario: Nested field and array indexing location formatting
- **WHEN** validation encounters an error on a nested model field or array element (e.g. `loc = ("connection_params", "paths", 0)`)
- **THEN** the field location in the formatted error message is represented using dot notation for object keys and bracket notation for array indices (`connection_params.paths[0]`)

#### Scenario: Built-in constraint and type error field path association
- **WHEN** a built-in Pydantic constraint or type check (e.g. `greater_than_equal`, `int_parsing`) fails on a field location
- **THEN** the formatted message combines the location label and message body as `<field_path>: <msg>` (e.g. `count: Input should be greater than or equal to 1`)

#### Scenario: Standard ValueError message prefix normalization
- **WHEN** an operator Pydantic field validator raises a standard ValueError producing a `value_error` type with a `Value error, ` prefix on a field
- **THEN** the message body is normalized from `Value error, <message>` to `Value error: <message>` and combined with the location label as `<field_path>: Value error: <message>` (or `Value error: <message>` when the inner text after `Value error: ` already starts with `<field_path>`)

#### Scenario: Custom Pydantic error with value_error prefix collision
- **WHEN** a custom Pydantic error uses the exact `value_error` code and its rendered message body starts with `Value error, `
- **THEN** the message body is normalized to start with `Value error: ` and combined with the location label as `<field_path>: Value error: <remainder>` (or `Value error: <remainder>` when the inner text after `Value error: ` already starts with `<field_path>` or when unprefixed)

#### Scenario: Custom Pydantic error message preservation
- **WHEN** an operator Pydantic validator raises a custom Pydantic error on a field with a distinct type code or without a `Value error, ` prefix
- **THEN** the rendered message body is preserved verbatim and combined with the location label as `<field_path>: <message_body>` (or `<message_body>` when unprefixed or already starting with `<field_path>`), without exposing internal error context diagnostics or separate input values

#### Scenario: Model-level validation error without location
- **WHEN** a model-level validator raises a validation error with an empty location (`loc = ()`)
- **THEN** the formatted error message contains the normalized message body directly without a leading location label or colon (e.g. `Value error: <message>`)

#### Scenario: Runtime execution configuration failure reporting
- **WHEN** an operator encounters a Pydantic configuration validation error during execution (including with flow validation disabled)
- **THEN** the failure recorded in document metadata, operator logs, and executor exceptions contains the normalized error message without Pydantic's separate input, context, or URL diagnostic dictionaries and without stringifying raw `ValidationError` exception representations

#### Scenario: Orchestration executor constructor error normalization
- **WHEN** an operator constructor raises a Pydantic `ValidationError` during execution node construction in `PythonOperatorExecutor`
- **THEN** the executor intercepts the `ValidationError` and raises a `DocpipeException` containing the formatted, normalized error messages without leaking raw exception trace representations
