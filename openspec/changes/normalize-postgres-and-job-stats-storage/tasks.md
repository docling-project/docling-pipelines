# Tasks

## 1. Storage Adapters and Connection Normalization

- [ ] 1.1 [backend] Update `src/docpipe/storage/postgres/connection.py` to support flat connection configs alongside nested `postgres` dictionaries. Verify with pytest on postgres connection tests.
- [ ] 1.2 [backend] Normalize `"postgres"` and `"postgresql"` backend names in `JobManagementFactory` and `IncrementalMetadataFactory`. Verify with `pytest tests/unit/core/job_management/adapters/config/` and `pytest tests/unit/core/incremental_metadata/test_factory.py`.
- [ ] 1.3 [backend] Update `JsonJobStatsStore` in `src/docpipe/core/job_management/adapters/stores/json/json_job_stats_store.py` to append `job_stats` to explicit `base_dir` when missing. Verify with `pytest tests/unit/core/job_management/adapters/stores/test_json_job_stats_store.py`.

## 2. Validation & Documentation

- [ ] 2.1 [backend] Add unit tests covering flat PostgreSQL config, `"postgres"`/`"postgresql"` alias handling, and `job_stats` `base_dir` resolution. Verify with `pytest tests/unit/utils/infrastructure/test_config_util.py`.
- [ ] 2.2 [backend] Update `docling-pipelines-config.yaml.example` and documentation in `docs/reference/GLOBAL_CONFIG.md` to reflect flat postgres configuration and standardized backend names.
