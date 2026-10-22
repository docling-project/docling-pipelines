# Proposal

## Why

An ingest source with a null provider exposes a NoneType error during validation. Omitted and blank providers incorrectly pass validation instead of telling the user to select a provider.

## What Changes

- Safely normalize null and blank provider selections in the ingest source operator.
- Return an actionable, node-specific missing-provider validation alert through REST, CLI, and Python library validation.
- Reject execution with the same message before storage or source access when validation is bypassed.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `backend/flow-execution-engine`: require an ingest provider during shared validation and ingestion.
- `backend/operators-api`: report missing ingest providers as structured validation errors in both supported formats.

## Impact

Backend-only change to IngestSourceOperator and shared validation messages. The existing validation route and Canvas post-save validation consume the corrected alerts. No dependencies, storage adapters, BFF routes, routing, or Redux state changes.

## Non-goals

Do not block saving incomplete draft flows, alter provider-specific connection validation, or change successful ingestion tables or metadata.
