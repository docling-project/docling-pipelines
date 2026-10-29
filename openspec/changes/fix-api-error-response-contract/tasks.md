# Tasks

## 1. Review the contract

- [ ] 1.1 [backend] Get maintainer review of the OpenSpec change, including trace IDs on early payload rejections.

## 2. Update middleware

- [ ] 2.1 [backend] Return standard `ErrorResponse` bodies from both 413 rejection paths.
- [ ] 2.2 [backend] Return HTTP 400 for non-numeric `Content-Length` values.
- [ ] 2.3 [backend] Ensure early payload rejections receive a trace ID and the matching `X-Transaction-ID` response header without changing the incoming header contract.

## 3. Regression tests

- [ ] 3.1 [backend] Update the existing 413 response test and cover declared and streamed oversized payloads.
- [ ] 3.2 [backend] Test malformed `Content-Length`, trace propagation, and normal request-body replay.

## 4. Verification

- [ ] 4.1 [backend] Run `openspec validate fix-api-error-response-contract --strict`.
- [ ] 4.2 [backend] Run the affected middleware tests and the applicable lint and type checks; review the final diff for unrelated changes.
