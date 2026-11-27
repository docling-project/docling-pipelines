# Proposal

## Why

The Chunk Text (`chunker`) properties panel accepts a chunk size outside the supported range without any visible message and still lets the user save. Simple chunking supports 500-5000 characters and Hybrid chunking supports 100-2048 tokens, but the panel only passes `min`/`max` to the Carbon `NumberInput`, which renders an empty error. Switching from Simple to Hybrid can also leave a previously valid value (for example 3000) out of range with no feedback. The invalid configuration is only rejected later at run time.

## What Changes

- Show an inline range message (reusing the existing localized "Range allowed: {min}-{max}" string introduced for provider fields in #137) when the chunk size is outside the range for the selected chunk type.
- Disable the Save button while the chunk size is invalid, and re-enable it when a valid value is entered.
- Revalidate when the chunk type changes between Simple and Hybrid.
- Define the per-chunk-type ranges once in the Chunker constants and reuse them for the input bounds and validation.
- Extract the existing range helpers from `ProviderFieldsForm` into a shared module so both panels use the same logic.
- Add regression tests.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `frontend/properties-panel`: add chunk size range validation and save gating for the Chunker panel.

## Impact

Frontend-only change. Affected code: the Chunker custom panel, the shared range helpers (extracted from `ProviderFieldsForm`), and the two places that compute Save-button state (`CommonPropertiesWrapper`, `CommonPropertiesPanel`). Carbon `NumberInput` is reused. No routing, BFF, Redux, backend, or i18n message ID changes.

## Non-goals

- Fixing the backend Hybrid chunk size validation defect (tracked in #449).
- Changing validation or layout of any other operator panel.
- Validating chunk overlap or overlap percentage.
- Validating chunk size for Semantic chunking, where chunk size is not used.
