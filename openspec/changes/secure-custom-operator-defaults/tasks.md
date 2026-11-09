# Tasks

## 1. Authentication

- [x] 1.1 [backend] Add `dependencies=[Depends(get_current_user)]` to `custom_operators_router` in `src/docpipe/api/routes/custom_operators.py`. Verify with `pytest tests/unit/api/routes/test_custom_operators_routes.py`.
- [x] 1.2 [backend] Add tests: no token, invalid token, JWT secret unset (503), read routes and `directory_tree` protected, valid token succeeds. Verify with `pytest tests/unit/api/routes/test_custom_operators_routes.py`.

## 2. Disabled by default

- [x] 2.1 [backend] Set `ENABLE_CUSTOM_OPERATORS_DEFAULT = False` and add `OperatorFactory.resolve_enable_custom_operators()`. Verify with `pytest tests/unit/core/orchestrator/test_operator_factory.py`.
- [x] 2.2 [backend] Change `enable_custom_operators` defaults from `True` to `None` in `OperatorFactoryProvider`, `OperatorFactory`, `AbstractOrchestrator`, `PythonOrchestrator`, `OrchestratorFactory`, `PythonOperatorExecutor` and `DocpipeFlowManager`, resolving through the single resolver. Verify with `pytest tests/unit/core/orchestrator tests/unit/test_docpipe_flow_manager.py`.
- [x] 2.3 [backend] Add tests for default off, env on, explicit argument over env, unrecognised env value, and orchestrator resolved boolean. Verify with `pytest tests/unit/core/orchestrator/test_operator_factory.py`.

## 3. Review follow-up

- [x] 3.1 [backend] Refuse script upload and script replacement with 409 (`CustomOperatorsDisabledException`) while custom operators are disabled, and skip the factory refresh. Verify with `pytest tests/unit/core/custom_operators/test_service.py`.
- [x] 3.2 [backend] Forward `DOCPIPE_ENABLE_CUSTOM_OPERATORS` in `JobManagementFactory.resolve_worker_env()` when set. Verify with `pytest tests/unit/core/job_management/adapters/config/test_job_management_factory.py`.
- [x] 3.3 [backend] Pin the no-token response to 401 in the spec and in `test_custom_operators_routes.py`.

## 4. Documentation

- [x] 4.1 [backend] Update `CONTRIBUTING.md`, `AGENTS.md`, `docs/guides/CUSTOM_OPERATORS_GUIDE.md` and `docs/guides/SECURITY_BEST_PRACTICES.md` with the new default, the token requirement and the migration steps.
- [x] 4.2 [backend] State plainly that an uploaded script runs in the API process, so every token holder can execute code once loading is enabled.

## 5. Validation

- [x] 5.1 [backend] Run `ruff format --check`, `ruff check` and `mypy` on touched files, then the full unit suite.
- [x] 5.2 [backend] Run `openspec validate secure-custom-operator-defaults --strict`.
- [ ] 5.3 [backend] After review and merge, run `openspec archive secure-custom-operator-defaults`.
