# Design

## Context

`WatsonXAdapter` (`src/docpipe/core/adapters/watsonx/watsonx_adapter.py`) implements `LLMInferencePort`, `LLMEmbeddingPort` and `TextDetectionPort`. Inference goes through `WatsonXClient` and embeddings through a lazily created `WatsonxRestEmbeddingClient`. Detection is built inside the adapter:

- `_call_watsonx_detection_api` checks `api_base`, `container_kind` and `container_id`, builds the URL with `urljoin(api_base, "/ml/v1/text/detection")`, adds `version=2024-07-29` and `<container_kind>_id`, creates a new `RestClient` (3 attempts, multiplier 2.0, wait 1-10 s) with the bearer token, POSTs, returns the `detections` list (or `[]` if it is not a list), and on `ExternalServiceError` clears the cached token for 401/403 before raising `DocpipeException`.
- `_get_access_token` caches the IAM token in `self._access_token` and gets it from `WatsonxPipelineOptionsProvider._get_iam_access_token(api_key=...)`.
- `detect()` converts any exception into `{"success": False, "detections": [], "error": str(e)}`. `detect_entities()` re-raises as `ValueError`.
- `validate()` resolves by method resolution order to `LLMInferencePort.validate()`, which calls `validate_inference()`. `WatsonxPIIAndHAPAdapter.validate()` calls `self._adapter.validate()`.

The `add-huggingface-hap-provider` change (PR #622, archived first) already sets the precedent for the validation fix: `HuggingFaceHAPAdapter.validate()` calls `validate_detection()` explicitly.

## Goals / Non-Goals

**Goals:**
- The core adapter only maps `TextDetectionPort` calls to an integration client, as it does for inference and embeddings.
- Detection behavior, errors and result dicts stay identical.
- PII/HAP startup validation for WatsonX reports the `detection` context.

**Non-Goals:**
- Changing `TextDetectionPort`, the result dicts or detection defaults.
- Changing validation for the embeddings operator.
- Splitting `_validate_config` into per-context checks. The three hooks keep sharing it.

## Decisions

### D1. A `WatsonxDetectionClient` in `integrations/watsonx/`

New file `src/docpipe/integrations/watsonx/detection_client.py`. The name follows the rule that integration clients are named after the external capability, not the core port that uses them. `/ml/v1/text/detection` is a detection API.

Constructor (keyword-only): `api_key`, `api_base`, `container_id`, `container_kind`, `timeout`. One public method, `detect(*, payload) -> list[dict]`, which takes the `input` and `detectors` payload and returns the `detections` list. It owns the endpoint path, the API `version` constant (moved from `WatsonXAdapter.WATSONX_API_VERSION`), the container id payload field, retry settings, token caching and token reset.

Precondition checks (`api_base`, `container_kind`/`container_id`, `api_key`) and their `ValueError` messages move with the code. Existing tests that match those messages keep working because the adapter still surfaces them through `detect()` as a failed result.

Alternatives considered:
- Extend `WatsonXClient` with a detection method. Rejected: that client is the inference client (model name, generation) and would gain an unrelated endpoint.
- Leave it in the adapter. Rejected: it breaks the one-adapter-maps-to-clients convention that inference and embeddings already follow.

### D2. Lazy creation in the adapter

`WatsonXAdapter` stores the detection parameters and creates the client on first use, through a `detection_client` property that mirrors `embedding_client`. The constructor never calls the network or fetches a token. Parameter checks stay inside the client, so a half-configured adapter still constructs, and `detect()` reports the problem as `success: False`, as today.

The adapter drops `_access_token`, `_get_access_token`, `_call_watsonx_detection_api`, `WATSONX_API_VERSION` and the imports only they used (`urljoin`, `RestClient`, `RestClientConfig`, `RestMethod`, `WatsonxPipelineOptionsProvider`, `ExternalServiceError`).

### D3. Token handling stays in the client; one `RestClient` is reused

The client keeps the IAM token in an instance attribute and resets it on 401/403 only, exactly as now. Instead of building a `RestClient` with `auth_token=...` on every call, it builds one `RestClient` without a token and passes `headers={"Authorization": f"Bearer {token}"}` per call. `RestClient._build_headers` only adds its own header when `Authorization` is not already present, so the per-call header wins, and a refreshed token takes effect without rebuilding the client. This removes a `requests.Session` per call and keeps the token reset simple.

Token fetch is not locked, as today. Two threads that both find no token fetch one each and the last write wins; both tokens are valid, so the cost is one extra IAM request. A lock would add behavior the issue does not ask for.

### D4. Explicit `validate_detection()` call in the operator adapter

`WatsonxPIIAndHAPAdapter.validate()` calls `self._adapter.validate_detection()` instead of `self._adapter.validate()`. This is the same approach as `HuggingFaceHAPAdapter`, and it is needed because the core adapter's `validate()` resolves to the inference hook by method resolution order.

`WatsonXAdapter` itself does not override `validate()`. Which hook `validate()` picks depends on which port the caller means, so the caller states it. The embeddings operator's `_validate_adapter` has the same pattern and is left for a separate change (see proposal Non-goals).

Alternatives considered:
- Override `validate()` in `WatsonXAdapter` to call all three hooks. Rejected: it makes embedding-only use fail on detection checks.
- Reorder the base classes so `TextDetectionPort` is first. Rejected: it moves the problem to inference and embeddings.

### DDD and layer boundaries

- Port: `TextDetectionPort` (unchanged).
- Core adapter: `WatsonXAdapter` depends on `WatsonxDetectionClient` and `WatsonXClient` (integration layer), never the reverse.
- Operator adapter: `WatsonxPIIAndHAPAdapter` depends only on `LLMAdapterFactory` and the port (rule 11); it calls `validate_detection()` on the object the factory returns, which is already the case for its `detect()` calls.
- Integration client: no imports from `core/`.

## Risks / Trade-offs

- [Tests patch `RestClient` and read `_access_token` on the adapter module] -> Move those tests to patch the client module and read the client's token attribute. `test_watsonx_adapter.py::TestWatsonXTextDetection` and `test_watsonx_adapter_embeddings_validation.py::TestWatsonXDetectionGuards` are the known cases; a missed `mock.patch` string fails at test time, so run both modules after the change.
- [Reusing one `RestClient` changes retry state sharing] -> `RestClient` holds only configuration and a `requests.Session`; its retry wrapper is stateless per call, so reuse is safe. The client keeps 3 attempts and the same waits.
- [`validate()` result shape differs between the early-return branch and the delegated one] -> Out of scope; both already lack `context` in the early-return branch.
- [Spec delta targets a capability created by PR #622] -> Archive this change after `add-huggingface-hap-provider`. If the order flips, `openspec archive` cannot find the target spec.

## Migration Plan

No data or configuration migration. Rollback is a plain revert of the change.
