# Proposal

## Why

The `DocumentClassifierOperator` port/adapter architecture has been partially implemented — `ClassificationPort`, `StandardLLMClassificationAdapter`, `ClassificationAdapterFactory`, and the operator wiring are all in place. What remains is:

1. **The fast-path implementation**: domain types, deterministic scan detector, lightweight document sampler, and `HybridClassificationAdapter` that replaces the 3–10 second full Docling extraction with a ~50–800 ms first-N-pages strategy.
2. **Backend metadata restructure**: `get_metadata()` uses a flat attribute list today. The `ExtractOperator` already uses nested `properties` groups (e.g. `text_extraction.properties.*`, `entity_extraction.properties.*`) which enable the UI to render scoped accordions, per-provider schemas, and conditional field display. The classifier's metadata must adopt the same pattern — grouping classification config and output config as nested attribute groups — and the hybrid provider schema inside `provider_config.providers["hybrid"]` must expose the `vlm` sub-object alongside the text model fields.
3. **Frontend panel update**: The `DocumentClassifierPanelBody` currently reads all attributes flat from top-level controller keys. It must be updated to read from nested config groups, add a `"hybrid"` provider option in the dropdown, and conditionally render the VLM sub-object fields (`provider_config.vlm.*`) and top-level `max_pages` when the hybrid provider is selected.

## What Changes

- **New**: `ScanDecision` frozen dataclass added to `domain/models.py` — structured return type for the scan detector.
- **New**: `build_vision_classification_prompt()` function added to `domain/models.py` — dedicated vision prompt builder for the hybrid adapter's visual path, initially delegating to `build_classification_prompt`.
- **New**: `OperatorConstants.Classification.DEFAULT_MAX_PAGES = 5` added to `operator_constants.py`.
- **New**: `ScannedDocumentDetector` class in `domain/scanned_detector.py` — deterministic multilingual heuristic (Unicode categories, not ASCII regex) that classifies page text as scanned or digital using three signals: negligible text, watermark trap, and sufficient text density.
- **New**: `FastDocumentSampler` + `SampleResult` in `src/docpipe/utils/document/` — lightweight per-format extractor (pypdfium2, python-docx, python-pptx, openpyxl, PIL) that reads only the first N pages without invoking Docling.
- **New**: `HybridClassificationAdapter(ClassificationPort)` in `adapters/outbound/hybrid_adapter.py` — wires sampler → detector → text SLM (digital path) or vision VLM (visual path); registered in `ClassificationAdapterFactory` under `"hybrid"`.
- **Update**: `DocumentClassifierOperator.get_metadata()` — restructure flat attributes into nested groups (`classification_config.properties.*`, `output_config.properties.*`) following the `ExtractOperator` pattern; add `"hybrid"` as a valid provider; add a hybrid entry to `_get_classifier_provider_schemas()` with text model fields (`llm_inference`, `model_id`, `api_base`, `api_key`) at root level and a `vlm` sub-object with the same four fields for the vision model. `max_pages` remains a top-level operator attribute.
- **Update**: `DocumentClassifierPanelBody` (`DocumentClassifier.tsx`) — read config from nested attribute groups, add `"hybrid"` to provider dropdown, conditionally render the VLM sub-object section (`provider_config.vlm.*`) when `provider === "hybrid"`, and render a top-level `max_pages` number input.
- **Update**: `constants.ts` — add attribute key constants for `max_pages`, `max_content_length`, and the new nested config group keys (`classification_config`, `output_config`).
- **Update**: `docs/operators/quality/document_classifier_readme.md` — add hybrid provider config example with `provider_config.model_id` (text SLM), `provider_config.vlm.model_id` (vision VLM), and top-level `max_pages`.

## Capabilities

### New Capabilities

- `backend/document-classifier-hybrid-adapter`: Fast hybrid classification path for `DocumentClassifierOperator` — deterministic scan detection, per-format document sampling without Docling, and dual-model routing (text SLM for digital documents, vision VLM for scanned/image documents).
- `frontend/document-classifier-panel`: Properties panel for the `document_classifier` operator — provider selection, nested config groups, hybrid-specific fields (vision model, page limit), and document type multi-select.

### Modified Capabilities

*(none — no existing spec-level behavior changes)*

## Impact

- **Full-stack** (backend + frontend).
- Backend files added: `domain/models.py` (extended), `domain/scanned_detector.py`, `src/docpipe/utils/document/__init__.py`, `src/docpipe/utils/document/fast_document_sampler.py`, `adapters/outbound/hybrid_adapter.py`.
- Backend files modified: `src/docpipe/core/constants/operator_constants.py`, `domain/__init__.py`, `classification_adapter_factory.py`, `document_classifier.py`, `docs/operators/quality/document_classifier_readme.md`.
- Frontend files modified: `DocumentClassifier.tsx`, `constants.ts`.
- No new `pyproject.toml` dependencies: `pypdfium2`, `pillow`, `python-docx`, `python-pptx`, and `openpyxl` are already present as transitive dependencies.
- No changes to `LLMAdapterFactory`, `LLMInferencePort`, operator registry, storage, or any other operator.
- No new output columns: the hybrid adapter emits the same `document_type`, `_confidence`, `_reasoning` columns as the standard adapter.
