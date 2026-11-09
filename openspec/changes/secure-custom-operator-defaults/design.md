# Design

## Context

Two facts on `main` make the custom operator catalog reachable and executable without credentials:

- `custom_operators_router` is included by `api_router` with no `dependencies=`, and none of its six handlers declares an auth dependency.
- `DocpipeConstants.ENABLE_CUSTOM_OPERATORS_DEFAULT` is `True`, and the API wires the custom operator directory into `DOCPIPE_CUSTOM_OPERATORS` at startup, so uploaded scripts are loaded on every catalog refresh.

Changing the constant alone does nothing. It is read only inside `OperatorFactory.__init__` when the argument is `None`, and every caller above it passes a hard-coded `True`.

## Goals / Non-Goals

**Goals:**
- Close both exposures with the smallest change that does not depend on the larger secret-management design.
- Make the default impossible to bypass by a caller that forgets to pass the flag.

**Non-Goals:**
- Isolation, sandboxing, roles, audit. See the proposal.

## Decisions

### 1. Router-level authentication dependency
- **Decision**: `APIRouter(..., dependencies=[Depends(get_current_user)])` on `custom_operators_router`.
- **Rationale**: One declaration covers all six routes, including the read routes and `directory_tree`, and covers routes added later. Reads disclose the script inventory and the on-disk layout, so they are protected too.
- **Behavior without `JWT_SECRET_KEY`**: `get_current_user` depends on `get_jwt_config`, which raises 503 when the secret is missing or invalid. The routes therefore refuse to serve in that state without a startup check. A missing `Authorization` header is rejected by the bearer scheme before any token is verified.
- **Alternatives considered**: Refuse to start the API when `JWT_SECRET_KEY` is unset. Rejected because the project supports running without authentication for every other route, and the per-route 503 already gives the required result for this router.

### 2. Single resolver for the enable flag
- **Decision**: add `OperatorFactory.resolve_enable_custom_operators(*, enable_custom_operators)`. Precedence: explicit argument, then `DOCPIPE_ENABLE_CUSTOM_OPERATORS`, then `ENABLE_CUSTOM_OPERATORS_DEFAULT`. Parameters that previously defaulted to `True` default to `None`.
- **Where it is called**: `OperatorFactoryProvider` (before the cache key is built, so `None` and the resolved value share a factory), `OperatorFactory.__init__`, and `AbstractOrchestrator.__init__` (so `orchestrator.enable_custom_operators` stays a real `bool` for the validator and metadata readers).
- **Rationale**: A default that each layer re-declares drifts. With one resolver, the constant and the environment variable are the only inputs when a caller passes nothing.
- **Alternatives considered**: Flip the constant and leave `True` defaults in the callers. Rejected because it has no effect.

### 3. Environment variable parsing unchanged
- **Decision**: reuse the existing rule, `true`, `1` or `yes` (case-insensitive) enables, anything else disables.
- **Rationale**: Existing deployments that already set the variable keep working.

## Risks / Trade-offs

- Deployments that rely on uploaded or package operators stop loading them after upgrade until `DOCPIPE_ENABLE_CUSTOM_OPERATORS=true` is set. Flows that reference such an operator fail validation with an unknown operator error, which names the problem. Documented under Breaking Changes.
- API clients and scripts that call the custom operator routes without a token start receiving 401/403/503. Documented.
- Any authenticated user can still upload code once the flag is on. This change narrows exposure and does not provide isolation.
