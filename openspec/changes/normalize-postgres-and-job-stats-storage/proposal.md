# Proposal

## Why

PostgreSQL storage backends are registered inconsistently across services. Job Management and Incremental Metadata register `"postgresql"`, while Asset Repositories, Table Storage and the ededup store use `"postgres"`. A configuration that uses the other spelling fails to resolve.

PostgreSQL connection settings must also be nested under a redundant `postgres:` key, even when the backend is already selected as PostgreSQL. `JsonJobStatsStore` writes run directories directly under an explicit `base_dir`, while its unconfigured default is `<data>/job_stats/`. The two layouts disagree.

This change is independent of the `central-config-loader` change, which owns the config file reader, the `global_storage` precedence rules and the `backend/config-loader` capability. This change does not modify those rules. It only normalizes backend names, connection-setting shape, and the job stats directory layout.

## What Changes

- **Backend name normalization**: `"postgres"` is the canonical name. `"postgresql"` is accepted as an alias in every storage factory that currently recognizes only one of the two names: `JobManagementFactory`, `IncrementalMetadataFactory`, `AssetRepositoryFactory`, `ededup_storage/factory.py`, and the `EntityStoreOperator` data backend.
- **Flat and nested PostgreSQL connection settings**: `get_postgres_connection_string`, `create_postgres_engine`, and `get_postgres_pool_settings` in `src/docpipe/storage/postgres/connection.py` accept connection keys at the root of the config. A nested `postgres` mapping remains supported. When both forms are present, the nested mapping wins for every key it defines, and root keys fill the rest. Environment variables are used only for keys absent from both forms.
- **Job stats directory layout**: `JsonJobStatsStore` appends `job_stats` to an explicit `base_dir` unless the path already ends in `job_stats`. Run directories are then always `<base_dir>/job_stats/<job_run_id>/`.

## Breaking Changes

- **BREAKING (on-disk layout)**: With `job_management.storage.config.base_dir` set to a path that does not end in `job_stats` (for example `./data/job_stats_store_data` in the shipped `docling-pipelines-config.yaml`), existing run directories at `<base_dir>/<job_run_id>/` are no longer listed or read. Operators upgrading must move them:

  ```bash
  mkdir -p <base_dir>/job_stats
  for d in <base_dir>/*/; do
    name=$(basename "$d")
    [ "$name" = "job_stats" ] || mv "$d" <base_dir>/job_stats/
  done
  ```

  Alternatively, set `base_dir` to `<base_dir>/job_stats` in the config file, which keeps existing paths readable without moving files.
- **Environment override `DOCPIPE_JOB_STATS_BASE_DIR`**: This variable is also a `base_dir` and is subject to the same rule. The `job_stats` suffix is appended to it in the same way. Its value is not used verbatim. The migration note above applies to it as well.

## Non-goals

- Changing the `global_storage` merge or fallback rules, or the `backend/config-loader` capability. Those belong to `central-config-loader`.
- Removing support for the nested `postgres:` block.
- Changing database schemas, SQL migrations, or table definitions.
- Changing ededup, entity-store, or asset-repository behavior beyond accepting the backend alias.
- Changing frontend UI components or REST API routes.

## Capabilities

### New Capabilities
- `backend/postgres-storage-normalization`: Canonical PostgreSQL backend naming with alias support, flat and nested PostgreSQL connection settings, and deterministic job stats directory layout.

### Modified Capabilities
- None

## Impact

- **Affected Layer**: Backend-only.
- **Shared connection code**:
  - `src/docpipe/storage/postgres/connection.py` (flat and nested settings)
- **Factories and backend name normalization**:
  - `src/docpipe/core/job_management/adapters/config/job_management_factory.py` (`POSTGRESQL` alias, flat config forwarding)
  - `src/docpipe/core/incremental_metadata/adapters/config/incremental_metadata_factory.py` (`"postgresql"` alias)
  - `src/docpipe/core/incremental_metadata/adapters/stores/postgres/postgres_incremental_store.py` (`STORE_BACKEND` alias)
  - `src/docpipe/core/assets/common/factories/asset_repository_factory.py` (`"postgresql"` alias)
  - `src/docpipe/core/operators/quality/ededup_storage/factory.py` (`"postgres"` alias, currently accepts only `"postgresql"`)
  - `src/docpipe/core/operators/storage/entity_store_operator.py` (`"postgresql"` alias, currently accepts only `"postgres"`)
- **Job stats layout**:
  - `src/docpipe/core/job_management/adapters/stores/json/json_job_stats_store.py`
  - `src/docpipe/core/job_management/adapters/config/job_management_factory.py` (`_resolve_filesystem_base_dir`, used for worker propagation)
- **Configuration and documentation**:
  - `docling-pipelines-config.yaml`, `docling-pipelines-config.yaml.example`
  - `docs/reference/GLOBAL_CONFIG.md`, `docs/guides/ADVANCED_CONFIGURATION.md` (Breaking Changes section with the migration note)
- **Tests**:
  - Unit: `tests/unit/storage/` (connection), `tests/unit/core/job_management/adapters/config/`, `tests/unit/core/job_management/adapters/stores/test_json_job_stats_store.py`, `tests/unit/core/incremental_metadata/test_factory.py`, `tests/unit/core/assets/common/factories/test_asset_repository_factory.py`, `tests/unit/operators/ededup/`
  - Integration: `tests/integration/test_ededup_postgres.py` (run only with the existing suite; no new tests added)
