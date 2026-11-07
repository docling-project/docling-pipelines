# Tasks

## 1. Review gate

Maintainer approval of the revised proposal remains pending. Review must cover payload-error trace fallback, explicit
middleware order, and negative `Content-Length` before implementation is accepted. This is a prerequisite, not an
implementation checkbox completed by merging or archiving the change.

## 2. Update middleware

- [ ] 2.1 [backend] Return standard `ErrorResponse` from both 413 paths using `invalid_request`.
- [ ] 2.2 [backend] Return 400 with `invalid_parameter` for failed length conversion and negative parsed lengths;
  preserve 413 for parseable non-negative lengths above 5 MiB.
- [ ] 2.3 [backend] Generate a compatible UUID on payload rejection for absent or incompatible trace IDs; preserve
  payload status and ensure the outgoing-header writer uses the same effective trace as the error body.
- [ ] 2.4 [backend] Ensure transaction tracking precedes payload validation and CORS wraps both while preserving
  preflights, body replay, streaming, and successful-request tracing.

## 3. Regression tests

- [ ] 3.1 [backend] Assert `ErrorResponse` for declared and streamed oversized bodies, including understated lengths.
- [ ] 3.2 [backend] Cover compatible, absent, empty, arbitrary, whitespace-only, and uppercase-UUID trace headers on
  payload errors; verify status, schema, and body/header equality. Check rejection diagnostics for stale IDs where used.
- [ ] 3.3 [backend] Cover negative, plus-signed, whitespace-padded, empty, nonnumeric, fractional, and oversized
  declared lengths; preserve non-write method scoping and actual-body-size checks.
- [ ] 3.4 [backend] Test required middleware relationships, allowed/denied preflights, CORS headers on errors,
  successful bodies, exact-limit bodies, separate body chunks, streamed responses, and successful arbitrary trace IDs.

## 4. Verification

- [x] 4.1 [backend] Run `openspec validate fix-api-error-response-contract --strict`.
- [ ] 4.2 [backend] After revised-contract approval, run middleware and adjacent API tests, Ruff, relevant mypy checks,
  and `git diff --check`; review the implementation diff for unrelated changes.
