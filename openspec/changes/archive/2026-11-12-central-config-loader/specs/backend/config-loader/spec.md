# Spec Delta

## Purpose

The config-loader capability is the single reader of `docling-pipelines-config.yaml`. It locates, parses and caches the file and resolves, for each storage-backed service, which storage type and which backend settings apply. Job management, incremental metadata, job run reports and flow definition snapshots all select their backend through it.

## ADDED Requirements

### Requirement: Config file location and tolerant loading
The loader SHALL read the config file from the path in `DOCPIPE_CONFIG_PATH` when set, otherwise from `docling-pipelines-config.yaml` in the project root. When the file is absent, or is not valid YAML, the loader SHALL return an empty configuration and SHALL NOT raise, so that every service falls back to its own defaults. An invalid file SHALL be reported with a warning log.

#### Scenario: Path from environment
- **WHEN** `DOCPIPE_CONFIG_PATH` points to an existing YAML file
- **THEN** the loader returns the contents of that file

#### Scenario: File absent
- **WHEN** the resolved config path does not exist
- **THEN** the loader returns an empty configuration and each service uses its default backend

#### Scenario: File is invalid YAML
- **WHEN** the resolved config file cannot be parsed as YAML
- **THEN** the loader logs a warning and returns an empty configuration

### Requirement: Single cached read per process
The loader SHALL read the config file at most once per process and serve later lookups from the cached result. Changes to the file or to `DOCPIPE_CONFIG_PATH` after the first read SHALL NOT take effect until the cache is cleared with `reset()` or the process restarts.

#### Scenario: Repeated lookups
- **WHEN** several services request configuration during one process
- **THEN** the file is read once and every service sees the same contents

#### Scenario: File changes after first read
- **WHEN** the config file is edited after the first lookup and `reset()` has not been called
- **THEN** lookups continue to return the originally loaded contents

#### Scenario: Cache cleared
- **WHEN** `reset()` is called and a lookup follows
- **THEN** the file is read again from the current `DOCPIPE_CONFIG_PATH`

### Requirement: Storage selection precedence
For a named service, the loader SHALL resolve the storage type and storage config from, in order: the service's `storage` block, the legacy `store` block when `storage` is absent, the `global_storage` block, then a built-in default. The selected block's `config` SHALL be returned as the storage config. Values SHALL NOT be copied between blocks.

#### Scenario: Service block wins
- **WHEN** both `incremental_metadata.storage` and `global_storage` are configured
- **THEN** the type and config come from `incremental_metadata.storage`

#### Scenario: Global block used when service block is absent
- **WHEN** a service has no `storage` block and `global_storage` is configured
- **THEN** the type and config come from `global_storage`

#### Scenario: Legacy store key accepted
- **WHEN** a service has a `store` block and no `storage` block
- **THEN** the loader uses the `store` block

#### Scenario: No merging of global settings
- **WHEN** a service `storage` block sets only `type` and `global_storage` sets `config` or `postgres` values
- **THEN** the returned config contains none of the `global_storage` values

### Requirement: Storage type fallback for a block without a type
When the selected service block does not set a `type`, the loader SHALL use `global_storage.type` if present, otherwise the service's default type. The service block's own `config` SHALL be preserved. The loader SHALL NOT return an empty type.

#### Scenario: Service config without type, global type present
- **WHEN** `job_management.storage` sets only `config` and `global_storage.type` is `duckdb`
- **THEN** the resolved type is `duckdb` and the config is the service block's `config`

#### Scenario: Service config without type, no global type
- **WHEN** `job_management.storage` sets only `config` and `global_storage` is absent
- **THEN** the resolved type is the job management default and the config is the service block's `config`

### Requirement: Per-service default storage type
When neither the service nor `global_storage` configures a storage block, the loader SHALL return the service's default type with an empty config. The default SHALL be `filesystem` unless the caller supplies a different `default_type`. Job management SHALL supply `inmemory`, so that with no configuration it persists nothing.

#### Scenario: Job management with no configuration
- **WHEN** no config file exists and job management requests its storage
- **THEN** the resolved type is `inmemory`

#### Scenario: Other service with no configuration
- **WHEN** no config file exists and incremental metadata, job run reports or flow definition snapshots request storage
- **THEN** the resolved type is `filesystem`

#### Scenario: Configured type beats the default
- **WHEN** `global_storage.type` is `duckdb` and job management has no `storage` block
- **THEN** the resolved job management type is `duckdb`, not `inmemory`

### Requirement: Job management backend selected only from the config file
`JobManagementFactory` SHALL select its storage backend and framework type from `job_management.storage`, `job_management.framework`, `global_storage` and defaults only. `DOCPIPE_STORAGE_BACKEND` and `DOCPIPE_FRAMEWORK_TYPE` SHALL NOT override these values. The legacy keys `job_management.storage_backend` and `job_management.storage_config` SHALL be ignored. An unsupported storage type or framework type SHALL fail with an error naming the supported values.

#### Scenario: Environment variable does not override
- **WHEN** `DOCPIPE_STORAGE_BACKEND=postgresql` is set and the config file selects `filesystem`
- **THEN** job management uses `filesystem`

#### Scenario: Legacy storage_backend key ignored
- **WHEN** `job_management.storage_backend` is set and `job_management.storage` is absent
- **THEN** the legacy key has no effect on backend selection

#### Scenario: Unsupported storage type
- **WHEN** the resolved job management storage type is not a supported backend
- **THEN** factory creation raises an error listing the supported backends

### Requirement: Worker propagation of job management settings
`JobManagementFactory.resolve_worker_env()` SHALL return the resolved storage backend and framework type under `DOCPIPE_STORAGE_BACKEND` and `DOCPIPE_FRAMEWORK_TYPE`. The Prefect work pool adapter SHALL forward `DOCPIPE_CONFIG_PATH` to workers when the config file exists. Workers SHALL select their job management backend from that config file, not from the forwarded backend variables.

#### Scenario: Config path forwarded
- **WHEN** the work pool adapter builds a worker environment and the config file exists
- **THEN** the environment includes `DOCPIPE_CONFIG_PATH` set to the resolved path

#### Scenario: Worker cannot read the config file
- **WHEN** a worker has no readable config file
- **THEN** its job management backend is the job management default, `inmemory`

### Requirement: Job management storage settings stay flat
`JobManagementFactory.create_default_factory()` SHALL expose the resolved storage config keys (such as `base_dir`, `lock_timeout`) at the top level of the factory configuration, together with `job_management.postgres` when present and any framework config.

#### Scenario: Filesystem settings reach the store
- **WHEN** `job_management.storage.config` sets `base_dir`
- **THEN** the factory configuration contains `base_dir` at its top level

### Requirement: Removed incremental metadata directory override
The filesystem incremental metadata store SHALL take its base directory from `incremental_metadata.storage.config.base_dir` or its default only. `DOCPIPE_INCREMENTAL_BASE_DIR` SHALL have no effect.

#### Scenario: Removed variable has no effect
- **WHEN** `DOCPIPE_INCREMENTAL_BASE_DIR` is set and the config file sets `base_dir`
- **THEN** the store uses the config file value

### Requirement: Default factory construction for storage services
Job management, incremental metadata, job run report and flow definition snapshot factories SHALL each provide `create_default_factory()` as the way to build a factory from the config file. Each SHALL reject an unknown resolved storage type with an error that lists the available types, and SHALL NOT silently substitute another backend. The report and flow definition snapshot factories SHALL expose `list_storage_types()`.

#### Scenario: Unknown incremental metadata type
- **WHEN** the resolved incremental metadata storage type is not registered
- **THEN** `create_default_factory()` raises an error listing the available types

#### Scenario: Factory built from configuration
- **WHEN** `create_default_factory()` is called with a valid `job_run_report.storage` block
- **THEN** the factory is created with the configured storage type and config
