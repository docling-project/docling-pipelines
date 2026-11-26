# Align payload validation errors with the API contract

## Why

Payload validation returns `detail` instead of `ErrorResponse` for oversized requests. Invalid `Content-Length` can
raise an exception, and negative values pass integer conversion. The flows API spec also names the wrong trace header.

Transaction middleware accepts arbitrary non-empty IDs, while `ErrorResponse.trace` requires a UUID-shaped value.
Reusing the DTO without a fallback can turn a handled payload rejection into HTTP 500.

## What Changes

- Return `ErrorResponse` for HTTP 413 from both declared-length and actual-body-size checks, using `invalid_request`.
- Return HTTP 400 with `invalid_parameter` for lengths that cannot be parsed as non-negative integers.
- Keep HTTP 413 for parseable non-negative lengths greater than 5 MiB; introduce no separate numeric upper bound.
- Name `X-Global-Transaction-Id` as the incoming trace header; keep `X-Transaction-ID` as the response header.
- On payload rejection, preserve IDs accepted by `ErrorResponse.trace`; otherwise generate a compatible UUID.
  The body trace and outgoing header must match without changing the payload status or error code.
- Require transaction tracking before payload validation, with CORS outside both to preserve preflight handling and
  allowed-origin headers on payload errors.

## Capabilities

### Modified Capabilities

- `backend/flows-api`: specify payload error responses, trace fallback, middleware order, and invalid-length handling.

## Impact

Backend-only. API middleware and its tests are affected across POST, PUT, and PATCH requests, including flow routes.
No route, operator, storage, dependency, response-schema, or 5 MiB limit changes are needed. Negative declared lengths
now return 400. Payload errors with incompatible trace IDs receive a generated UUID instead of failing DTO validation.

## Non-goals

- Change the size limit, checked HTTP methods, accepted-body replay, or streamed responses.
- Accept `X-Transaction-ID` as an incoming trace header.
- Change successful-request tracing or define a general malformed-transaction-header policy.
- Introduce a new `Content-Length` syntax policy or another numeric upper bound.
- Refactor unrelated exception handling, logging, telemetry, authentication, or CORS permissions.
