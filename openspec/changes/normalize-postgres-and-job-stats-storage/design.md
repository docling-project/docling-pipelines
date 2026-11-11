# Design

## Context

See proposal.md for motivation and problem background.

Currently:
1. `JobManagementFactory` and `IncrementalMetadataFactory` check against `"postgresql"` while `AssetRepositoryFactory` checks against `"postgres"`.
2. `get_postgres_connection_string` expects connection settings under `config["postgres"]`.
3. `JsonJobStatsStore` uses `base_dir` verbatim without guaranteeing a `job_stats` subdirectory when `base_dir` is passed.

## Goals / Non-Goals

**Goals:**
- Provide seamless backend resolution whether `"postgres"` or `"postgresql"` is supplied.
- Centralize flat/nested PostgreSQL dictionary parsing in `src/docpipe/storage/postgres/connection.py`.
- Guarantee deterministic `<base_dir>/job_stats/<job_run_id>/` layout across default and configured filesystem paths.

**Non-Goals:**
- Modifying SQL migration files or changing table definitions.
- Changing API response formats.

## Decisions

### Decision 1: Canonical `"postgres"` and alias normalization
- **Choice**: Normalize `"postgresql"` and `"postgres"` to the target factory's registered store key at the factory entrypoint (`create_default_factory` / `__init__`).
- **Rationale**: Minimal surgical impact that ensures both names work in any configuration block without throwing `ValueError` or `DocpipeException`.
- **Alternatives considered**: Requiring migration to only one string and breaking existing configs (rejected: unnecessarily disruptive).

### Decision 2: Centralized flat/nested parsing in `connection.py`
- **Choice**: In `get_postgres_connection_string`, `create_postgres_engine`, and `get_postgres_pool_settings`, if `config.get("postgres")` is a dict, use that section; otherwise use `config` directly.
- **Rationale**: Any adapter calling `get_postgres_connection_string` immediately supports both flat (`config: {host: ...}`) and nested (`config: {postgres: {host: ...}}`) configs with zero duplicated logic.
- **Alternatives considered**: Normalizing in each factory separately (rejected: leads to drift).

### Decision 3: Deterministic `base_dir` path resolution in `JsonJobStatsStore`
- **Choice**: If `base_dir` is passed, resolve `Path(base_dir)`: if its name is `"job_stats"`, keep it as-is; otherwise append `"job_stats"`.
- **Rationale**: Ensures job runs are always organized under `job_stats/<job_run_id>/` regardless of whether `base_dir` points to `./data` or `./data/job_stats`.

## Risks / Trade-offs

- **[Risk] Existing test fixtures expecting direct `<base_dir>/<job_run_id>` without `job_stats`**:
  - *Mitigation*: Update any test fixtures passing a mock root to account for the normalized `job_stats` subdirectory or pass a path ending in `job_stats`.
