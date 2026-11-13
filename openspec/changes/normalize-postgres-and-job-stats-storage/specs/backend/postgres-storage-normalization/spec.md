# Spec Delta

## Purpose

The postgres-storage-normalization capability defines how PostgreSQL storage backends are named, how their connection settings are shaped, and where filesystem job stats are laid out. It does not define config file loading or `global_storage` precedence, which belong to `backend/config-loader`.

## ADDED Requirements

### Requirement: Canonical PostgreSQL backend name with alias
Every storage factory and operator that supports PostgreSQL SHALL accept `"postgres"` as the canonical backend name and SHALL accept `"postgresql"` as an alias for it. Both names SHALL resolve to the same PostgreSQL adapter without error.

#### Scenario: Canonical name
- **WHEN** a storage block sets `type` to `"postgres"`
- **THEN** the PostgreSQL adapter for that service is created

#### Scenario: Alias name
- **WHEN** a storage block sets `type` to `"postgresql"`
- **THEN** the same PostgreSQL adapter is created as for `"postgres"`

#### Scenario: Ededup and entity store accept both names
- **WHEN** the ededup storage factory or `EntityStoreOperator` receives `"postgres"` or `"postgresql"`
- **THEN** it selects the PostgreSQL backend instead of rejecting the value

### Requirement: Flat PostgreSQL connection settings
When PostgreSQL is the selected backend, connection settings (`host`, `port`, `database`, `user`, `password`, `schema`, `pool_size`, `max_overflow`, `pool_timeout`) SHALL be accepted at the root of the storage `config` without a nested `postgres` key.

#### Scenario: Flat settings only
- **WHEN** `config` sets `host`, `user` and `password` at its root and has no `postgres` key
- **THEN** the connection string and engine use those values

### Requirement: Nested PostgreSQL connection settings remain supported
The storage `config` SHALL continue to accept connection settings under a nested `postgres` mapping.

#### Scenario: Nested settings only
- **WHEN** `config` sets connection settings only under `postgres`
- **THEN** the connection string and engine use the nested values as before

### Requirement: Mixed flat and nested precedence
When both a nested `postgres` mapping and root-level connection settings are present, a key defined in the nested mapping SHALL take precedence over the same key at the root. A key defined only at the root SHALL be used. A key defined in neither SHALL fall back to its environment variable and then its default.

#### Scenario: Nested key overrides root key
- **WHEN** `config` sets `host: db-a` at its root and `postgres.host: db-b`
- **THEN** the connection uses host `db-b`

#### Scenario: Root key fills an undefined nested key
- **WHEN** `config` sets `host: db-a` at its root and `postgres.password: secret`
- **THEN** the connection uses host `db-a` and password `secret`

#### Scenario: Environment fallback for undefined keys
- **WHEN** neither the root nor the nested mapping sets `port` and `DOCPIPE_POSTGRES_PORT` is set
- **THEN** the connection uses the environment value

### Requirement: Deterministic job stats directory layout
The filesystem job stats store SHALL place job statistics and node run directories under a `job_stats` directory. When an explicit `base_dir` is provided, the store SHALL append `job_stats` unless the path already ends with `job_stats`. This rule SHALL apply equally to `base_dir` from the config file and to `DOCPIPE_JOB_STATS_BASE_DIR`.

#### Scenario: Configured base directory without job_stats suffix
- **WHEN** `job_management.storage.config.base_dir` is `./data`
- **THEN** job statistics are written to `./data/job_stats/<job_run_id>/job_stats.json`

#### Scenario: Configured base directory already ending in job_stats
- **WHEN** `job_management.storage.config.base_dir` is `./data/job_stats`
- **THEN** job statistics are written to `./data/job_stats/<job_run_id>/job_stats.json` without duplicate nesting

#### Scenario: Environment override uses the same rule
- **WHEN** `DOCPIPE_JOB_STATS_BASE_DIR` is `/mnt/stats`
- **THEN** job statistics are written to `/mnt/stats/job_stats/<job_run_id>/job_stats.json`

#### Scenario: Existing runs under the old layout
- **WHEN** runs exist at `<base_dir>/<job_run_id>/` and `base_dir` does not end in `job_stats`
- **THEN** those runs are not listed by the store, and operators SHALL move them into `<base_dir>/job_stats/` or set `base_dir` to `<base_dir>/job_stats` as described in the proposal's Breaking Changes section
