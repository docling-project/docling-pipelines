## MODIFIED Requirements

### Requirement: Error response format

All error responses SHALL conform to the `ErrorResponse` schema: a JSON object with `errors` (list of objects with `code`, `message`, and optional `target`), `trace` (request trace ID), and `status_code`. The `trace` field SHALL match the `X-Global-Transaction-Id` request header when present. The effective trace ID SHALL be returned in the `X-Transaction-ID` response header.

#### Scenario: Error response includes trace ID
- **WHEN** a request that produces an error includes an `X-Global-Transaction-Id` header containing a UUID
- **THEN** `ErrorResponse.trace` and the `X-Transaction-ID` response header contain that UUID

#### Scenario: Rejected request gets a generated trace ID
- **WHEN** an API request is rejected by payload validation without an `X-Global-Transaction-Id` header
- **THEN** the error body contains a generated trace ID that matches the `X-Transaction-ID` response header

#### Scenario: Content-Length exceeds the payload limit
- **WHEN** a POST, PUT, or PATCH request declares a `Content-Length` greater than 5 MiB
- **THEN** the API returns HTTP 413 with an `ErrorResponse` body containing `errors`, `trace`, and `status_code` set to 413

#### Scenario: Streamed request body exceeds the payload limit
- **WHEN** a POST, PUT, or PATCH request body exceeds 5 MiB even if `Content-Length` is missing or understated
- **THEN** the API returns HTTP 413 with the same `ErrorResponse` structure

#### Scenario: Invalid Content-Length
- **WHEN** a POST, PUT, or PATCH request has a non-numeric `Content-Length` that reaches the application
- **THEN** the API returns HTTP 400 with an `ErrorResponse` body instead of an unhandled exception
