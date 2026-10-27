# Spec Delta

## ADDED Requirements

### Requirement: Custom operator management is authorized and audited
Every `/api/v1/custom_operators` route that creates, updates, or deletes an operator SHALL require an authenticated caller when authentication is enabled, and SHALL emit one server-side audit record with timestamp, caller identity, operator identifier, `short_name`, action, and SHA-256 digest of the script. When authentication is disabled and a secret provider is registered, these routes SHALL return 403.

#### Scenario: Unauthenticated upload
- **WHEN** authentication is enabled and `POST /api/v1/custom_operators` is called without a valid token
- **THEN** the response is 401 and no file is stored

#### Scenario: Authentication disabled with Vault configured
- **WHEN** authentication is disabled, a secret provider is registered, and `POST /api/v1/custom_operators` is called
- **THEN** the response is 403 and no file is stored

#### Scenario: Audit record
- **WHEN** an operator is created, replaced, or deleted
- **THEN** one audit record naming the caller, operator, action, and script digest is written to the server-side log
