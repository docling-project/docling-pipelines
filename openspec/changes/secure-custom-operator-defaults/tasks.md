# Tasks

## 1. Authentication

- [x] 1.1 [backend] Add `dependencies=[Depends(get_current_user)]` to `custom_operators_router` in `src/docpipe/api/routes/custom_operators.py`. Verify with `pytest tests/unit/api/routes/test_custom_operators_routes.py`.
- [x] 1.2 [backend] Add tests: no token, invalid token, JWT secret unset (503), read routes and `directory_tree` protected, valid token succeeds. Verify with `pytest tests/unit/api/routes/test_custom_operators_routes.py`.

## 2. Disabled by default

- [x] 2.1 [backend] Set `ENABLE_CUSTOM_OPERATORS_DEFAULT = False` and add `OperatorFactory.resolve_enable_custom_operators()`. Verify with `pytest tests/unit/core/orchestrator/test_operator_factory.py`.
- [x] 2.2 [backend] Change `enable_custom_operators` defaults from `True` to `None` in `OperatorFactoryProvider`, `OperatorFactory`, `AbstractOrchestrator`, `PythonOrchestrator`, `OrchestratorFactory`, `PythonOperatorExecutor` and `DocpipeFlowManager`, resolving through the single resolver. Verify with `pytest tests/unit/core/orchestrator tests/unit/test_docpipe_flow_manager.py`.
- [x] 2.3 [backend] Add tests for default off, env on, explicit argument over env, unrecognised env value, and orchestrator resolved boolean. Verify with `pytest tests/unit/core/orchestrator/test_operator_factory.py`.

## 3. Documentation

- [x] 3.1 [backend] Update `CONTRIBUTING.md`, `AGENTS.md`, `docs/guides/CUSTOM_OPERATORS_GUIDE.md` and `docs/guides/SECURITY_BEST_PRACTICES.md` with the new default, the token requirement and the migration steps.

## 4. Validation

- [x] 4.1 [backend] Run `ruff format --check`, `ruff check` and `mypy` on touched files, then the full unit suite.
- [x] 4.2 [backend] Run `openspec validate secure-custom-operator-defaults --strict`.
- [ ] 4.3 [backend] After review and merge, run `openspec archive secure-custom-operator-defaults`.
