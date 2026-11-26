# Design

## Context

See `proposal.md` for motivation. Current state, observed on `origin/main`:

- `worker_client.build_worker_environment` filters `os.environ` against `ENVIRONMENT_ALLOWLIST` and adds `PYTHONUNBUFFERED`. The worker is started with `subprocess.Popen(..., env=<that>)`, so the environment handed to the process is correct.
- The worker imports `abstract_operator` when it loads an operator. Importing any module under `docpipe.utils.infrastructure` runs the package `__init__`, which imports `.config`; `config.py` line 13 calls `load_dotenv()`. `import docpipe.utils.infrastructure.logging` alone triggers it, so import ordering cannot avoid the load.
- `load_dotenv()` with no argument searches upward from the calling module's file, not the working directory, so the worker's temporary `cwd` does not help.
- The repository pins `python-dotenv==1.2.4`. `load_dotenv()` returns `False` without reading any file when `PYTHON_DOTENV_DISABLED` is a truthy value (`1`, `true`, `t`, `yes`, `y`), read from the process environment at call time.
- Other import-time loaders in `src/docpipe` were checked (search for `load_dotenv`, `dotenv_values`, `find_dotenv`, module-level `os.environ` writes and module-level file reads). `config.py` is the only module that loads a file into `os.environ` at import. Other module-level environment reads (for example `DOCPIPE_REPORT_WORKERS` in `executor_pool.py`, `DOCPIPE_POSTGRES_SCHEMA` in the Postgres models) only read values already present. A few modules do write to `os.environ` at import, but only on application start-up paths that the isolated worker's import chain does not reach: `prefect_engine.py` calls `set_prefect_env_variables()` at module level (it is imported lazily from `python_orchestrator.py`, and `core/orchestration/__init__.py` and the isolation package `__init__` do not import it), and `api/main.py` calls `set_dpk_log_level_from_ds_log_level()` at module level (the worker never imports the API module). The remaining writes (`litellm` client, CLI) are inside functions that are not called on import. None of these read a file, so they are not another dotenv route. Third-party packages were not audited. Task 1.1 asserts the synthetic canary only, so it does not catch other variables a dependency might add; the existing `TestHostileOperator::test_no_inherited_environment_beyond_the_allowlist` provides the broader full-environment check.
- Docker: the image copies only `src/docpipe/`, and `.dockerignore` excludes `.env`, so the leak needs a checkout or a mounted `.env`. Compose and Kubernetes files define no `env_file`.

## Goals / Non-Goals

**Goals:**
- No `.env` file is loaded inside an isolated worker.
- Application behaviour, including `.env` loading and non-override semantics, is unchanged.
- The hostile-operator environment test passes with a `.env` present.

**Non-Goals:**
- Preventing explicit file reads by operator code (same-UID limit, documented).
- Moving `load_dotenv()` out of import time.

## Decisions

**D1. Set `PYTHON_DOTENV_DISABLED=1` in `build_worker_environment`.** It is added next to `PYTHONUNBUFFERED`, as a parent-set control variable, not as an allowlist entry (the allowlist names what is copied from the parent). The variable is set unconditionally so a value in the parent cannot re-enable loading.
- Why: the load happens during package import, before any worker code can run, and the parent controls the environment at spawn. The switch is a documented `python-dotenv` feature, so no second disabling mechanism is introduced, `config.py` and its import graph are untouched, and the policy sits in the one function that already owns the worker's environment.
- Alternatives considered:
  - *A custom marker variable plus a conditional in `config.py`.* Works, but adds a constant, a shared-module conditional and a second mechanism for something the library already provides. Rejected.
  - *Remove `load_dotenv()` from import time and call it at entry points.* Cleanest in principle but touches the API, CLI, library and Prefect start-up paths. Rejected as out of scope.
  - *Delete the loaded variables in `worker_main` after import.* Module-level operator code can run after import and the values would already be in the process. Rejected.
- Trade-offs: the variable is visible to operator code and can be unset, after which an explicit `load_dotenv()` works. That is the same-UID limit already declared. If `python-dotenv` is downgraded to a release without the switch, the guard becomes silently ineffective. The pin and the regression test in task 1.1 cover that, and the test fails loudly if the switch stops working.

**D2. Existing tests that assert the exact environment are updated, not loosened.** `test_only_allowlisted_names_pass` expects `{"PATH", "LANG", "PYTHONUNBUFFERED", "PYTHON_DOTENV_DISABLED"}` and still asserts each credential name is absent. `test_no_inherited_environment_beyond_the_allowlist` adds `PYTHON_DOTENV_DISABLED` to its tolerated set and keeps its canary assertions.

**D3. Layer boundaries.** Only `core/orchestration/operator_loader/isolation/worker_client.py` changes. No port, adapter, domain or shared-utility module is touched, and no import direction changes.

**D4. Spec placement.** The delta goes in the live `backend/secret-management` capability, where the archived `add-secret-management` change (#708) placed the isolation requirements. The existing "Isolation guarantee is limited to in-memory and inherited state" requirement is MODIFIED (not duplicated) so the worker environment is the allowlist plus the parent-set control variables; the `.env`, application-loading and documentation requirements are ADDED. No new capability is created.

**D5. Documentation.** One sentence plus the same-UID precondition in the isolation section of `docs/guides/SECRETS_GUIDE.md`, beside the allowlist sentence.

## Risks / Trade-offs

- **Operator re-enables loading or reads the file explicitly.** Possible and out of scope; a deployment precondition.
- **Library behaviour drift.** Covered by the pin and a regression test that starts a real worker.
- **Test environments with a `.env`** previously failed the acceptance test; they pass after this change, which is intended.
