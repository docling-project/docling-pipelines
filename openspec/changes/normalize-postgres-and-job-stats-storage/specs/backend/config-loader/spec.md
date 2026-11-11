# Spec Delta

## Purpose

The config-loader capability resolves storage backend types and backend settings across services, supporting uniform PostgreSQL naming, flat/nested connection settings, and deterministic job stats storage layout.

## ADDED Requirements

### Requirement: Uniform PostgreSQL backend type naming
The system SHALL accept both `"postgres"` and `"postgresql"` as valid storage backend types for all storage-backed services and operators, normalizing them consistently so that configuring either `"postgres"` or `"postgresql"` selects the PostgreSQL adapter without resolution errors.

#### Scenario: Global storage configured with postgres
- **WHEN** `global_storage.type` is set to `"postgres"`
- **THEN** job management, incremental metadata, and asset repositories resolve and initialize the PostgreSQL backend successfully

#### Scenario: Service storage configured with postgresql
- **WHEN** `job_management.storage.type` or `incremental_metadata.storage.type` is set to `"postgresql"`
- **THEN** the service initializes the PostgreSQL backend successfully

### Requirement: Flat and nested PostgreSQL configuration
When PostgreSQL is selected as the storage backend, the loader and connection utilities SHALL accept connection settings directly at the root of `storage.config` or nested within `storage.config.postgres`. Flat connection properties SHALL NOT require a nested `postgres` dictionary key.

#### Scenario: Flat connection settings
- **WHEN** `storage.type` is `"postgres"` and connection keys (`host`, `port`, `database`, `user`, `password`) are provided directly under `storage.config`
- **THEN** the PostgreSQL connection string and engine are constructed using these connection properties

#### Scenario: Nested postgres connection settings
- **WHEN** connection keys are nested under `storage.config.postgres`
- **THEN** the PostgreSQL connection string and engine continue to parse the nested settings correctly

### Requirement: Deterministic job stats directory layout
The filesystem job stats store SHALL always place job statistics and node run directories inside a `job_stats` directory under the configured `base_dir`. When `base_dir` is explicitly configured, the store SHALL append `job_stats` if the path does not already end with `job_stats`.

#### Scenario: Configured base directory without job_stats suffix
- **WHEN** `job_management.storage.config.base_dir` is configured as `./data`
- **THEN** job statistics files are written under `./data/job_stats/<job_run_id>/job_stats.json`

#### Scenario: Configured base directory already ending in job_stats
- **WHEN** `job_management.storage.config.base_dir` is configured as `./data/job_stats`
- **THEN** job statistics files are written under `./data/job_stats/<job_run_id>/job_stats.json` without duplicate nesting
