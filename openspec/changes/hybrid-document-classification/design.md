# Design

## Context

See `proposal.md — Why` for motivation. The key structural context: the port/adapter scaffold is already in place. `ClassificationPort` (ABC), `StandardLLMClassificationAdapter`, `ClassificationAdapterFactory` (registry-based, self-registering adapters), and the `DocumentClassifierOperator` wiring (`self.adapter`, factory call in `__init__`, `binary_content` threading in `transform`) are all committed. What remains is purely additive: the domain types, the pure-Python scan detector, the per-format sampler, and the hybrid adapter itself.

The factory uses a `register()` classmethod pattern — not an if/elif chain. Adding the hybrid adapter requires only implementing `HybridClassificationAdapter` and calling `ClassificationAdapterFactory.register(HybridClassificationAdapter)` once at module level. The operator does not change structurally; it only needs `"hybrid"` added to `get_metadata()` `VALID_VALUES`.

## Goals / Non-Goals

**Goals:**
- Add the three missing domain components (`ScanDecision`, `build_vision_classification_prompt`, `DEFAULT_MAX_PAGES`) so Tasks 2, 4, and 6 have their dependencies.
- Implement `ScannedDocumentDetector` as a pure-Python, no-I/O domain class testable without any mocks.
- Implement `FastDocumentSampler` as a stateless utility in `src/docpipe/utils/document/` reusable by future operators.
- Implement `HybridClassificationAdapter` and register it — the fast classification path.
- Update the two remaining operator touch-points: `VALID_VALUES` in `get_metadata()` and the operator README.

**Non-Goals:**
- Changes to `LLMAdapterFactory`, `LLMInferencePort`, or any existing LLM adapter.
- Changes to any operator other than `DocumentClassifierOperator`.
- Adding `is_scanned` as an output column. The scan routing is an internal detail.
- Performance benchmarking; that is deferred post-implementation.
- New `pyproject.toml` dependencies — all parsers (`pypdfium2`, `pillow`, `python-docx`, `python-pptx`, `openpyxl`) are already present as transitive deps.

## Decisions

### D1: `ScanDecision`, `build_vision_classification_prompt` and `DEFAULT_MAX_PAGES` placement

**Decision:** `ScanDecision` and `build_vision_classification_prompt` go in the existing `domain/models.py`. `DEFAULT_MAX_PAGES` goes in `OperatorConstants.Classification` in `operator_constants.py`.

**Rationale:** `domain/models.py` already holds `ClassificationRequest`, `ClassificationResponse`, and `build_classification_prompt`. Co-locating `ScanDecision` and the vision prompt builder keeps all classification domain types in one file. `OperatorConstants.Classification` is the single source of truth for classification defaults (`DEFAULT_CONFIDENCE_THRESHOLD`, `DEFAULT_MAX_CONTENT_LENGTH`) — the new constant belongs in the same group.

**Alternative considered:** A separate `domain/scan_decision.py` — rejected because it would fragment a small domain model with no benefit.

---

### D2: `ScannedDocumentDetector` as a stateless class with `@classmethod evaluate`

**Decision:** `ScannedDocumentDetector` lives in `domain/scanned_detector.py` as a class with no instance state. Detection thresholds are class-level constants. `evaluate` is a `@classmethod`; `_is_content_char` is a `@staticmethod`.

**Rationale:** No I/O, no mutable state. The class boundary groups the thresholds and logic under a single namespace without requiring instantiation. `@classmethod` for `evaluate` lets subclasses override thresholds if needed; `@staticmethod` for the pure char-category helper follows project rules (Rule 15: pure helpers with no class state → `@staticmethod`).

**Alternative considered:** A module-level function — rejected because the threshold constants would float free; a class keeps them co-located with the logic that uses them.

---

### D3: `FastDocumentSampler` placement in `src/docpipe/utils/document/`

**Decision:** The sampler lives in a new `src/docpipe/utils/document/` sub-package, not inside the classification operator's subtree.

**Rationale:** The sampler has no classification-specific logic — it only reads document bytes and returns text/images. Placing it in `utils/` makes it reusable by future operators (e.g. a future extraction preview operator) without creating an import dependency into the classification subtree. The classification adapter imports from `utils/`; `utils/` never imports from `operators/`.

**Alternative considered:** Placing it under `classification/domain/` — rejected because it would create a circular dependency risk if another operator ever imports from the same utility, and because samplers are infrastructure, not domain logic.

---

### D4: Lazy PDF image rendering in `FastDocumentSampler`

**Decision:** `FastDocumentSampler.sample` returns `page_images=[]` for PDFs. A separate `render_pdf_pages` static method produces images only when called explicitly.

**Rationale:** ~85% of PDFs in typical document collections are digital. Rendering pages to images takes ~40–70 ms per page via `pypdfium2`. Making rendering lazy means digital PDFs never pay that cost. The `HybridClassificationAdapter` calls `render_pdf_pages` only after `ScannedDocumentDetector` returns `is_scanned=True`.

**Alternative considered:** Always rendering images for PDFs — rejected as ~3–4× slower for the majority case.

---

### D5: `HybridClassificationAdapter` config shape — `provider_config` with nested `vlm` sub-object

**Decision:** Both the text SLM and the vision VLM are constructed via `LLMAdapterFactory.create_inference_adapter`. Their configuration lives entirely inside `provider_config`:
- Text model: `provider_config.llm_inference` (provider), `provider_config.model_id`, `provider_config.api_base`, `provider_config.api_key`
- Vision model: `provider_config.vlm.llm_inference`, `provider_config.vlm.model_id`, `provider_config.vlm.api_base`, `provider_config.vlm.api_key`

`max_pages` is a **top-level** operator config key (sibling of `provider`, `confidence_threshold`, etc.), not inside `provider_config`.

**Rationale:** The `vlm` sub-object inside `provider_config` mirrors how the text model is configured, making both models symmetrical and self-contained within `provider_config`. This is consistent with how the actual flow JSON is written (confirmed example). `max_pages` stays top-level because it is a sampling tuning knob for the operator, not a connection detail for a specific LLM endpoint.

**Alternative considered:** Optional top-level `vlm_provider` / `vlm_provider_config` keys — rejected because the actual confirmed config shape uses the nested `provider_config.vlm` sub-object, which is cleaner and avoids proliferating top-level keys.

---

### D6: Vision multi-image message format

**Decision:** The visual path sends a single user message with a list of `{"type": "image_url", ...}` content items followed by a `{"type": "text", ...}` item — the OpenAI multi-image content format.

**Rationale:** This is the de-facto standard for vision models served via vLLM, OpenAI, LiteLLM, and Watsonx. `LiteLLMAdapter.chat` passes `messages` through without inspecting content types, so no adapter changes are required.

---

### D7: No `is_scanned` in `ClassificationResponse`

**Decision:** `ClassificationResponse` is not extended with an `is_scanned` field. The hybrid adapter always returns the same response shape as the standard adapter.

**Rationale:** The scan routing is an internal optimisation, not a classification result. Surfacing it as an output column would create a schema difference between providers, complicating downstream operators and forcing the operator to conditionally emit columns. The plan is explicit on this point.

## Risks / Trade-offs

- **Scan detector false positives** → A watermarked digital PDF with very sparse cover-page text might be misclassified as scanned, routing it to the vision VLM instead of the text SLM. Mitigation: the thresholds (`MIN_TOTAL_CHARS_THRESHOLD=150`, `MIN_WORDS_PER_PAGE_THRESHOLD=25`) are conservative and tunable as named constants. The VLM path still produces a correct classification in most cases; the penalty is latency, not correctness.

- **pypdfium2 thread safety** → `pypdfium2` document objects are not shareable across threads. Mitigation: the sampler creates a new `pdfium.PdfDocument` per call (stateless); each worker in the operator's `ThreadPoolExecutor` operates on its own PDF instance.

---

### D8: Nested `properties` groups in `get_metadata()` for the classifier

**Decision:** `DocumentClassifierOperator.get_metadata()` is restructured to use nested attribute groups (`classification_config` and `output_config`, each with a `properties` sub-dict) mirroring the `ExtractOperator` pattern.

`classification_config.properties`: `document_types`, `confidence_threshold`, `doc_column`
`output_config.properties`: `output_column`, `include_confidence`, `include_reasoning`

Top-level attributes kept flat: `provider`, `provider_config`, `max_pages`, `max_content_length`, `max_workers`.

The `provider_config` attribute's `providers["hybrid"]` schema exposes the `vlm` sub-object (with `llm_inference`, `model_id`, `api_base`, `api_key`) alongside the text model fields at the root level of the schema. `max_pages` is a top-level operator attribute, not a field inside the hybrid provider schema.

**Rationale:** `ExtractOperator` already defines this standard. Moving classification-tuning fields into a `classification_config` group and output-format controls into an `output_config` group lets the panel use scoped accordion sections driven by metadata rather than hardcoded component layout. `max_pages` and `max_content_length` are sampling/truncation controls that apply at the operator level regardless of provider, so they stay top-level.

**Alternative considered:** Keeping the flat layout — rejected because it diverges from the established `ExtractOperator` convention and forces the panel to hardcode grouping.

- **Large image payloads to vision model** → 5 pages at 150 DPI per page produces approximately 5 × 1–2 MB JPEG images. Mitigation: images are JPEG-compressed before base64 encoding; the `scale` parameter of `render_pdf_pages` defaults to 1.5 (not full resolution) and can be lowered for throughput-sensitive flows.

- **openpyxl and large spreadsheets** → Opening a large `.xlsx` to read only the first 50 rows still loads the full workbook into memory. Mitigation: `read_only=True` mode in `openpyxl` streams row-by-row. This mode is used in `FastDocumentSampler`.
