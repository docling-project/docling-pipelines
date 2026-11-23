# Spec Delta

## ADDED Requirements

### Requirement: Upload is restricted to configured identities when secrets are in use
When a secret provider is registered, create, update, and delete SHALL additionally require the authenticated username to appear in `custom_operators.allowed_uploaders`. An empty or unset list SHALL permit nobody. When no secret provider is registered, any authenticated user SHALL be permitted, as before.

#### Scenario: Authenticated but not listed
- **WHEN** a secret provider is registered, the caller is authenticated, and the caller is not in `custom_operators.allowed_uploaders`
- **THEN** the response is 403 and no file is stored

#### Scenario: Listed uploader
- **WHEN** a secret provider is registered and the caller is in `custom_operators.allowed_uploaders`
- **THEN** the operation proceeds

#### Scenario: No secret provider
- **WHEN** no secret provider is registered and the caller is authenticated
- **THEN** the operation proceeds without an uploader list

### Requirement: Custom operator changes are audited in a dedicated store
Every create, update, and delete attempt, including rejected ones, SHALL emit one structured JSON record to a dedicated `docpipe.audit` logger that debug and scrub filters cannot suppress. The record SHALL contain timestamp, caller, `operator_id`, `short_name`, action, `script_sha256`, and `outcome` (`success` or `rejected`). Retention SHALL be configurable by `audit.retention_days`.

#### Scenario: Successful change
- **WHEN** an operator is created, replaced, or deleted
- **THEN** one record with outcome `success`, the caller, operator, action, and script digest is written to `docpipe.audit`

#### Scenario: Rejected attempt
- **WHEN** a create, update, or delete is refused with 403 or a validation error
- **THEN** one record with outcome `rejected` is written to `docpipe.audit`

#### Scenario: Debug level does not hide the record
- **WHEN** `DS_LOG_LEVEL` is set to `WARNING`
- **THEN** audit records are still written
