# Tasks

Each task is scoped to at most two hours. Activate `.venv` before Python verification commands. These are implementation tasks; artifact creation does not mark them complete.

## 1. Local configuration selection

- [ ] 1.1 [backend] Add pure storage-block normalization/selection shared by the two factories, including legacy job storage keys and empty/null blocks; verify table-driven tests cover service replacement, global fallback, absent defaults, non-mapping errors, and unchanged input dictionaries without initializing stores.
- [ ] 1.2 [backend] Integrate selection into job management while keeping framework settings separate; verify factory tests cover framework-only global inheritance and missing service type using the service default.
- [ ] 1.3 [backend] Integrate selection into incremental metadata and replace the catch-all invalid-configuration fallback with explicit errors; verify malformed YAML/structure fail and missing default files or empty documents still permit defaults.
- [ ] 1.4 [backend] Update local selection documentation in `docs/reference/GLOBAL_CONFIG.md` and the relevant configuration guide with complete-block examples and unchanged per-service defaults; verify examples match selection tests and relative links resolve.

## 2. Environment overrides and effective validation

- [ ] 2.1 [backend] Apply job and incremental backend overrides before backend validation, add the documented incremental backend variable, and reject invalid effective overrides; verify service independence and environment correction of an unsupported YAML backend.
- [ ] 2.2 [backend] Make shared PostgreSQL connection resolution prefer each supported environment field over selected configuration; verify host, port, database, user, and password conflicts and missing-password completion for both services and direct adapter callers without real connections.
- [ ] 2.3 [backend] Add incremental PostgreSQL schema environment resolution with consistent schema binding for initialization and operations; verify schema precedence in adapter tests and add an integration test exercising write/read/delete in an overridden schema.
- [ ] 2.4 [backend] Preserve filesystem directory override behavior and ensure effective configuration errors exclude credentials; verify independent directory overrides, backend preservation, invalid effective values, and redacted configuration errors.
- [ ] 2.5 [backend] Document supported environment names, environment-first precedence, restart/reconstruction behavior, and invalid-config errors; verify documented examples against the override tests and explicitly retain the distributed-execution exclusion.

## 3. Integration verification

- [ ] 3.1 [backend] Run focused factory, PostgreSQL connection, filesystem, and incremental adapter tests with isolated environment and singleton state; verify direct factory and default-source paths produce the specified effective settings and record results.
- [ ] 3.2 [backend] Run the overridden-schema PostgreSQL integration test against an isolated test database; verify initialized and queried schemas agree, test data is cleaned up, and credentials are not printed. If unavailable, report the missing external prerequisite explicitly.
- [ ] 3.3 [backend] Run `uv run ruff check --fix .`, `uv run mypy .`, and `openspec validate unify-local-storage-config-resolution --strict`; verify successful results or identify pre-existing failures separately, and review the diff for accidental distributed/report/snapshot/asset storage changes.

## Workflow follow-up

- Review the planning artifacts before implementation with `$openspec-apply-change`.
- Archive only after implementation, review, and required validation pass; do not modify canonical specs directly.
