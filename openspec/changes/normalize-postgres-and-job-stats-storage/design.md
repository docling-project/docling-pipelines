# Design

## Context

See proposal.md for motivation. This change does not touch config file loading or `global_storage` precedence; those are specified by `central-config-loader`. The two changes do not share a capability name, so archiving either one does not overwrite the other.

Current behavior:
1. `JobManagementFactory` and `IncrementalMetadataFactory` recognize `"postgresql"`. `AssetRepositoryFactory` recognizes `"postgres"`. `ededup_storage/factory.py` accepts only `{"filesystem", "postgresql"}`. `EntityStoreOperator` accepts only `"postgres"`.
2. `get_postgres_connection_string`, `create_postgres_engine`, and `get_postgres_pool_settings` read connection settings only from `config["postgres"]`.
3. `JsonJobStatsStore` uses an explicit `base_dir` verbatim. Its default path, from `get_data_path(sub_dir="/job_stats")`, already includes `job_stats`.

## Goals / Non-Goals

**Goals:**
- Accept `"postgres"` and `"postgresql"` in every storage factory and operator that handles PostgreSQL.
- Accept PostgreSQL connection settings either flat or nested, with one defined precedence rule.
- Make the job stats directory layout the same whether `base_dir` is explicit or defaulted.

**Non-Goals:**
- Changing the config file reader or `global_storage` fallback (owned by `central-config-loader`).
- Changing SQL table definitions or migrations.

## Decisions

### Decision 1: Canonical `"postgres"` with `"postgresql"` alias
- **Choice**: `"postgres"` is canonical. Each factory maps `"postgresql"` to its own registered key before lookup. The mapping lives in each factory's entry point, not in a shared helper, because the factories register different key sets.
- **Rationale**: Users with either spelling in existing configs keep working. No config migration is required for backend names.
- **Alternatives considered**: Renaming the registered keys to `"postgresql"` everywhere (rejected: breaks existing `"postgres"` configs in asset and table storage).

### Decision 2: Flat and nested PostgreSQL settings in `connection.py`
- **Choice**: Add one private helper in `connection.py`, `_postgres_settings(config)`, used by all three functions. It builds the effective settings as follows:
  1. If `config["postgres"]` is a mapping, its keys take precedence.
  2. Any connection key that the nested mapping does not define is taken from the root of `config`.
  3. Any key defined in neither place falls back to the existing environment variable, then to the existing default.
- **Rationale**: Nested config keeps working unchanged. A partially nested config, such as `password` nested and `host` at the root, behaves predictably. Keeping the logic in one helper prevents the three functions from drifting.
- **Mixed-config scenario**: `config: {host: db-a, postgres: {password: secret}}` gives host `db-a` and the nested password. `config: {host: db-a, postgres: {host: db-b}}` gives host `db-b`, because nested wins for the key it defines.
- **Alternatives considered**: Raising an error for mixed configs (rejected: adds a failure mode the current code does not have). Normalizing in each factory (rejected: drift).

### Decision 3: `job_stats` suffix on explicit `base_dir`
- **Choice**: In `JsonJobStatsStore.__init__`, when `base_dir` is given, set `resolved = Path(base_dir)` and append `job_stats` unless `resolved.name == "job_stats"`. The default branch is unchanged.
- **`DOCPIPE_JOB_STATS_BASE_DIR`**: This env var reaches the store through `_resolve_filesystem_base_dir` and the same constructor, so it gets the same suffix rule. It is not a special case. This is a breaking change for any deployment that sets the variable to a path not ending in `job_stats`; the proposal's migration note covers it.
- **Rationale**: One rule for every entry point, matching the default layout.
- **Alternatives considered**: Applying the suffix only in the config-file path (rejected: the env var would then produce a different layout from the config file for the same directory).

## Risks / Trade-offs

- **[Risk] Existing runs disappear from listings after upgrade** (BREAKING):
  - *Mitigation*: Migration commands in proposal.md, or point `base_dir` at `<base_dir>/job_stats`.
- **[Risk] Existing test fixtures expect `<base_dir>/<job_run_id>` directly**:
  - *Mitigation*: Update fixtures to expect the `job_stats` segment, or pass a path already ending in `job_stats`.
- **[Risk] Mixed flat/nested configs are hard to read**:
  - *Mitigation*: Documented precedence in `docs/reference/GLOBAL_CONFIG.md`.
