# Spec Delta

## ADDED Requirements

### Requirement: Custom operator routes require authentication
Every `/api/v1/custom_operators` route, including list, get, `directory_tree`, create, update and delete, SHALL require a valid bearer token. A request without a valid token SHALL NOT reach the handler. When `JWT_SECRET_KEY` is missing or invalid, these routes SHALL return 503 and SHALL NOT invoke the custom operator service.

#### Scenario: Request without a token
- **WHEN** any `/api/v1/custom_operators` route is called without an `Authorization` header
- **THEN** the response is 401 or 403 and the custom operator service is not called

#### Scenario: Request with an invalid token
- **WHEN** any `/api/v1/custom_operators` route is called with a token that fails verification
- **THEN** the response is 401 and the custom operator service is not called

#### Scenario: Read routes are protected
- **WHEN** `GET /api/v1/custom_operators`, `GET /api/v1/custom_operators/{operator_id}` or `GET /api/v1/custom_operators/directory_tree` is called without a valid token
- **THEN** the response is not 200 and no operator inventory or file layout is returned

#### Scenario: JWT secret not configured
- **WHEN** `JWT_SECRET_KEY` is unset and any `/api/v1/custom_operators` route is called with a bearer token
- **THEN** the response is 503 and the custom operator service is not called

#### Scenario: Valid token
- **WHEN** a route is called with a valid bearer token
- **THEN** the handler runs and the existing success and error responses apply
