# Spec Delta

## Purpose

Provides a fast hybrid classification path for `DocumentClassifierOperator` that samples only the first N pages of a document using lightweight parsers, deterministically decides whether the document is scanned or digital, and routes to a text SLM or a vision VLM accordingly — without invoking the full Docling pipeline.

## ADDED Requirements

### Requirement: Scan decision model
The system SHALL represent the outcome of scanned-vs-digital detection as a structured value carrying `is_scanned`, `total_valid_chars`, `avg_words_per_page`, and `reason`.

#### Scenario: Scan decision captures all fields
- **WHEN** the scanned detector evaluates page texts
- **THEN** the returned decision includes `is_scanned` (bool), `total_valid_chars` (int), `avg_words_per_page` (int), and `reason` (str)

---

### Requirement: Vision prompt builder
The system SHALL provide a dedicated prompt builder for the visual classification path that is callable independently of the text prompt builder.

#### Scenario: Vision prompt produces valid output
- **WHEN** `build_vision_classification_prompt` is called with a `ClassificationRequest`
- **THEN** it returns a non-empty string suitable for use as the text portion of a multi-image LLM message

---

### Requirement: Configurable page limit constant
The system SHALL define a default maximum page sample count as a named constant accessible at `OperatorConstants.Classification.DEFAULT_MAX_PAGES`, overridable per flow via the top-level `max_pages` operator config key (sibling of `provider`, `confidence_threshold`, etc. — not nested inside `provider_config`).

#### Scenario: Default page limit is used when max_pages is absent
- **WHEN** a flow config omits `max_pages`
- **THEN** the hybrid adapter samples at most `DEFAULT_MAX_PAGES` pages (default value: 5)

#### Scenario: Flow config overrides page limit
- **WHEN** a flow config sets `"max_pages": 3` at the top level of the operator config
- **THEN** the hybrid adapter samples at most 3 pages

---

### Requirement: Deterministic scanned-vs-digital detection
The system SHALL determine whether a document is scanned or digital using a three-signal deterministic algorithm operating on page text: negligible character count, watermark/stamp detection, and sufficient text density. The decision SHALL be made without any LLM call.

#### Scenario: Document with negligible text is scanned
- **WHEN** total valid Unicode letters/numbers across all sampled pages is fewer than 50
- **THEN** the decision is `is_scanned=True` with `reason="negligible_text"`

#### Scenario: Document with only watermark text is scanned
- **WHEN** the total unique words across all sampled pages is 6 or fewer AND total valid chars is below 150
- **THEN** the decision is `is_scanned=True` with `reason="watermark_or_stamp_only"`

#### Scenario: Document with sufficient text density is digital
- **WHEN** average words per page is 25 or more OR total valid chars is 150 or more
- **THEN** the decision is `is_scanned=False` with `reason="verified_digital_text"`

#### Scenario: Borderline document falls back to scanned
- **WHEN** none of the above signals produce a definitive result
- **THEN** the decision is `is_scanned=True` with `reason="sparse_or_corrupt_text"`

#### Scenario: Empty page list is treated as scanned
- **WHEN** the detector receives an empty list of page texts
- **THEN** the decision is `is_scanned=True` with `reason="empty_pages"`

#### Scenario: CID glyph artifacts are stripped before evaluation
- **WHEN** page text contains `(cid:NNN)` font-mapping artifacts
- **THEN** those substrings are removed before character and word counting

#### Scenario: Non-ASCII scripts are counted correctly
- **WHEN** page text consists of Arabic, CJK, or Devanagari characters
- **THEN** those characters are counted as valid content characters using Unicode general category `L*`

---

### Requirement: Lightweight per-format document sampling
The system SHALL extract up to N pages of content from any file format in `CLASSIFICATION_FILE_EXTENSIONS` using only lightweight parsers, producing paginated text for digital formats and PIL Image objects for visual formats, without invoking Docling.

#### Scenario: PDF text extraction
- **WHEN** `FastDocumentSampler.sample` receives a PDF binary
- **THEN** it returns page texts (up to `max_pages`) delimited by `--- [Page N] ---` markers, with `is_visual=False`

#### Scenario: PDF image rendering is lazy
- **WHEN** `FastDocumentSampler.sample` receives a PDF binary
- **THEN** `page_images` is empty in the returned result; images are only produced on a subsequent explicit `render_pdf_pages` call

#### Scenario: Office format text extraction
- **WHEN** `FastDocumentSampler.sample` receives a `.docx`, `.pptx`, or `.xlsx` binary
- **THEN** it returns page-delimited text (up to `max_pages`) with `is_visual=False`

#### Scenario: Raster image handling
- **WHEN** `FastDocumentSampler.sample` receives a `.png`, `.jpg`, `.bmp`, `.webp`, `.gif`, or `.jfif` binary
- **THEN** `is_visual=True` and `page_images` contains exactly one PIL Image

#### Scenario: Multi-frame TIFF handling
- **WHEN** `FastDocumentSampler.sample` receives a `.tiff` or `.tif` binary
- **THEN** `is_visual=True` and `page_images` contains up to `max_pages` frames

#### Scenario: Plain text and markdown handling
- **WHEN** `FastDocumentSampler.sample` receives a `.txt`, `.md`, or `.html` binary
- **THEN** it returns text content (up to `max_pages * 500` words) with `is_visual=False`

#### Scenario: Unknown extension raises an error
- **WHEN** `FastDocumentSampler.sample` receives a file name with an unsupported extension
- **THEN** it raises `ValueError` with a message identifying the unsupported extension

#### Scenario: max_pages clamps to one page
- **WHEN** `FastDocumentSampler.sample` is called with `max_pages=1`
- **THEN** at most one page or frame is returned

---

### Requirement: Hybrid classification adapter
The system SHALL provide a `HybridClassificationAdapter` registered under the `"hybrid"` provider. The adapter's models are configured entirely inside `provider_config`: the text model is specified via `llm_inference` (provider), `model_id`, `api_base`, and `api_key` at the top level of `provider_config`; the vision model is specified via a nested `vlm` sub-object inside `provider_config` with its own `llm_inference`, `model_id`, `api_base`, and `api_key` keys.

#### Scenario: Hybrid provider_config shape — text model
- **WHEN** a flow config specifies `provider: "hybrid"` with `provider_config.model_id` and `provider_config.llm_inference`
- **THEN** the hybrid adapter uses those values to construct the text inference adapter via `LLMAdapterFactory`

#### Scenario: Hybrid provider_config shape — vision model
- **WHEN** a flow config specifies `provider_config.vlm.model_id` and `provider_config.vlm.llm_inference`
- **THEN** the hybrid adapter uses those values to construct the vision inference adapter via `LLMAdapterFactory`

#### Scenario: Digital PDF routes to text model
- **WHEN** a PDF is classified and the scan detector returns `is_scanned=False`
- **THEN** the text model (from `provider_config.model_id`) is called and the vision model is not called

#### Scenario: Scanned PDF routes to vision model
- **WHEN** a PDF is classified and the scan detector returns `is_scanned=True`
- **THEN** the PDF pages are rendered to images, the vision model (from `provider_config.vlm`) is called, and the text model is not called

#### Scenario: Image file always routes to vision model
- **WHEN** a `.png`, `.jpg`, `.tiff`, or similar image file is classified
- **THEN** the vision model is called without invoking the scan detector

#### Scenario: Office and text formats always route to text model
- **WHEN** a `.docx`, `.pptx`, `.xlsx`, `.txt`, `.md`, or `.html` file is classified
- **THEN** the text model is called without invoking the scan detector

#### Scenario: Missing vlm sub-object raises at construction
- **WHEN** a flow config with `provider: "hybrid"` omits `provider_config.vlm`
- **THEN** adapter construction raises `ValueError` before any document is classified

#### Scenario: Hybrid adapter returns standard output columns
- **WHEN** the hybrid adapter successfully classifies a document
- **THEN** the returned `ClassificationResponse` contains `document_type`, `confidence`, `reasoning`, and `success=True` — with no `is_scanned` field

#### Scenario: Hybrid adapter registered in factory
- **WHEN** `ClassificationAdapterFactory.create_adapter` is called with `provider="hybrid"`
- **THEN** a `HybridClassificationAdapter` instance is returned

---

### Requirement: DocumentClassifierOperator accepts hybrid provider
The system SHALL accept `"hybrid"` as a valid `provider` value in `DocumentClassifierOperator` configuration, including in flow validation and operator metadata.

#### Scenario: Hybrid provider passes flow validation
- **WHEN** a flow JSON sets `"provider": "hybrid"` on a `document_classifier` node
- **THEN** `FlowValidator` reports no provider-related errors

#### Scenario: Operator metadata lists hybrid as valid
- **WHEN** `DocumentClassifierOperator.get_metadata()` is called
- **THEN** `"hybrid"` appears in the `VALID_VALUES` list for the `provider` attribute

#### Scenario: Output columns are identical for all providers
- **WHEN** `DocumentClassifierOperator.transform` runs with `provider="hybrid"` or `provider="litellm"`
- **THEN** the output pyarrow Table contains the same columns (`document_type`, `_confidence`, `_reasoning`) regardless of provider

---

### Requirement: Classification config nested attribute group
The system SHALL expose `document_types`, `confidence_threshold`, and `doc_column` as a nested group under `classification_config.properties` in `DocumentClassifierOperator.get_metadata()["attributes"]`.

#### Scenario: Nested classification_config group is present
- **WHEN** `DocumentClassifierOperator.get_metadata()["attributes"]` is inspected
- **THEN** a `classification_config` key is present whose value has a `properties` dict containing `document_types`, `confidence_threshold`, and `doc_column`

---

### Requirement: Output config nested attribute group
The system SHALL expose `output_column`, `include_confidence`, and `include_reasoning` as a nested group under `output_config.properties` in `DocumentClassifierOperator.get_metadata()["attributes"]`.

#### Scenario: Nested output_config group is present
- **WHEN** `DocumentClassifierOperator.get_metadata()["attributes"]` is inspected
- **THEN** an `output_config` key is present whose value has a `properties` dict containing `output_column`, `include_confidence`, and `include_reasoning`

---

### Requirement: Hybrid provider schema in provider_config
The system SHALL include a `"hybrid"` entry in `provider_config.providers` whose `properties` declare the text model fields (`llm_inference`, `model_id`, `api_base`, `api_key`) at the root level and a nested `vlm` object (with the same four fields) for the vision model.

#### Scenario: Hybrid provider schema declares text and vlm fields
- **WHEN** `DocumentClassifierOperator.get_metadata()["attributes"]["provider_config"]["providers"]["hybrid"]` is inspected
- **THEN** its `properties` dict contains `llm_inference`, `model_id`, `api_base`, `api_key`, and a `vlm` sub-object with its own `properties` for those same four fields

#### Scenario: max_pages is a top-level operator attribute not inside provider schema
- **WHEN** `DocumentClassifierOperator.get_metadata()["attributes"]` is inspected
- **THEN** `max_pages` is a top-level attribute (sibling of `provider`, `confidence_threshold`, etc.), not a field inside `provider_config.providers["hybrid"].properties`

---

### Requirement: Provider attribute preserved at top level with hybrid value
The top-level `provider` attribute in `get_metadata()["attributes"]` SHALL remain at the root of the attributes dict and SHALL list `"hybrid"` alongside `"litellm"` and `"watsonx"` in `valid_values`.

#### Scenario: Flat provider attribute is preserved at top level
- **WHEN** `DocumentClassifierOperator.get_metadata()["attributes"]` is inspected
- **THEN** a top-level `provider` key is still present with `valid_values` listing `"litellm"`, `"watsonx"`, and `"hybrid"`
