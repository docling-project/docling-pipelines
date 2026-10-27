# Design

## Context

See proposal.md for motivation. All supported validation entry points instantiate IngestSourceOperator before calling its validation method. Canvas Save calls the same REST validation endpoint after persistence. Metadata discovery and authoring must still tolerate constructing an incomplete operator.

## Goals / Non-Goals

Keep provider checks in the operator and reuse the existing node-aware alert pipeline. Do not add operator-specific checks to domain flow entities, application services, route handlers, or storage adapters.

## Decisions

- Normalize null to an empty string and trim provider strings in the constructor. Reject non-string non-null values with a clear type error instead of exposing a string-method exception.
- Add INGEST_PROVIDER_MISSING to shared validation messages and append a ValidationMessage during operator validation. This preserves node identifiers and existing error response schemas; merely catching the constructor error would miss absent and blank selections.
- Use keyword arguments when the operator executor delegates validation, matching the ingest validation signature and project method conventions.
- Guard transform before incremental metadata access with the same message so disabled validation cannot bypass the requirement.
- Keep save routes and frontend behavior unchanged. Post-save validation already consumes backend alerts.
- Exercise the real operator through REST validation, CLI, library, and execution validation in regression tests; do not contact storage or ingest sources.

## Risks / Trade-offs

Previously accepted incomplete ingest configurations will now fail validation as intended. Existing provider-specific validation and valid provider normalization receive regression coverage. Incomplete draft saves remain supported.

## Migration Plan

No data migration or dependency changes. Deploy the backend change; rollback restores the previous operator behavior.
