# properties-panel/custom-panels/vectordb-panel Specification

## Purpose

The vectordb custom panel is the configuration form for the `vectordb` operator. It lets users select a vector database provider, configure provider-specific settings and credentials, and manage feature mappings — the mapping of pipeline output features to vector database fields. Feature mappings are configured via a dedicated tearsheet opened from the panel.

## ADDED Requirements

### Requirement: Provider selection
The panel SHALL present a dropdown of supported vector database providers.

#### Scenario: Provider selection shows backend-specific fields
- **WHEN** the user selects a vector database provider
- **THEN** the configuration fields specific to that provider become visible

### Requirement: Feature mapping summary table
The panel SHALL show a summary table of existing feature mappings once configured.

#### Scenario: Empty state with Add action when no mappings
- **WHEN** no feature mappings have been saved for the node
- **THEN** an empty state is shown with an "Add feature mappings" action

#### Scenario: Summary table shown when mappings exist
- **WHEN** feature mappings have been saved
- **THEN** the summary table lists each mapping with its mandatory flag

### Requirement: Feature mapping tearsheet
The panel SHALL open a feature mapping tearsheet when the user initiates an add or edit mapping action.

#### Scenario: Tearsheet opens on Add/Edit click
- **WHEN** the user clicks "Add feature mappings" or the edit action
- **THEN** the VectorDB feature mapping tearsheet opens with available features and current mappings

#### Scenario: Tearsheet enriches features before opening
- **WHEN** the tearsheet is about to open
- **THEN** the panel calls the flow-features enrichment API to populate available_resources and available_features

### Requirement: Credentials via Vault or plaintext
The panel SHALL allow credential fields to accept either a plaintext value or a Vault reference.

#### Scenario: Vault reference accepted for credential fields
- **WHEN** the user enables vault mode for a credential field
- **THEN** the field stores a vault:// URI instead of a plaintext value
