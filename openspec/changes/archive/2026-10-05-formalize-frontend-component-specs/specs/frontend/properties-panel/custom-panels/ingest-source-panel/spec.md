# properties-panel/custom-panels/ingest-source-panel Specification

## Purpose

The ingest-source custom panel is the configuration form for the `ingest_source` operator. It allows users to select a data source provider, supply provider-specific connection parameters, and configure file ingestion settings including file type filters and a maximum file count.

## ADDED Requirements

### Requirement: Provider selection
The panel SHALL present a dropdown of available providers populated from operator metadata.

#### Scenario: Provider dropdown shows metadata values
- **WHEN** the panel opens for an ingest_source node
- **THEN** the provider dropdown lists all valid_values from the operator's attribute metadata

#### Scenario: Changing provider resets connection params
- **WHEN** the user selects a different provider
- **THEN** connection_params and credentials are cleared

### Requirement: Provider-specific connection fields
The panel SHALL show provider-specific structured fields when a provider schema is available, or a JSON textarea for custom/unknown providers.

#### Scenario: Structured fields for known provider
- **WHEN** the selected provider has a schema defined in operator metadata
- **THEN** structured form fields are rendered for that provider's connection parameters

#### Scenario: JSON textarea for custom provider
- **WHEN** the selected provider is "custom" or has no schema
- **THEN** a JSON textarea is shown for free-form connection params

#### Scenario: Provider fields hidden until provider selected
- **WHEN** no provider is selected
- **THEN** the provider configuration and ingestion settings sections are not rendered

### Requirement: Include/exclude filter conflict warning
The panel SHALL warn the user when the same file extension appears in both the include and exclude filter selections.

#### Scenario: Conflict warning shown
- **WHEN** one or more file extensions are selected in both include and exclude filters
- **THEN** a warning is displayed naming the conflicting extensions and stating they will be skipped

### Requirement: Required field validation
The panel SHALL mark required fields as invalid when they have no value, preventing Save.

#### Scenario: Provider required
- **WHEN** no provider is selected and the user attempts to save
- **THEN** the provider dropdown shows an invalid state with an error message
