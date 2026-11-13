## Purpose

Provide predictable local storage configuration for job statistics and incremental metadata by selecting one configuration source and applying explicit environment overrides consistently.

## ADDED Requirements

### Requirement: Select one storage configuration block per service
For job statistics and incremental metadata, the system SHALL select a non-empty service storage block, otherwise a non-empty `global_storage` block, otherwise service defaults. A selected service block SHALL replace the global block entirely. Missing values SHALL NOT be inherited from the unselected global block.

#### Scenario: Service configuration replaces global configuration
- **WHEN** global storage specifies PostgreSQL connection settings and a non-empty service storage block specifies filesystem storage
- **THEN** that service uses its filesystem configuration without inheriting global PostgreSQL settings

#### Scenario: Partial service configuration does not inherit global fields
- **WHEN** global storage specifies a PostgreSQL database and a non-empty service block specifies PostgreSQL with only a host
- **THEN** the database comes from its environment override or built-in default, not the global database

#### Scenario: Missing service type uses the service default
- **WHEN** a non-empty service storage block omits its type and no backend environment override is set
- **THEN** the service uses its default backend rather than a type from global storage

### Requirement: Empty service configuration is absent
The system SHALL treat an omitted or empty service section, an omitted storage block, and an empty or null storage block as absent for storage selection. Unrelated service settings SHALL NOT prevent global storage inheritance.

#### Scenario: Empty service section inherits global storage
- **WHEN** `incremental_metadata` is `{}` and `global_storage` is non-empty
- **THEN** incremental metadata uses global storage

#### Scenario: Framework-only job configuration inherits global storage
- **WHEN** job management configures only its execution framework and global storage is non-empty
- **THEN** job statistics uses global storage

#### Scenario: Empty storage block uses defaults without global storage
- **WHEN** a service storage block is empty or null and global storage is absent or empty
- **THEN** that service uses its built-in defaults, subject to environment overrides

### Requirement: Apply backend environment overrides before validation
The system SHALL apply `DOCPIPE_STORAGE_BACKEND` to job statistics and `DOCPIPE_INCREMENTAL_STORAGE_BACKEND` to incremental metadata with priority over the selected block and defaults. It SHALL validate the backend after applying the override. Each variable SHALL affect only its respective service.

#### Scenario: Incremental backend override replaces YAML backend
- **WHEN** selected incremental storage uses filesystem and `DOCPIPE_INCREMENTAL_STORAGE_BACKEND` is `postgresql` with valid connection settings
- **THEN** incremental metadata uses PostgreSQL

#### Scenario: Environment corrects an unsupported selected type
- **WHEN** the selected block has an unsupported type and its service backend environment override specifies a supported backend with valid settings
- **THEN** the effective backend passes validation and is used

#### Scenario: Job backend override is independent
- **WHEN** only `DOCPIPE_STORAGE_BACKEND` is set to `duckdb` and incremental storage is configured as filesystem
- **THEN** job statistics uses DuckDB and incremental metadata continues to use filesystem

### Requirement: PostgreSQL environment values override selected configuration
For both services using PostgreSQL, `DOCPIPE_POSTGRES_HOST`, `DOCPIPE_POSTGRES_PORT`, `DOCPIPE_POSTGRES_DB`, `DOCPIPE_POSTGRES_USER`, and `DOCPIPE_POSTGRES_PASSWORD` SHALL override the corresponding selected configuration fields. Fields without overrides SHALL retain their selected values or built-in defaults.

#### Scenario: Environment host overrides YAML host
- **WHEN** selected PostgreSQL configuration specifies host `yaml-host` and the environment specifies host `env-host`
- **THEN** the service connects using `env-host` while preserving other selected fields without overrides

#### Scenario: Environment supplies a missing password
- **WHEN** selected PostgreSQL configuration omits its password and `DOCPIPE_POSTGRES_PASSWORD` supplies a valid password
- **THEN** missing-password validation succeeds using the environment value

### Requirement: Filesystem directory environment overrides remain service specific
For filesystem storage, `DOCPIPE_JOB_STATS_BASE_DIR` SHALL override the job-statistics directory and `DOCPIPE_INCREMENTAL_BASE_DIR` SHALL override the incremental-metadata directory. Neither variable SHALL change the other service's directory or select a different backend.

#### Scenario: Independent filesystem directories
- **WHEN** both services use filesystem storage and both directory environment overrides are supplied
- **THEN** each service stores data in its own overridden directory rather than its selected YAML directory

### Requirement: Incremental PostgreSQL schema environment override is honored
For incremental PostgreSQL storage, `DOCPIPE_INCREMENTAL_POSTGRES_SCHEMA` SHALL override the selected PostgreSQL schema. Without an override, the selected schema or default `incremental_metadata` SHALL be used. Initialization and subsequent metadata operations SHALL target the same resolved schema.

#### Scenario: Environment schema overrides selected schema
- **WHEN** selected incremental PostgreSQL storage specifies schema `yaml_schema` and the environment specifies `env_schema`
- **THEN** initialization, reads, and writes use `env_schema`

### Requirement: Preserve service defaults when no configuration is provided
With no selected storage configuration or relevant environment overrides, job statistics SHALL use the `inmemory` backend and incremental metadata SHALL use `filesystem`. Existing adapter defaults for optional values and storage paths SHALL remain unchanged. A missing default configuration file or empty YAML document SHALL permit these defaults.

#### Scenario: No storage configuration or environment overrides
- **WHEN** neither service nor global storage is configured and no relevant environment overrides are supplied
- **THEN** job statistics uses in-memory storage and incremental metadata uses filesystem storage with its existing default data path

### Requirement: Invalid effective configuration fails explicitly
The system SHALL reject malformed configuration structure, malformed YAML, unsupported effective backends, and invalid or missing required effective values. It SHALL NOT ignore invalid backend overrides or silently select another backend. Errors SHALL identify the affected service or configuration source without exposing credentials.

#### Scenario: Invalid backend environment override
- **WHEN** a service has valid YAML storage configuration but its backend environment override is unsupported
- **THEN** configuration resolution fails rather than using the YAML backend

#### Scenario: Unsupported global backend for incremental metadata
- **WHEN** global storage selects DuckDB, incremental storage is absent, and no incremental backend override is supplied
- **THEN** incremental configuration fails rather than silently using filesystem storage

#### Scenario: Malformed configuration document
- **WHEN** the selected configuration file contains malformed YAML or a service storage value that is not a mapping or null
- **THEN** resolution reports a configuration error rather than selecting service defaults

#### Scenario: Environment supplied required values are validated first
- **WHEN** required PostgreSQL values remain missing after environment overrides and defaults are applied
- **THEN** configuration fails before storage use and the error does not expose passwords or credential-bearing connection strings
