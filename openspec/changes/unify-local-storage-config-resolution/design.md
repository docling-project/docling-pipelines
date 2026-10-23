# Design

## Context

See [proposal.md](proposal.md) for motivation and scope. The two configuration factories separately select backend types and shallow-merge dictionaries. Job management applies its backend environment override after YAML backend validation; incremental metadata does not read its documented backend override and catches configuration errors. PostgreSQL connection construction is shared but prefers YAML over environment values. Filesystem directory overrides already prefer environment variables.

This crosses both services and PostgreSQL configuration consumption, so a design is required. Existing live flow-engine and job-runs API specifications do not define this configuration contract.

## Goals / Non-Goals

Resolve each service once from a copied configuration block, apply environment overrides, then default and validate. Keep configuration handling in infrastructure/configuration adapters; domain ports and application services receive existing storage abstractions. Do not introduce domain imports of concrete adapters or route-specific resolution logic.

The exclusions in the proposal apply. In particular, do not change worker environment export, deployment construction, report/snapshot resolution, or add distributed fallback/mismatch handling. Shared helper changes will also be observed by processes using that helper, but distributed consistency is not asserted by this change.

## Decisions

### 1. Select a block instead of merging service and global storage

Normalize `job_management.store` and `incremental_metadata.storage` as service storage blocks. A non-empty block wins completely; otherwise select non-empty `global_storage`; otherwise select an empty block for service defaults. Empty service sections and null/empty storage blocks are absent. Non-mapping values are errors, not absence.

Preserve currently accepted legacy job-management storage keys by normalizing them to a service storage block before selection. The current `store` form takes priority over legacy storage keys. Framework settings alone do not make a service storage block present, and framework configuration must not overwrite storage values. Preserve the existing accepted locations of PostgreSQL settings within the chosen service configuration; do not combine them with unselected global settings.

Alternative: recursively merge global and service settings. Rejected because the agreed contract is complete service replacement. Copy selected data so resolving one service cannot mutate another service's inputs.

### 2. Apply environment fields before backend and required-value validation

Use an explicit mapping of supported environment names to effective settings. Keep `DOCPIPE_STORAGE_BACKEND` job-specific; implement `DOCPIPE_INCREMENTAL_STORAGE_BACKEND` independently. Apply the existing shared PostgreSQL connection variables and service filesystem directory variables. Implement `DOCPIPE_INCREMENTAL_POSTGRES_SCHEMA` for incremental PostgreSQL storage.

Preserve the existing convention that empty environment strings do not constitute an override. Validate non-empty override values; unsupported backend strings are errors. Do not create environment variables for every lock, pool, or DuckDB option. Keep `DOCPIPE_CONFIG_PATH` discovery intact.

Resolve schema before initialization and use that resolved schema consistently for incremental operations. Make only the schema-binding changes necessary for this contract; do not undertake unrelated ORM repairs. Job-statistics schema behavior via `DOCPIPE_POSTGRES_SCHEMA` remains unchanged.

Alternative: retain environment reads scattered across factories and adapters. Rejected for backend/connection/schema resolution because it allows different precedence at different consumption points. Filesystem consumers can retain their existing overrides provided the effective behavior is covered by shared contract tests.

### 3. Separate normalization from storage initialization

Use a small shared pure configuration-selection helper in infrastructure utilities, with service-specific backend/default/override definitions kept in their factories. Do not route other storage families through it in this change. Shared PostgreSQL connection construction must consume environment-first effective connection fields consistently, including callers that construct adapters directly.

Domain models, application service contracts, and REST DTOs are unchanged. Tests for selection must not create directories, connect to databases, or run migrations. Adapter tests verify actual configuration consumption separately.

### 4. Validate effective configuration and fail without redirecting storage

Parsing and structural validation precede field resolution; backend/required-value validation follows environment overrides and defaults. An environment backend can replace an unsupported YAML type, but cannot repair malformed YAML or an invalid document structure. Remove incremental's catch-all fallback for invalid configurations and job management's ignored invalid backend override. A missing default config file and empty YAML document continue to allow defaults.

Configuration errors identify the service and relevant key/source. Never include raw configuration dictionaries, passwords, or credential-bearing URLs in error messages. Preserve operational connection errors while ensuring they do not leak credentials.

Alternative: warn and use defaults on error. Rejected because silently moving metadata can trigger unexpected reprocessing or hide job history.

## Risks / Trade-offs

- Whole-block replacement breaks configurations relying on inherited global fields. Mitigation: document a before/after example and require complete selected service settings or explicit environment overrides.
- Environment-first PostgreSQL resolution changes existing deployments with conflicting YAML and environment values. Mitigation: conflict tests for every supported connection variable and explicit documentation of precedence.
- Schema overrides can initialize the right table while querying an unqualified model. Mitigation: verify initialization and real read/write behavior against the same resolved incremental schema.
- Shared PostgreSQL helpers have additional callers. Mitigation: check direct callers and run focused connection and adapter regression tests; do not expand changes into their configuration factories.
- Configuration is cached by existing singleton factories. Mitigation: resolve on factory construction, document process restart/reconstruction after configuration changes, and reset singleton state in tests. Runtime hot reload is out of scope.
- Distributed behavior remains unresolved. Mitigation: state the boundary explicitly; do not claim submitter/worker consistency from local precedence fixes.

## Migration Plan

Update configuration documentation with selection rules, supported overrides, unchanged per-service defaults, empty-block behavior, and errors. Users depending on global/service field merging must copy required fields into the service block or remove that block to inherit global storage. Remove conflicting environment values when YAML should remain effective. No stored-data or dependency migration is required. Rollback restores previous code and configuration behavior; preserve metadata directories/databases during rollback.
