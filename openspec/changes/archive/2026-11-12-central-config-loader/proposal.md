# Proposal

## Why

Five factory classes (`JobManagementFactory`, `IncrementalMetadataFactory`, `ContentStorageFactory`, `FlowDefinitionSnapshotStorageFactory`, `AssetRepositoryFactory`) each carried their own copy of the code that locates and parses `docling-pipelines-config.yaml`, resolves the config path, and applies the "service block, then `global_storage`, then default" storage precedence. Roughly 600 lines were duplicated, and the copies had drifted: some merged `global_storage.config` and `global_storage.postgres` into the service block, some applied environment overrides, and each exposed a different set of named constructors.

A single loader, `DocpipeConfigLoader`, removes the duplication and makes backend selection behave the same way for every service. The behavior is not fully identical to the old behavior, so the observable contract is specified here.

## What Changes

- **New capability**: `backend/config-loader` specifies how the config file is located, read, cached and queried, and how a service's storage type and config are resolved.
- **BREAKING**: `DOCPIPE_STORAGE_BACKEND` and `DOCPIPE_FRAMEWORK_TYPE` no longer override `job_management` settings when the submitter selects a backend. They are still written into worker environments by `JobManagementFactory.resolve_worker_env()`.
- **BREAKING**: `global_storage.config` and `global_storage.postgres` are no longer merged into job management, incremental metadata, job run report or flow definition snapshot settings. `global_storage` is used only when the service has no `storage` block.
- **BREAKING**: The legacy `job_management.storage_backend` and `job_management.storage_config` keys are ignored.
- **BREAKING**: `DOCPIPE_INCREMENTAL_BASE_DIR` is removed.
- **BREAKING**: The documented key `job_management.store` is now `job_management.storage`. `store` is still accepted when `storage` is absent.
- **BREAKING**: The config file is read once per process and cached.
- **BREAKING (Python API)**: `from_config_file()`, `from_default_sources()` and `from_environment()` are replaced by `create_default_factory()` on the four storage factories. Constructor keyword `backend=` becomes `storage_type=`. `list_backends()` becomes `list_storage_types()` on the report and snapshot factories. `RepositoryFactory` becomes `AssetRepositoryFactory`.
- Unchanged by design: with no configuration, job stats default to `inmemory`, and every other service defaults to `filesystem`.
- Bug fix included: a service `storage` block that sets `config` but no `type` takes its type from `global_storage.type`, then the service default, instead of failing with `Invalid storage backend 'None'`.

## Non-goals

- Migrating the remaining direct YAML readers (flow `repository_factory.py`, `event_streaming/factory.py`, Alembic `migrations/env.py`) onto the loader.
- Restoring the removed environment overrides or the `global_storage` merge.
- Changing ededup storage resolution, which is specified in `backend/ededup-operator` and does not use the loader.
- Changing any REST route or frontend behavior.

## Capabilities

### New Capabilities
- `backend/config-loader`: Central, cached reading of `docling-pipelines-config.yaml` and per-service storage type and config resolution.

### Modified Capabilities
- None

## Impact

- **Affected Layer**: Backend-only.
- **Affected Storage Adapters and Factories**:
  - `src/docpipe/utils/infrastructure/config_utils.py` (new `DocpipeConfigLoader`)
  - `src/docpipe/core/job_management/adapters/config/{job_management_factory,report_storage_factory,flow_definition_snapshot_storage_factory}.py`
  - `src/docpipe/core/incremental_metadata/adapters/config/incremental_metadata_factory.py`
  - `src/docpipe/core/assets/common/factories/asset_repository_factory.py` (renamed from `repository_factory.py`)
  - `src/docpipe/core/projects/factories/project_repository_factory.py`
  - `src/docpipe/integrations/secrets/vault_initializer.py`
- **Affected REST routes and operators**: None.
- **Documentation**: `docs/guides/ADVANCED_CONFIGURATION.md` (Breaking Changes section), `docs/reference/GLOBAL_CONFIG.md`, `docs/integrations/prefect/DISTRIBUTED_EXECUTION_GUIDE.md`, `TROUBLESHOOTING.md`, `ARCHITECTURE.md`, `AGENTS.md`, `docling-pipelines-config.yaml.example`.
- **Tests**: `tests/unit/utils/infrastructure/test_config_util.py`, `tests/unit/core/job_management/**`, `tests/unit/core/incremental_metadata/**`, `tests/unit/orchestration/adapters/test_work_pool_adapter.py`.
