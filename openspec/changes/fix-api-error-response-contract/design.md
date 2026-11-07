# Design

## Context

The baseline payload middleware builds `detail` responses and converts `Content-Length` with unguarded `int()`.
Negative values pass that conversion. Payload validation runs before transaction tracking, so early rejections can
lack a trace ID. Transaction middleware reads `X-Global-Transaction-Id` and returns `X-Transaction-ID`.

It accepts arbitrary non-empty values, but `ErrorResponse.trace` has UUID format constraints. Without a fallback,
a handled 413 or 400 can become a 500. This failure must be addressed within this change.

## Approach

### Payload errors and declared lengths

- Reuse `ErrorResponse`, `ErrorDetail`, and existing error-response helpers. Share construction between both 413 paths.
- Use `invalid_request` for oversized payloads and `invalid_parameter` for invalid `Content-Length`.
- Catch integer-conversion failures explicitly and reject negative parsed values with structured HTTP 400.
  This includes empty, whitespace-only, nonnumeric, and fractional values that reach the application.
- Preserve existing integer parsing for non-negative values, including leading plus signs and surrounding whitespace.
  Stricter syntax is outside this proposal. Parseable non-negative lengths above 5 MiB return 413, not 400;
  no separate numeric upper bound is introduced.
- Keep actual-body-size checks for missing or understated lengths and accepted-body replay unchanged.

### Trace fallback on payload rejection

Preserve incoming IDs unchanged when they satisfy the existing `ErrorResponse.trace` constraints. For absent, empty,
or incompatible values, generate a compatible UUID for both the error body and outgoing `X-Transaction-ID`.
Preserve the original payload status and error code; an invalid trace must not replace the payload error.

Check compatibility with the actual DTO constraints, not merely whether `uuid.UUID()` accepts the value. An uppercase
UUID is parseable but fails the existing lowercase pattern and therefore uses the fallback. Do not relax the response
schema or accept `X-Transaction-ID` as another incoming header.

Transaction middleware retains a local ID and writes the outgoing header after the payload response is built.
Changing only the body or request state is insufficient: the component writing the outgoing header must use the same
effective rejection ID as the error response, rather than overwrite it with the original incompatible input.
How the components share that ID is an implementation detail.

Check request state and logging context used by rejection diagnostics for stale IDs when implementing the fallback.
This is an internal consistency consideration, not a separate public contract requiring every logging context or
previously recorded telemetry event to be rewritten. Successful-request handling of arbitrary IDs remains outside
this change; the fallback is required for requests rejected by payload validation.

### Middleware order and boundaries

The planned request order is `CORS -> Transaction -> Payload -> Logging -> Security`. Only transaction tracking before
payload validation and CORS outside both are contract requirements. Logging and security positions are design details.
Starlette executes middleware in reverse registration order. CORS-owned preflights retain their existing plain-text
responses without an error envelope or transaction header. Allowed origins receive CORS headers on payload errors.

Transaction tracking must run before either payload rejection path. Keep payload validation as raw ASGI middleware
with its existing receive/replay behavior. Do not introduce response buffering or change CORS permissions.

This work stays in the backend API middleware and DTO/helper layer. Domain models, application services, ports,
adapters, routes, and storage are unaffected.

## Risks and Checks

- Test compatible, absent, empty, arbitrary, whitespace-only, and uppercase-UUID IDs on both oversized-body paths and
  invalid-length errors. Verify status, error schema, and matching body/header traces; inspect rejection diagnostics
  for stale trace IDs where applicable.
- Preserve successful requests with arbitrary IDs; avoid turning the fallback into a general header-policy change.
- Test allowed/denied preflights, allowed-origin headers on 400/413 responses, successful bodies, separate request
  chunks, exact-limit bodies, and streamed responses.
- Test negative, plus-signed, whitespace-padded, empty, nonnumeric, fractional, and oversized declared lengths.
  Preserve method scoping and ensure actual size still prevents understated lengths from bypassing the limit.

## Migration

No migration or new dependency is needed. Negative declared lengths receive 400. Rejected payloads with incompatible
trace IDs receive a generated UUID rather than the supplied value. Maintainer review of this revised contract is
pending.
