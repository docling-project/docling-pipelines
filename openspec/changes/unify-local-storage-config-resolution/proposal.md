# Proposal

## Why

Job statistics and incremental metadata resolve local storage configuration differently: PostgreSQL YAML values override environment variables, incremental backend overrides are ignored, and invalid incremental configuration can silently select filesystem storage. Users need predictable configuration selection and environment overrides within the executing process.

## What Changes

- Select a non-empty service storage configuration, otherwise non-empty `global_storage`, otherwise service defaults.
- **BREAKING**: Service storage configuration replaces the global storage block rather than merging with it; omitted values come from environment overrides or service defaults, not global configuration.
- Apply supported environment overrides before validating the effective configuration for both services.
- Support the documented incremental backend and PostgreSQL schema environment variables.
- **BREAKING**: Reject invalid effective storage configuration instead of ignoring invalid environment overrides or silently falling back to filesystem storage.
- Document and test the local resolution contract and service-specific defaults.

## Capabilities

### New Capabilities

- `backend/local-storage-configuration`: Local configuration selection, environment overrides, defaults, and validation for job statistics and incremental metadata storage.

### Modified Capabilities

None. Existing flow-execution-engine and job-runs-api requirements do not define storage configuration precedence.

## Impact

Backend-only. Affects job-management and incremental-metadata configuration factories, filesystem configuration consumption, and PostgreSQL connection/schema configuration. CLI, API, and library callers using these factories observe the same contract; no REST route or operator table contract changes are proposed. Existing configuration tests and storage documentation require updates. No dependency changes are expected.

## Non-goals

- Docker image environment resolution, Prefect worker environment propagation, inherited fallback blocks, and submitter/worker destination mismatch checks.
- Report, flow-definition snapshot, asset, and deduplication storage resolution.
- Changing supported storage backends, default storage locations, or adding environment variables for every adapter option.
- Storage data migration, broad PostgreSQL schema/ORM repairs, or unrelated factory refactoring.
