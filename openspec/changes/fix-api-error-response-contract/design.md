# Design

## Context

`PayloadValidationMiddleware` currently builds its own 413 response with a `detail` field. It also converts `Content-Length` using `int()` without checking for invalid input. In the application middleware stack, payload validation can run before transaction tracking, so an early rejection may not have a request trace ID yet.

The existing `TransactionMiddleware` already uses `X-Global-Transaction-Id` for incoming requests and returns `X-Transaction-ID` in responses. The spec should describe that behavior rather than introducing another accepted request header.

## Approach

- Keep the current 5 MiB limit and both rejection paths: the `Content-Length` check and the streamed-body check.
- Use the existing `ErrorResponse` model and error codes when building 413 and 400 responses. Use `invalid_request` for oversized payloads and `invalid_parameter` for malformed `Content-Length`.
- Make sure transaction tracking runs before payload validation in the effective ASGI middleware order. Rejected requests should use the same trace ID in their JSON body and outgoing `X-Transaction-ID` header.
- Keep body replay for accepted requests unchanged.
- Update the existing OpenSpec requirement to name the incoming `X-Global-Transaction-Id` header. Do not change the header read by `TransactionMiddleware`.

## Risks and Checks

Changing middleware order can affect response headers and request-body handling. Test early rejections alongside normal requests, streamed bodies, and the response trace header.

`ErrorResponse.trace` expects a UUID-shaped value, while transaction middleware currently accepts arbitrary non-empty header values. Regression tests for this change should use a valid UUID. If handling malformed transaction IDs is required, agree on that separately rather than adding a new header policy as part of this fix.

## Migration

No migration or new dependency is needed.
