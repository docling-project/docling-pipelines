# Proposal

## Why

Review feedback on the Vault hardening proposal (#464) pointed out that two custom-operator exposures need no part of that design and should not wait for it:

- `custom_operators_router` has no authentication dependency, so every `/api/v1/custom_operators` route (create, update, delete, list, get, directory tree) can be called without a token.
- Custom operator loading is enabled by default. Uploaded scripts are imported by the operator loader on every catalog refresh, so an unauthenticated upload can lead to code running inside the API process.

Both are a few lines to close. Requiring authentication on the router and turning the default off removes the exposure now, and leaves the larger isolation and secret-management work to its own change.

## What Changes

- **BREAKING**: Every `/api/v1/custom_operators` route requires a valid bearer token. A request without one is rejected, and a deployment without `JWT_SECRET_KEY` gets 503 from these routes.
- **BREAKING**: Custom operator loading is disabled by default. It is enabled only when the caller passes `enable_custom_operators=true` or `DOCPIPE_ENABLE_CUSTOM_OPERATORS` is set to `true`, `1` or `yes`.
- The default is resolved in one place, `OperatorFactory.resolve_enable_custom_operators()`, instead of each layer hard-coding `True`. An explicit argument wins over the environment variable, which wins over the constant.
- `DocpipeConstants.ENABLE_CUSTOM_OPERATORS_DEFAULT` becomes `False`.
- Uploading or replacing an operator script is refused with 409 while custom operators are disabled, so the API does not report success for code that can never run.
- `DOCPIPE_ENABLE_CUSTOM_OPERATORS` is forwarded to job-run workers, so the API and the workers resolve the same setting.

## Non-goals

- Process isolation, sandboxing or secret hand-off for custom operators (tracked in the Vault hardening proposal).
- Role checks or an uploader allowlist. Any authenticated user can still manage operators.
- An audit store for create, update and delete.
- Refusing to start the API when `JWT_SECRET_KEY` is unset. Unauthenticated development setups remain supported for every other route.
- Changing how installed packages or entry points are discovered.

## Capabilities

### New Capabilities
- None

### Modified Capabilities
- `backend/custom-operators-api`: all routes require authentication.
- `backend/flow-execution-engine`: custom operators are disabled unless explicitly enabled.

## Impact

- **Affected Layer**: Backend-only.
- **Code**:
  - `src/docpipe/api/routes/custom_operators.py`
  - `src/docpipe/core/custom_operators/service.py`
  - `src/docpipe/core/job_management/adapters/config/job_management_factory.py`
  - `src/docpipe/exceptions/docpipe_exceptions.py`, `src/docpipe/exceptions/error_codes.py`
  - `src/docpipe/core/constants/constants.py`
  - `src/docpipe/core/orchestration/operator_factory.py`
  - `src/docpipe/core/orchestration/abstract_orchestrator.py`
  - `src/docpipe/core/orchestration/orchestrator_factory.py`
  - `src/docpipe/core/orchestration/python/python_orchestrator.py`
  - `src/docpipe/core/orchestration/python/python_operator_executor.py`
  - `src/docpipe/lib/docpipe_flow_manager.py`
- **Affected REST routes**: all `/api/v1/custom_operators` routes.
- **Migration**: deployments that use uploaded or `DOCPIPE_CUSTOM_OPERATORS` operators must set `DOCPIPE_ENABLE_CUSTOM_OPERATORS=true`, and API clients of the custom operator routes must send a bearer token.
- **Documentation**: `CONTRIBUTING.md`, `AGENTS.md`, `docs/guides/CUSTOM_OPERATORS_GUIDE.md`, `docs/guides/SECURITY_BEST_PRACTICES.md`.
- **Tests**: `tests/unit/api/routes/test_custom_operators_routes.py`, `tests/unit/core/orchestrator/test_operator_factory.py`, `tests/unit/test_docpipe_flow_manager.py`.
