# Tasks

## 1. Loader

- [x] 1.1 [backend] Add `DocpipeConfigLoader` with `get_config()`, `get()`, `get_storage()` and `reset()` in `src/docpipe/utils/infrastructure/config_utils.py`. Verify with `pytest tests/unit/utils/infrastructure/test_config_util.py`.
- [x] 1.2 [backend] Add the `default_type` argument to `get_storage()` and the fallback for a service block without a `type`. Verify with `pytest tests/unit/utils/infrastructure/test_config_util.py`.

## 2. Factories

- [x] 2.1 [backend] Replace YAML loading in `JobManagementFactory`, `IncrementalMetadataFactory`, `ContentStorageFactory` and `FlowDefinitionSnapshotStorageFactory` with `create_default_factory()` built on the loader. Job management passes `default_type="inmemory"`. Verify with `pytest tests/unit/core/job_management tests/unit/core/incremental_metadata`.
- [x] 2.2 [backend] Rename `RepositoryFactory` to `AssetRepositoryFactory` and rename `backend=` to `storage_type=` where applicable. Verify with `pytest tests/unit/core`.

## 3. Tests and documentation

- [x] 3.1 [backend] Update `test_work_pool_adapter.py` mocks to target `create_default_factory`. Verify with `pytest tests/unit/orchestration/adapters/test_work_pool_adapter.py`.
- [x] 3.2 [backend] Document the breaking changes and migration steps in `docs/guides/ADVANCED_CONFIGURATION.md` and update the other affected docs.

## 4. Validation

- [x] 4.1 [backend] Run `ruff format --check`, `ruff check` and `mypy` on touched files.
- [ ] 4.2 [backend] Run `openspec validate central-config-loader --strict`.
- [ ] 4.3 [backend] After review and merge, run `openspec archive central-config-loader`.
