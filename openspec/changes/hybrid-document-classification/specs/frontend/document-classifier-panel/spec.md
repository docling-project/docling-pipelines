# Spec Delta

## Purpose

Properties panel configuration UI for the `document_classifier` operator — provides provider selection, nested configuration groups (classification config, output config), structured per-provider connection fields, and hybrid-specific fields for vision model and page limit.

## ADDED Requirements

### Requirement: Provider dropdown populated from metadata
The panel SHALL render a provider `Dropdown` whose items come exclusively from `attributes.provider.valid_values` in the operator metadata, so that adding a new backend provider (e.g. `"hybrid"`) automatically appears in the UI without a frontend code change.

#### Scenario: Hybrid provider appears in dropdown
- **WHEN** the user opens the Document Classifier properties panel
- **THEN** the provider `Dropdown` includes `"hybrid"` as a selectable item

#### Scenario: Selecting a provider clears provider_config
- **WHEN** the user changes the selected provider
- **THEN** `provider_config` is reset to `null` and all structured connection fields clear

---

### Requirement: Nested attribute group reading
The panel SHALL read its field metadata from nested attribute groups (`classification_config.properties.*` and `output_config.properties.*`) in the same way `ExtractPanelBody` reads from `text_extraction.properties.*` and `entity_extraction.properties.*`.

#### Scenario: Classification config fields are read from nested group
- **WHEN** the panel initialises
- **THEN** `document_types`, `confidence_threshold`, and `doc_column` field metadata (description, default, required, valid_values) are sourced from `attributes.classification_config.properties`

#### Scenario: Output config fields are read from nested group
- **WHEN** the panel initialises
- **THEN** `output_column`, `include_confidence`, and `include_reasoning` field metadata are sourced from `attributes.output_config.properties`

---

### Requirement: Hybrid provider VLM sub-object fields
When the hybrid provider is selected, the Provider configuration accordion SHALL render a visually grouped "Vision model" section containing `TextInput` fields for `vlm.model_id`, `vlm.api_base`, `vlm.api_key`, and `vlm.llm_inference`. These fields map to `provider_config.vlm.*` and SHALL NOT be visible when any other provider is selected.

#### Scenario: VLM sub-object fields shown for hybrid
- **WHEN** the user selects `provider = "hybrid"`
- **THEN** the Provider configuration accordion renders a "Vision model" section with inputs for `vlm.llm_inference`, `vlm.model_id`, `vlm.api_base`, and `vlm.api_key`

#### Scenario: VLM fields hidden for other providers
- **WHEN** the user selects `provider = "litellm"` or `provider = "watsonx"`
- **THEN** the VLM sub-object section is not rendered

---

### Requirement: max_pages field as a top-level operator config input
The panel SHALL render a `NumberInput` for `max_pages` sourced from the top-level `attributes.max_pages` metadata (not from `provider_config`). The field SHALL be visible for all providers but is most relevant when `provider = "hybrid"`.

#### Scenario: max_pages field is rendered
- **WHEN** the user opens the Document Classifier properties panel
- **THEN** a `NumberInput` for `max_pages` is rendered with a default value of 5 and minimum value of 1

#### Scenario: max_pages persists to top-level controller key
- **WHEN** the user changes the `max_pages` value
- **THEN** `controller.updatePropertyValue({ name: "max_pages" }, value)` is called (not nested inside `provider_config`)

---

### Requirement: Required-field save-gate includes hybrid VLM fields
The Save button SHALL remain disabled until all required fields for the selected provider are filled. For `provider = "hybrid"`, `provider_config.vlm.model_id` is required; `provider_config.vlm.llm_inference` defaults to the same value as `provider_config.llm_inference` when absent.

#### Scenario: Save gated on missing VLM model_id for hybrid
- **WHEN** `provider = "hybrid"` and `provider_config.vlm.model_id` has no value
- **THEN** `controller.setSaveButtonDisable(true)` is called and the `vlm.model_id` field shows an invalid state

#### Scenario: Save enabled when hybrid fields are complete
- **WHEN** `provider = "hybrid"`, `provider_config.model_id` is filled, and `provider_config.vlm.model_id` is filled
- **THEN** `controller.setSaveButtonDisable(false)` is called

---

### Requirement: Structured provider connection fields for hybrid
When `provider = "hybrid"`, the panel SHALL render the `ProviderFieldsForm` using the `"hybrid"` entry from `attributes.provider_config.providers`, displaying structured fields for the text model (`llm_inference`, `model_id`, `api_base`, `api_key`) followed by the VLM sub-object fields.

#### Scenario: ProviderFieldsForm renders for hybrid
- **WHEN** `provider = "hybrid"` and `attributes.provider_config.providers["hybrid"].properties` is non-empty
- **THEN** `ProviderFieldsForm` renders both the text model connection fields and the VLM sub-object section

---

### Requirement: Constants file updated for new keys
The `DOCUMENT_CLASSIFIER_ATTRIBUTE` constants object SHALL include keys for `max_pages`, `max_content_length`, `classification_config`, and `output_config` so no attribute key is hardcoded as a raw string inside `DocumentClassifier.tsx`.

#### Scenario: max_pages key is exported from constants
- **WHEN** `DOCUMENT_CLASSIFIER_ATTRIBUTE.MAX_PAGES` is accessed
- **THEN** it returns the string `"max_pages"`

#### Scenario: Nested group keys are exported from constants
- **WHEN** `DOCUMENT_CLASSIFIER_ATTRIBUTE.CLASSIFICATION_CONFIG` and `DOCUMENT_CLASSIFIER_ATTRIBUTE.OUTPUT_CONFIG` are accessed
- **THEN** they return `"classification_config"` and `"output_config"` respectively

---

### Requirement: Keyboard accessibility of new fields
All new fields (VLM sub-object inputs and `max_pages`) SHALL have associated accessible labels and SHALL be reachable via keyboard Tab navigation in the same sequence as surrounding fields.

#### Scenario: VLM fields and max_pages are keyboard-reachable
- **WHEN** the user navigates the Provider configuration accordion with the Tab key
- **THEN** focus visits each VLM sub-object field and `max_pages` in document order without requiring a mouse interaction
