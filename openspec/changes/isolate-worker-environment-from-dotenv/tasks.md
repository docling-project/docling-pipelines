# Tasks

## 1. Regression tests first

- [x] 1.1 [backend] Add a test (a real worker subprocess, not a check of the dictionary returned by `build_worker_environment`) beside `tests/unit/core/orchestration/operator_loader/isolation/test_isolation_worker.py` that makes a synthetic `.env` containing a canary credential discoverable by `load_dotenv()` (use a temporary source root or monkeypatched discovery, never the real repository `.env`), starts a real worker, and asserts the canary name and value are absent from the worker's environment. Confirm it fails on current code. Verify with `pytest tests/unit/core/orchestration/operator_loader/isolation/test_isolation_worker.py`.
- [x] 1.2 [backend] Add tests that, in a process without `PYTHON_DOTENV_DISABLED`, a discoverable `.env` is loaded and does not override an existing variable, and that with `PYTHON_DOTENV_DISABLED=1` it is not loaded. Verify with `pytest tests/unit/utils/infrastructure/`.

## 2. Implementation

- [x] 2.1 [backend] Set `PYTHON_DOTENV_DISABLED=1` unconditionally in `build_worker_environment` in `src/docpipe/core/orchestration/operator_loader/isolation/worker_client.py`. Update `TestWorkerEnvironment.test_only_allowlisted_names_pass` to the exact set `{"PATH", "LANG", "PYTHONUNBUFFERED", "PYTHON_DOTENV_DISABLED"}` and add `PYTHON_DOTENV_DISABLED` to the tolerated names in `test_no_inherited_environment_beyond_the_allowlist`. Keep the credential-dropped assertions in both. Verify with `pytest tests/unit/core/orchestration/operator_loader/isolation/`.
- [x] 2.2 [backend] Reverse control: remove the variable from `build_worker_environment`, confirm the 1.1 test fails, restore from a saved copy, confirm with `cmp`. Verify with `pytest tests/unit/core/orchestration/operator_loader/isolation/test_isolation_worker.py`.

## 3. Documentation

- [x] 3.1 [backend] Update the isolation section of `docs/guides/SECRETS_GUIDE.md`: the worker does not load `.env`, and a file readable by the worker's OS user remains covered by the distinct-user and file-permission preconditions. Verify by reading the section for links and code fences.

## 4. Validation

- [x] 4.1 [backend] Run the acceptance test with a real `.env` present and with none: `pytest tests/unit/core/orchestration/operator_loader/isolation/test_isolation_worker.py::TestHostileOperator::test_no_inherited_environment_beyond_the_allowlist`.
- [x] 4.2 [backend] Run `ruff check`, `ruff format --check` and `mypy` on the changed files, and `pytest tests/unit/core/orchestration/ tests/unit/utils/infrastructure/ --ignore=tests/unit/utils/infrastructure/test_rate_limiter.py`. The ignored rate-limiter module is a baseline failure tracked separately; `test_audit.py` is not ignored because its failure is test-order dependence tracked in #682.
- [x] 4.3 [backend] Run `openspec validate isolate-worker-environment-from-dotenv --strict`, then `pre-commit run --from-ref origin/main --to-ref HEAD` after committing.
