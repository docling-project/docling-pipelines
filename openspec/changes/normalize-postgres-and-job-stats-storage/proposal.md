# Proposal

## Why

PostgreSQL storage backends were registered inconsistently across services (`"postgresql"` in Job Management and Incremental Metadata vs `"postgres"` in Asset Repositories and Table Storage), causing global configuration fallbacks to fail when users configured `global_storage: {type: postgres}` or `global_storage: {type: postgresql}`. Additionally, PostgreSQL configuration required a redundant nested `postgres:` block when the backend was already selected as PostgreSQL, and `JsonJobStatsStore` placed job run directories directly in `<base_dir>/` rather than namespacing them under `<base_dir>/job_stats/`.

## What Changes

- **PostgreSQL Backend Name Standardization**: Standardize on `"postgres"` as the primary backend name across all storage factories and backends (`job_management`, `incremental_metadata`, `assets_management`, `ededup`), while normalizing `"postgresql"` as a supported alias so neither name causes resolution failures.
- **Flat and Nested PostgreSQL Configuration**: Allow PostgreSQL connection settings (`host`, `port`, `database`, `user`, `password`, `schema`, `pool_size`, etc.) to be provided directly at the root of `storage.config` without requiring a redundant nested `postgres:` section. Nested `postgres:` blocks remain supported for backward compatibility.
- **Deterministic Job Stats Filesystem Path**: Ensure `JsonJobStatsStore` always appends `job_stats` to its resolved root directory when configured with an explicit `base_dir` (e.g. `<base_dir>/job_stats/<job_run_id>/job_stats.json`), matching the unconfigured default layout.

## Non-goals

- Removing support for nested `config.postgres` blocks (both flat and nested shapes will be supported).
- Changing database schemas or SQL table structures for existing PostgreSQL or JSON stores.
- Changing frontend UI components or REST API routes.

## Capabilities

### New Capabilities
- `backend/config-loader`: Standardized storage backend type resolution (including PostgreSQL alias normalization), flat and nested PostgreSQL connection configuration, and deterministic job stats base directory resolution.

### Modified Capabilities
- None

## Impact

- **Affected Layer**: Backend-only.
- **Affected Storage Adapters and Factories**:
  - `src/docpipe/storage/postgres/connection.py` (connection string builder and engine creation supporting flat and nested configs)
  - `src/docpipe/core/job_management/adapters/config/job_management_factory.py` (backend type normalization and flat config forwarding)
  - `src/docpipe/core/job_management/adapters/stores/json/json_job_stats_store.py` (deterministic `job_stats` directory appending)
  - `src/docpipe/core/incremental_metadata/adapters/config/incremental_metadata_factory.py` (backend type normalization)
  - `src/docpipe/core/incremental_metadata/adapters/stores/postgres/postgres_incremental_store.py` (store backend registration alias)
  - `src/docpipe/core/assets/common/factories/asset_repository_factory.py` (backend type normalization)
  - `src/docpipe/core/operators/quality/ededup_storage/factory.py` (backend type normalization)
- **Documentation**: `docling-pipelines-config.yaml`, `docling-pipelines-config.yaml.example`, `docs/reference/GLOBAL_CONFIG.md`, `docs/guides/ADVANCED_CONFIGURATION.md`.
- **Tests**: Unit and integration tests for config loading, job management factory, incremental metadata factory, and json job stats store.
