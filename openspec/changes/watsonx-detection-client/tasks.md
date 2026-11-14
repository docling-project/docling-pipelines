# Tasks

## 1. Detection client

- [ ] 1.1 [backend] Create `src/docpipe/integrations/watsonx/detection_client.py` with `WatsonxDetectionClient` (keyword-only constructor: `api_key`, `api_base`, `container_id`, `container_kind`, `timeout`; `detect(*, payload) -> list[dict]`). Move the endpoint URL, the API `version` constant, the `<container_kind>_id` payload field, the retry settings (3 attempts, multiplier 2.0, wait 1-10 s), the precondition `ValueError` messages, IAM token caching via `WatsonxPipelineOptionsProvider._get_iam_access_token`, and the token reset on 401/403 out of `WatsonXAdapter`; keep one `RestClient` and send the token as a per-call `Authorization` header (design D1, D3). Verify with `uv run mypy src/docpipe/integrations/watsonx/detection_client.py` <!-- pragma: allowlist secret -->
- [ ] 1.2 [backend] Add `tests/unit/integrations/watsonx/test_detection_client.py` with a mocked `RestClient` and IAM call covering: request URL ends with `/ml/v1/text/detection`; `version` query param; `project_id` / `space_id` payload field follows `container_kind`; `Authorization: Bearer` header; non-list `detections` returns `[]`; 401 and 403 reset the token so the next call fetches a new one; 500 and a connection error keep the token; the token is fetched once across several successful calls; missing `api_key`, `api_base`, and `container_id` / `container_kind` raise `ValueError` with the current messages; other `ExternalServiceError` is raised as `DocpipeException` with the original status code. Verify with `uv run pytest tests/unit/integrations/watsonx/test_detection_client.py -v`

## 2. Core adapter

- [ ] 2.1 [backend] In `src/docpipe/core/adapters/watsonx/watsonx_adapter.py`, add a lazy `detection_client` property (mirroring `embedding_client`, no network call in `__init__`) and make `detect()` and `detect_entities()` call it. Remove `_call_watsonx_detection_api`, `_get_access_token`, `_access_token`, `WATSONX_API_VERSION` and the imports only they used (`urljoin`, `RestClient`, `RestClientConfig`, `RestMethod`, `WatsonxPipelineOptionsProvider`, `ExternalServiceError`) (design D2). Verify with `uv run ruff check src/docpipe/core/adapters/watsonx` and `uv run mypy src/docpipe/core/adapters/watsonx/watsonx_adapter.py`
- [ ] 2.2 [backend] Update `tests/unit/core/adapters/watsonx/test_watsonx_adapter.py::TestWatsonXTextDetection` to patch the client module's `RestClient` and IAM call instead of the adapter module's, and replace the `adapter._access_token is None` assertion with an assertion that the next call fetches a new token. Update `TestWatsonXDetectionGuards` in `tests/unit/core/adapters/watsonx/test_watsonx_adapter_embeddings_validation.py`: the two `_get_access_token` tests move to the client tests, and the guard tests assert that `detect()` still returns `success: False` for a missing `api_base`. Add a test that constructing `WatsonXAdapter` makes no IAM or detection request. Verify with `uv run pytest tests/unit/core/adapters/watsonx -v`

## 3. Detection validation

- [ ] 3.1 [backend] In `src/docpipe/core/operators/quality/pii_and_hap/adapters/outbound/watsonx/adapter.py`, change `WatsonxPIIAndHAPAdapter.validate()` to return `self._adapter.validate_detection()` (design D4). Verify with `uv run mypy src/docpipe/core/operators/quality/pii_and_hap/adapters/outbound/watsonx/adapter.py`
- [ ] 3.2 [backend] In `tests/unit/operators/pii_and_hap/test_watsonx_adapter.py`, change `test_validate_delegates_to_inner_adapter` to expect `validate_detection` on the mocked inner adapter (and that `validate` is not called). Add a regression test using a real `WatsonXAdapter` with a patched `WatsonXClient`: `WatsonxPIIAndHAPAdapter.validate()` returns `context == "detection"`, and a config with no `api_key` fails with an error naming `api_key`. Verify with `uv run pytest tests/unit/operators/pii_and_hap/test_watsonx_adapter.py -v`

## 4. Verification

- [ ] 4.1 [backend] Run `uv run ruff check --fix .`, `uv run ruff format --check src tests`, `uv run mypy .`, and `uv run pytest tests/unit/core/adapters tests/unit/integrations tests/unit/operators/pii_and_hap -v`; confirm no new warnings or failures and that `grep -rn "_call_watsonx_detection_api\|WATSONX_API_VERSION" src tests` finds nothing outside the client module and its tests
- [ ] 4.2 [backend] Confirm OpenSpec validity with `openspec validate watsonx-detection-client --strict`

## Workflow follow-up

- Archive this change only after `add-huggingface-hap-provider` (PR #622) is archived, because the spec delta targets `backend/pii-and-hap-operator`, which that change creates.
- Run `pre-commit run --from-ref origin/main --to-ref HEAD` after committing with `git commit -s`, before pushing.
