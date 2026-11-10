# Design

## Context

Each storage-backed factory used to open and parse the config YAML itself, resolve `DOCPIPE_CONFIG_PATH`, and implement its own precedence and merge rules. Adding a service meant copying that block again, and the copies disagreed about environment overrides and about whether `global_storage.config` and `global_storage.postgres` were merged into service settings.

## Goals / Non-Goals

**Goals:**
- One place that locates, reads, caches and queries the config file.
- One precedence rule for storage selection, shared by every service.
- A per-service default type, so job management keeps `inmemory` while other services keep `filesystem`.

**Non-Goals:**
- Moving the remaining direct YAML readers onto the loader.
- Hot reload of the config file.

## DDD Layer Boundaries

- **Infrastructure utility**: `DocpipeConfigLoader` in `docpipe.utils.infrastructure.config_utils`. It has no dependency on any `core/` domain or application layer.
- **Adapters**: the factories under `core/job_management/adapters/config/` and `core/incremental_metadata/adapters/config/` call the loader and then build their stores. They remain the only place that maps a storage type string to a store class.
- **Domain and application layers**: unchanged. They never read the config file.

## Decisions

### 1. Process-wide singleton with explicit `reset()`
- **Decision**: `DocpipeConfigLoader` caches the parsed dict on first use, guarded by a lock, and exposes `reset()` for tests.
- **Rationale**: A single read removes repeated IO and guarantees all services see one consistent snapshot.
- **Trade-off**: Edits to the file or to `DOCPIPE_CONFIG_PATH` after the first read are ignored until restart. Accepted and documented.

### 2. Type resolution without merging
- **Decision**: `get_storage()` returns `(type, config)` from the first of: the service `storage` block (or legacy `store`), `global_storage`, a built-in default. Values are never copied between blocks. If the chosen block has no `type`, the type comes from `global_storage.type`, then the default.
- **Rationale**: Merging made the effective configuration depend on which keys happened to be omitted, and differed per factory.
- **Alternatives considered**: Keep the merge for job management only. Rejected because it preserves the inconsistency this change removes.

### 3. Per-service default type
- **Decision**: `get_storage(key, default_type=...)`. Job management passes `inmemory`. All others use `filesystem`.
- **Rationale**: Job stats historically persisted nothing when unconfigured. Changing that would silently start writing run history to disk.

### 4. Environment overrides for backend selection are removed
- **Decision**: `DOCPIPE_STORAGE_BACKEND` and `DOCPIPE_FRAMEWORK_TYPE` are not read by `JobManagementFactory`. `resolve_worker_env()` still writes them, and `DOCPIPE_CONFIG_PATH` is forwarded to workers.
- **Rationale**: One source of truth for backend choice. Workers select their backend from the same config file as the submitter.
- **Risk**: A worker that cannot read the config file falls back to `inmemory`. Mitigated by documenting that workers must receive the config file, and by forwarding `DOCPIPE_CONFIG_PATH`.

### 5. Missing or invalid file degrades to defaults
- **Decision**: An absent file returns `{}`. An invalid YAML file logs a warning and returns `{}`.
- **Rationale**: The CLI and library must run with no config file.
- **Risk**: A typo in the YAML silently selects defaults. Mitigated by the warning log.

## Risks / Trade-offs

- Existing deployments that relied on the removed overrides or the `global_storage` merge change behavior on upgrade. Migration steps are in `docs/guides/ADVANCED_CONFIGURATION.md`.
- `postgres` connection settings live in different places per service (sibling of `storage` for job management, inside `storage.config` for incremental metadata). This is existing behavior and is not unified here.
