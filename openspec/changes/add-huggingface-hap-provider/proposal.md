# Proposal

## Why

#77 made PII and HAP detection independently selectable and added `presidio` as a local, PII-only provider, but HAP still has no local option: the only HAP providers are `watsonx` (remote API) and `litellm` (a prompted generative LLM). A `presidio` pipeline therefore still depends on a remote service, or on a slow, non-deterministic LLM call, for HAP. Compact Hugging Face text classifiers such as `ibm-granite/granite-guardian-hap-38m` (Apache 2.0, runs on CPU) give good HAP results when applied sentence by sentence, and `torch`, `transformers` and `nltk` are already core dependencies. Tracked in issue #504.

## What Changes

- Add a HAP-only `huggingface` provider to the `pii_and_hap` operator. It is selectable as `hap_provider` and rejected as `pii_provider` with the existing capability-mismatch error.
- The provider splits the input text into sentence spans whose `start`/`end` offsets point into the original text, scores each span with a local Hugging Face sequence-classification model, and reports each span whose toxic score is at or above `hap_threshold` as a `has_HAP` detection. `hap_redaction` then masks exactly that span.
- With no `hap_provider_config`, the provider uses `ibm-granite/granite-guardian-hap-38m`. All model-specific settings live in `hap_provider_config` (`model_id`, `revision`, `toxic_labels`, `activation`, `max_length`, `batch_size`, `device`, `local_files_only`), so other classifiers (Detoxify's models, multilingual models) work through config alone, without code changes.
- Misconfiguration (model or tokenizer cannot be loaded, `toxic_labels` not in the model's labels, missing `toxic_labels` for a non-default model, invalid option values) fails when the operator starts, before any document is processed.
- The model is loaded lazily, once per process for each `(model_id, revision, device)`, and shared by all adapter instances and concurrent batches. Nothing touches the network at import time. With `local_files_only: true` (or `HF_HUB_OFFLINE=1`), the provider runs fully offline from locally cached weights. Document content is never logged.
- The `LLMAdapterFactory` text detection capability gains `huggingface` (it is already an embedding provider). `create_text_detection_adapter` accepts an empty `model_id` and `provider_config` for `huggingface`. `watsonx` behavior does not change.
- Docstrings: `HAPDetectionPort` stops naming Perspective API (it shuts down at the end of 2026) as an example provider. `TextDetectionPort` documents the `detectors` keyword argument and the `success: False` error contract that implementations follow.
- Docs: `docs/reference/OPERATORS.md`, `docs/operators/quality/pii_and_hap_readme.md` (including a fully local `presidio` + `huggingface` example), `docs/guides/UNIFIED_LLM_ARCHITECTURE_GUIDE.md` and `ARCHITECTURE.md`.
- No new dependencies. No breaking changes: existing provider names, defaults and config keys are unchanged.

## Non-goals

- Choosing a model per document language. `detect_hap()` takes no language argument, so multilingual coverage comes only from configuring a multilingual `model_id`.
- Remote inference (the Hugging Face Inference API, TGI or other hosted endpoints). The provider runs models in-process only.
- PII detection with Hugging Face models (for example token-classification NER models).
- Reusing DPK's `dpk_hap` transform or adding the `data-prep-toolkit-transforms[hap]` extra. It gives only a document-level score, loses offsets, downloads NLTK data at import, logs document contents, and pins `nltk==3.9.1`, which conflicts with our `nltk==3.10.4`.
- Integrating Detoxify, LLM Guard or Perspective API as libraries. They return scores without offsets, and Perspective is being shut down. Detoxify's models remain usable as plain `model_id` config.
- Fixing the chunk-offset handling in `PIIAndHAPAnnotator._perform_detections_for_single_document`, where chunk-relative offsets may be applied to the full document for documents split into more than one chunk. That affects every provider and is tracked separately (see design.md, Risks).
- Changing the `TextDetectionPort.detect()` signature or adding a typed result model. Both would touch the `watsonx` adapter and are a follow-up.
- Shipping or pre-downloading model weights, and any license review of non-default models (for example `textdetox/xlmr-large-toxicity-classifier-v2`, which is OpenRAIL++).

## Capabilities

### New Capabilities

- `backend/pii-and-hap-operator`: behavior of the `pii_and_hap` operator's detection providers. This change introduces the spec with the `huggingface` HAP provider's requirements: provider selection and capability rules, default and configurable model, sentence-span detections with original-text offsets, startup validation, offline and logging guarantees, and per-process model sharing. Other providers' behavior can be added to this capability later.

### Modified Capabilities

None. `backend/operators-api` already specifies that `GET /api/v1/operators/metadata` returns metadata for all registered operators. The new provider shows up in the `pii_and_hap` provider schemas through the existing adapter registry, so no requirement there changes.

## Impact

- **Layer**: backend only. No frontend, `/ui` routing, BFF proxy or Redux changes. The properties panel already renders provider options and `hap_provider_config` fields from operator metadata.
- **Operators**: `pii_and_hap` (`PIIAndHAPAnnotator`) gains a HAP provider option. Its output columns and metadata contract are unchanged.
- **REST routes**: no new routes. `GET /api/v1/operators/metadata` and `POST /api/v1/validation/validate_flow` reflect the new provider through existing code paths.
- **Code**:
  - New: `src/docpipe/integrations/huggingface/text_classification_client.py` (model loading, cache, batched scoring), `src/docpipe/core/adapters/huggingface/huggingface_text_detection_adapter.py` (`TextDetectionPort` implementation), `src/docpipe/core/operators/quality/pii_and_hap/adapters/outbound/huggingface/` (`adapter.py`, `config.py`, `__init__.py`).
  - Modified: `src/docpipe/core/adapters/llm_adapter_factory.py`, `src/docpipe/core/adapters/huggingface/__init__.py`, `src/docpipe/core/operators/quality/pii_and_hap/adapters/outbound/__init__.py`, `src/docpipe/core/ports/text_detection_port.py` (docstring), `src/docpipe/core/operators/quality/pii_and_hap/ports/outbound/hap_detection_port.py` (docstring).
- **Storage adapters**: none.
- **Dependencies**: none added. Uses the existing `torch`, `transformers` and `nltk` core dependencies. `pyproject.toml` and `uv.lock` are unchanged.
- **Runtime**: the first use downloads the default model (about 38M parameters) from the Hugging Face Hub unless weights are already cached locally. The loaded model stays in process memory for the process lifetime.
