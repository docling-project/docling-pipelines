# Align payload validation errors with the API contract

## Why

The payload-size middleware returns a `detail` response when a request is too large, but the API spec says errors should use the `ErrorResponse` format. A non-numeric `Content-Length` can also raise an exception instead of returning a 400 response. Separately, the flows API spec names the wrong incoming transaction header.

These differences make error handling less predictable for API clients and make rejected requests harder to trace.

## What Changes

- Return an `ErrorResponse` for HTTP 413, whether the request is rejected using `Content-Length` or the actual body size.
- Return HTTP 400 in the same format when `Content-Length` is not numeric.
- Correct the spec to name `X-Global-Transaction-Id` as the incoming header. The response header remains `X-Transaction-ID`.
- Ensure requests rejected by payload validation have a trace ID that is reflected in the response.

## Capabilities

### Modified Capabilities

- `backend/flows-api`: clarify the error response and transaction header contract for API requests, including payload validation failures.

## Impact

Backend-only. The implementation will affect API middleware and the related unit tests. No changes are needed to routes, storage, dependencies, or the 5 MiB request limit.

## Non-goals

- Change the size limit or which HTTP methods are checked.
- Add support for `X-Transaction-ID` as an incoming header.
- Refactor unrelated exception handling or tracing code.
