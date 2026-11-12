# Proposal

## Why

`WatsonXAdapter` builds the WatsonX text detection HTTP request itself (`_call_watsonx_detection_api`) and manages the IAM token itself (`_get_access_token`). Inference and embeddings already go through integration clients, and `docs/guides/UNIFIED_LLM_ARCHITECTURE_GUIDE.md` says a core adapter only maps port calls onto integration clients. Detection is the one exception, and it creates a new `RestClient` on every call.

The adapter also has a latent validation bug. It extends `LLMInferencePort`, `LLMEmbeddingPort` and `TextDetectionPort`, each of which defines a template `validate()`. Python's method resolution order picks `LLMInferencePort.validate()`, so `WatsonxPIIAndHAPAdapter.validate()` runs `validate_inference()` and its result says `context: "inference"`. The three hooks share one `_validate_config()` today, so only the `context` value is wrong, but PII/HAP startup validation would silently skip any check that is added to detection later. The `add-huggingface-hap-provider` change already avoids this for its provider by calling `validate_detection()` explicitly.

## What Changes

- Add `WatsonxDetectionClient` in `src/docpipe/integrations/watsonx/detection_client.py`. It owns the `/ml/v1/text/detection` URL, the `version` query parameter, the `<container_kind>_id` payload field, the retry settings, IAM token caching and the token reset on 401/403, and returns the `detections` list.
- `WatsonXAdapter` creates the client lazily, like `embedding_client`, so constructing the adapter makes no network call. `detect()` and `detect_entities()` only map `TextDetectionPort` calls onto it. `_call_watsonx_detection_api`, `_get_access_token` and the `_access_token` attribute are removed from the adapter.
- `WatsonxPIIAndHAPAdapter.validate()` calls `self._adapter.validate_detection()` explicitly, so its validation result reports `context: "detection"`.
- No change to detection behavior: same endpoint, `version` value, retry settings, token refresh on 401/403, errors and result dicts.
- Layer affected: backend-only. No REST route, operator parameter, storage adapter, frontend, BFF or Redux change.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `backend/pii-and-hap-operator`: adds one requirement. PII/HAP provider startup validation runs the provider's detection validation, so the `WatsonX` provider reports the `detection` context. This capability is created by the `add-huggingface-hap-provider` change (PR #622), which must be archived first. The requirement is written as `ADDED`, so it merges into that spec at archive.

## Non-goals

- Changing detection behavior, defaults, thresholds or the `TextDetectionPort` signature.
- The same `validate()` method-resolution-order pattern in `EmbeddingsOperator._validate_adapter`, which also resolves to `validate_inference()` for `WatsonXAdapter` and `LiteLLMAdapter`. Today that is only a wrong `context` value.
- Renaming `integrations/watsonx/rest_client.py` and `WatsonxRestEmbeddingClient`, tracked in [#623](https://github.com/docling-project/docling-pipelines/issues/623).
- Overriding `WatsonXAdapter.validate()` itself.

## Impact

- New: `src/docpipe/integrations/watsonx/detection_client.py`, `tests/unit/integrations/watsonx/test_detection_client.py`.
- Modified: `src/docpipe/core/adapters/watsonx/watsonx_adapter.py`, `src/docpipe/core/operators/quality/pii_and_hap/adapters/outbound/watsonx/adapter.py`.
- Modified tests: `tests/unit/core/adapters/watsonx/test_watsonx_adapter.py` (the detection tests patch `RestClient` and read `adapter._access_token` on the adapter module), `tests/unit/core/adapters/watsonx/test_watsonx_adapter_embeddings_validation.py` (`TestWatsonXDetectionGuards` calls `adapter._get_access_token()`), `tests/unit/operators/pii_and_hap/test_watsonx_adapter.py` (validation regression test).
- Dependencies: none. The client keeps using `WatsonxPipelineOptionsProvider._get_iam_access_token` and `RestClient` as today.
- Ordering: archive after `add-huggingface-hap-provider`.
