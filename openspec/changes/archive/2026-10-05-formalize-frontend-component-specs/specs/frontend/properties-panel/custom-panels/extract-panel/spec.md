# properties-panel/custom-panels/extract-panel Specification

## Purpose

The extract custom panel is the configuration form for the `extract_operator`. It lets users configure text extraction (provider, PDF backend, VLM/ASR pipeline, image export mode, additional format support) and entity extraction (provider, LLM config, Watsonx config) for the Docling-based document processing stage.

## ADDED Requirements

### Requirement: Text extraction provider selection
The panel SHALL present a dropdown of text extraction providers and show provider-specific configuration fields based on the selection.

#### Scenario: Provider-specific fields shown
- **WHEN** the user selects a text extraction provider
- **THEN** the configuration fields specific to that provider become visible

#### Scenario: Docling Serve config visible when selected
- **WHEN** the user selects "docling_serve" as the text provider
- **THEN** the Docling Serve configuration section is shown

### Requirement: Entity extraction toggle
The panel SHALL allow entity extraction to be enabled or disabled via a toggle.

#### Scenario: Entity fields hidden when disabled
- **WHEN** entity extraction is toggled off
- **THEN** entity provider and configuration fields are hidden

#### Scenario: Entity fields shown when enabled
- **WHEN** entity extraction is toggled on
- **THEN** entity provider selection and provider-specific config fields are shown

### Requirement: Additional format support
The panel SHALL allow users to select additional document formats (e.g. HTML, AsciiDoc, CSV) to process beyond the defaults.

#### Scenario: Additional formats selectable
- **WHEN** the user opens the Additional Formats section
- **THEN** checkboxes for supported additional formats are available for selection
