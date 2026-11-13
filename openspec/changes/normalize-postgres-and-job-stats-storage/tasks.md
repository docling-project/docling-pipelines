# Tasks

## 1. Connection and Job Stats Layout

- [ ] 1.1 [backend] Add `_postgres_settings(config)` in `src/docpipe/storage/postgres/connection.py` implementing nested-over-root precedence with env and default fallback; use it in `get_postgres_connection_string`, `create_postgres_engine` and `get_postgres_pool_settings`. Verify with `pytest tests/unit/core/job_management/adapters/stores/postgres/` and `pytest tests/unit/storage/test_postgres_table_storage.py`.
- [ ] 1.2 [backend] Update `JsonJobStatsStore.__init__` in `src/docpipe/core/job_management/adapters/stores/json/json_job_stats_store.py` to append `job_stats` to an explicit `base_dir` unless it already ends with `job_stats`. Update the class docstring. Verify with `pytest tests/unit/core/job_management/adapters/stores/test_json_job_stats_store.py`.
- [ ] 1.3 [backend] Confirm `_resolve_filesystem_base_dir` in `src/docpipe/core/job_management/adapters/config/job_management_factory.py` passes `DOCPIPE_JOB_STATS_BASE_DIR` through the store constructor so the suffix rule applies, without a second path rule. Verify with `pytest tests/unit/core/job_management/adapters/config/test_job_management_factory.py`.

## 2. Backend Name Aliases

- [ ] 2.1 [backend] Accept the `"postgresql"` alias in `JobManagementFactory` (`src/docpipe/core/job_management/adapters/config/job_management_factory.py`) and `IncrementalMetadataFactory` (`src/docpipe/core/incremental_metadata/adapters/config/incremental_metadata_factory.py`). Register `"postgres"` as the store `STORE_BACKEND` alias in `postgres_incremental_store.py`. Verify with `pytest tests/unit/core/job_management/adapters/config/` and `pytest tests/unit/core/incremental_metadata/test_factory.py tests/unit/core/incremental_metadata/test_postgres_incremental_store.py`.
- [ ] 2.2 [backend] Accept the `"postgresql"` alias in `AssetRepositoryFactory` (`src/docpipe/core/assets/common/factories/asset_repository_factory.py`). Verify with `pytest tests/unit/core/assets/common/factories/test_asset_repository_factory.py`.
- [ ] 2.3 [backend] Accept the `"postgres"` alias in `src/docpipe/core/operators/quality/ededup_storage/factory.py` (currently only `{"filesystem", "postgresql"}`), and accept `"postgresql"` in `EntityStoreOperator` (`src/docpipe/core/operators/storage/entity_store_operator.py`, currently only `"postgres"`). Verify with `pytest tests/unit/operators/ededup/`.

## 3. Unit Tests

- [ ] 3.1 [backend] Add unit tests covering the flat-only, nested-only, mixed precedence and env fallback cases in `tests/unit/storage/` (connection settings). Verify with `pytest tests/unit/storage/`.
- [ ] 3.2 [backend] Add unit tests for the `"postgresql"` alias in the job management, incremental metadata, asset repository and ededup factories. Verify with `pytest tests/unit/core/job_management/adapters/config/ tests/unit/core/incremental_metadata/test_factory.py tests/unit/core/assets/common/factories/test_asset_repository_factory.py tests/unit/operators/ededup/`.
- [ ] 3.3 [backend] Add unit tests for `base_dir` resolution in `JsonJobStatsStore`: `./data` gives `./data/job_stats`, `./data/job_stats` stays unchanged, and the env override follows the same rule. Verify with `pytest tests/unit/core/job_management/adapters/stores/test_json_job_stats_store.py`.
- [ ] 3.4 [backend] Update existing `JsonJobStatsStore` test fixtures that expect `<base_dir>/<job_run_id>` directly. Verify with `pytest tests/unit/core/job_management/adapters/stores/`.

## 4. Integration Tests

- [ ] 4.1 [backend] Confirm `tests/integration/test_ededup_postgres.py` still passes with flat and alias configurations. Use existing tests only; do not add new integration tests. Verify with `pytest tests/integration/test_ededup_postgres.py`.

## 5. Configuration and Documentation

- [ ] 5.1 [backend] Update `docling-pipelines-config.yaml` (`job_management.storage.config.base_dir`) and `docling-pipelines-config.yaml.example` to show the flat PostgreSQL form and the standardized `"postgres"` name, and to document the `job_stats` suffix rule. Verify with `python -c "import yaml; yaml.safe_load(open('docling-pipelines-config.yaml'))"`.
- [ ] 5.2 [backend] Update `docs/reference/GLOBAL_CONFIG.md` with the flat/nested precedence rule and the canonical backend name. Verify the file's links with `grep -n "](" docs/reference/GLOBAL_CONFIG.md`.
- [ ] 5.3 [backend] Add a Breaking Changes entry to `docs/guides/ADVANCED_CONFIGURATION.md` containing the `job_stats` migration commands from proposal.md. Verify with `grep -n "job_stats" docs/guides/ADVANCED_CONFIGURATION.md`.

## 6. Validation

- [ ] 6.1 [backend] Run `openspec validate normalize-postgres-and-job-stats-storage --strict`.
- [ ] 6.2 [backend] Run the existing test suites listed in tasks 1 to 4 with the project virtual environment, following the project-python-tests skill.
