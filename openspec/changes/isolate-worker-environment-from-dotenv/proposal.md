# Proposal

## Why

An isolated custom-operator worker is documented to receive only an allowlisted set of environment variables (`docs/guides/SECRETS_GUIDE.md`, design D12 of `add-secret-management`). That guarantee does not hold when a `.env` file is discoverable. The parent builds the worker environment correctly, but the worker imports application modules, and `docpipe.utils.infrastructure.config` calls `load_dotenv()` at import time. `load_dotenv()` searches upward from that module, finds the repository-root `.env`, and puts every key in it (for example `LDAP_BIND_PASSWORD` and `OPENSEARCH_PASSWORD`) into the worker's `os.environ`, where untrusted operator code can read it. In one checkout the worker gained 39 unexpected variables, three of them credential-like.

The failure is reproducible on clean `origin/main`: `test_no_inherited_environment_beyond_the_allowlist` passes with no `.env` and fails with one. It is a security gap in an existing guarantee, and it leaves that test failing on any machine that has a `.env`.

## What Changes

- **Backend: the worker environment disables `.env` loading.** `build_worker_environment` sets `PYTHON_DOTENV_DISABLED=1`, the switch `python-dotenv` (pinned `==1.2.4`) already honours inside `load_dotenv()`. The policy lives in the worker-environment builder only. `config.py` and every application process are unchanged.
- **Backend: regression coverage.** A test starts a real worker with a discoverable `.env` holding a synthetic canary and asserts the canary is absent. A second test asserts the application still loads a `.env` and does not override existing variables.
- **Backend: existing tests updated.** `TestWorkerEnvironment.test_only_allowlisted_names_pass` (exact-set assertion) and `TestHostileOperator.test_no_inherited_environment_beyond_the_allowlist` permit the one explicit control variable. Both keep asserting that credential variables are dropped.
- **Docs.** `docs/guides/SECRETS_GUIDE.md` states that the worker does not load `.env` and that explicit same-UID file access remains a deployment precondition.
- No REST route, operator, storage adapter or flow-JSON change. No new configuration key.

## Capabilities

### New Capabilities
<!-- None. -->

### Modified Capabilities
- `backend/custom-operators-api`: adds a requirement that an isolated worker does not load a `.env` file. The detailed isolation requirements are still in the in-flight `add-secret-management` change, which this change does not edit or restate.

## Impact

- **Layer:** backend-only.
- **Code:** `src/docpipe/core/orchestration/operator_loader/isolation/worker_client.py` only.
- **Tests:** `tests/unit/core/orchestration/operator_loader/isolation/test_isolation_worker.py` (two existing assertions, one new regression test), plus a parent-side `.env` test under `tests/unit/utils/infrastructure/`.
- **Docs:** `docs/guides/SECRETS_GUIDE.md`.
- **Not affected:** REST routes, operators, storage adapters, `config.py`, `docker/` (the image copies only `src/docpipe/` and `.dockerignore` excludes `.env`, so containers are exposed only when a `.env` is mounted).
- **Relationship to other changes:** independent of `standardize-pydantic-validation-errors` (PR #627), which lists this failure as a baseline problem.

## Non-goals

- Not a sandbox. Operator code can still read any file its OS user can read, including a `.env`, by opening it explicitly or by calling `load_dotenv()` after clearing the switch. A distinct worker UID and restricted file permissions remain deployment preconditions, as the secrets guide already states.
- No change to how the API, CLI, library or Prefect workers load `.env`.
- No change to `ENVIRONMENT_ALLOWLIST` contents.
- No fix for the other baseline failures (`requires_prefect` marker, Doclang, audit-logger test ordering).
