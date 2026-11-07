## MODIFIED Requirements

### Requirement: Error response format

Except for CORS-owned preflight responses, all error responses SHALL conform to `ErrorResponse`: a JSON object with
`errors` (a list of objects with `code`, `message`, and optional `target`), `trace`, and `status_code`.
The trace SHALL match `X-Global-Transaction-Id` when its value satisfies
existing `ErrorResponse.trace` constraints. For payload rejections with an absent, empty, or incompatible incoming ID,
the API SHALL generate a compatible UUID for both `ErrorResponse.trace` and the outgoing `X-Transaction-ID` header.
The effective trace ID SHALL be returned in `X-Transaction-ID`. An incompatible incoming ID SHALL NOT turn a payload
rejection into HTTP 500 or change its payload status and error code. This fallback does not define successful-request
tracing policy. CORS-owned preflight responses are exempt from this requirement's error-envelope and trace-header
rules and retain their existing response format.

#### Scenario: Error response includes trace ID

- **WHEN** a request producing an error includes an `X-Global-Transaction-Id` satisfying `ErrorResponse.trace`
- **THEN** the body trace and outgoing `X-Transaction-ID` contain that value unchanged

#### Scenario: Rejected request gets a generated trace ID

- **WHEN** payload validation rejects a request without `X-Global-Transaction-Id`, or with an empty value
- **THEN** the error body contains a generated UUID matching the outgoing `X-Transaction-ID`

#### Scenario: Incompatible transaction ID does not replace a payload error

- **WHEN** payload validation rejects a request whose `X-Global-Transaction-Id` fails `ErrorResponse.trace` constraints,
  including a non-UUID string, whitespace-only value, or uppercase UUID
- **THEN** the API returns `ErrorResponse` with a generated compatible UUID matching the outgoing `X-Transaction-ID`
- **AND** the response retains HTTP 413 with `invalid_request` for an oversized payload or HTTP 400 with
  `invalid_parameter` for invalid `Content-Length`, instead of returning HTTP 500

#### Scenario: Content-Length exceeds the payload limit

- **WHEN** a POST, PUT, or PATCH request declares a parseable non-negative `Content-Length` greater than 5 MiB
- **THEN** the API returns HTTP 413 with `ErrorResponse`, `errors[0].code` set to `invalid_request`, and `status_code`
  413

#### Scenario: Streamed request body exceeds the payload limit

- **WHEN** a POST, PUT, or PATCH body exceeds 5 MiB even if `Content-Length` is missing or understated
- **THEN** the API returns HTTP 413 with the same `ErrorResponse` structure and `invalid_request` code

#### Scenario: Invalid Content-Length

- **WHEN** a POST, PUT, or PATCH request has a `Content-Length` that reaches the application and cannot be parsed as
  a non-negative integer, including an empty, whitespace-only, nonnumeric, fractional, or negative value
- **THEN** the API returns HTTP 400 with `ErrorResponse` and `errors[0].code` set to `invalid_parameter`

## ADDED Requirements

### Requirement: Payload validation middleware order

Transaction tracking SHALL execute before payload validation can reject a request. CORS SHALL execute outside both
layers. This requirement does not prescribe the positions of logging or security middleware. Payload validation SHALL
preserve accepted-body replay and streamed responses.

#### Scenario: Trace initialized before early rejection

- **WHEN** a request is rejected for invalid `Content-Length`, excessive declared length, or actual body size
- **THEN** transaction tracking has already initialized request tracing, and the effective rejection trace matches
  between `ErrorResponse.trace` and the outgoing `X-Transaction-ID`

#### Scenario: CORS headers on payload errors

- **WHEN** a POST, PUT, or PATCH request from an allowed Origin is rejected by payload validation
- **THEN** its structured HTTP 400 or 413 response includes configured CORS headers and matching body/header traces

#### Scenario: Preflight handling is preserved

- **WHEN** a CORS preflight requesting an allowed method and headers reaches the application
- **THEN** CORS handles it before transaction tracking and payload validation, preserving existing allowed-origin 200
  and disallowed-origin 400 responses in their existing plain-text format without adding a transaction header

#### Scenario: Accepted bodies and streamed responses are preserved

- **WHEN** a request passes payload validation, including a chunked body or a body exactly at the 5 MiB limit
- **THEN** the downstream handler receives the complete body, and streamed responses retain their content and trace
  header
