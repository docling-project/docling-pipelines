# Spec Delta

## Purpose

The api-client capability defines the frontend-backend communication boundary, providing base URL resolution (BFF proxy vs direct API), request header injection (transactions and credentials), error normalization into Redux-friendly payload structures, and centralized service endpoint definitions.

## ADDED Requirements

### Requirement: Base URL and proxy resolution
The API client layer SHALL resolve backend endpoints against the relative `/api` path when proxied through the BFF server, or against the configured backend base URL when direct API communication is enabled.

#### Scenario: Relative path resolution under BFF proxy
- **WHEN** an API request is initiated by any service client
- **THEN** the request targets `/api/*`, delegating upstream routing to the backend service

### Requirement: Standardized error normalization
The API client layer SHALL normalize HTTP errors, network failures, and backend error response payloads into a consistent error structure containing message, status code, and optional error details for Redux store consumption.

#### Scenario: Backend JSON error normalized
- **WHEN** the backend returns an HTTP 4xx or 5xx response with a JSON error body
- **THEN** the client extracts the error message and status code into a normalized error object passed to the rejected Redux action

#### Scenario: Network disconnect or unreachable backend
- **WHEN** an HTTP request fails due to network termination or timeout
- **THEN** the client generates a descriptive fallback error object with a network error flag

### Requirement: Request header and transaction tracking
The API client layer SHALL attach required request headers, including content type (`application/json`) and client-side transaction identifiers, across all outgoing mutation and fetch requests.

#### Scenario: Mutation request sends JSON content headers
- **WHEN** a POST, PUT, or PATCH request is dispatched
- **THEN** the outgoing request headers contain `Content-Type: application/json` and any active transaction trace tokens

### Requirement: Centralized endpoint constants
All frontend API calls SHALL reference centralized endpoint constants defined within the API service layer rather than hardcoded string URLs across component files.

#### Scenario: Service calls use centralized endpoint constants
- **WHEN** an API service function is called (e.g. `flowsApi.getFlows()`)
- **THEN** the request URL is constructed using the corresponding endpoint constant
