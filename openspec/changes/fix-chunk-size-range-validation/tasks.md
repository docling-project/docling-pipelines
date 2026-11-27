# Tasks

## 1. Shared helpers

- [x] 1.1 [frontend] Extract `isOutOfRange` and `buildRangeText` from `ProviderFieldsForm.tsx` to `shared/rangeValidation.ts`; verify provider form tests still pass.

## 2. Chunker validation

- [x] 2.1 [frontend] Add `CHUNK_SIZE_RANGE` to Chunker constants and `chunkSizeValidation.ts` helpers.
- [x] 2.2 [frontend] Show the inline range message on the chunk size input and use the constants for `min`/`max`.

## 3. Save gating

- [x] 3.1 [frontend] Add `saveValidation.ts` and use it in `CommonPropertiesWrapper` and `CommonPropertiesPanel`.

## 4. Tests

- [x] 4.1 [frontend] Add regression tests for below/above range, boundaries, inline message, error clearing, chunk type switching, and Save enable/disable.

## 5. Verification

- [x] 5.1 [frontend] Run vitest, `npm run lint`, TypeScript check, build, and `openspec validate fix-chunk-size-range-validation --strict`.

Validation: full frontend suite 179 files / 2627 tests passed; `tsc --noEmit` clean; `npm run lint` 0 errors, warning count unchanged vs upstream/main (305); strict OpenSpec validation passed.

## Workflow follow-up

- Archive after code review.
