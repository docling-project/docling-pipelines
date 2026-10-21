# properties-panel/custom-panels/embeddings-panel Specification

## Purpose

The embeddings custom panel is the configuration form for the `embeddings` operator. It lets users select an embeddings provider, configure provider-specific settings (API base, model, batch size, credentials), and load available models from the provider's API for selection.

## ADDED Requirements

### Requirement: Provider selection drives field visibility
The panel SHALL show only the configuration fields relevant to the selected embeddings provider.

#### Scenario: Provider-specific fields shown on selection
- **WHEN** the user selects an embeddings provider
- **THEN** the configuration fields specific to that provider become visible

#### Scenario: Fields from previous provider are hidden
- **WHEN** the user changes to a different provider
- **THEN** only the new provider's fields are shown

### Requirement: Dynamic model loading
The panel SHALL fetch available model options from the provider's API using the configured API base and display them in a dropdown for selection.

#### Scenario: Loading state shown during model fetch
- **WHEN** the panel fetches models from the provider API
- **THEN** an inline loading indicator is shown in the model selector

#### Scenario: Model dropdown populated after fetch
- **WHEN** the model fetch completes successfully
- **THEN** the model dropdown lists the available models filtered for embeddings use

#### Scenario: Error shown when model fetch fails
- **WHEN** the model fetch returns an error
- **THEN** an inline notification describing the failure is shown

### Requirement: Credentials via Vault or plaintext
The panel SHALL allow credential fields to be entered as plaintext or as a Vault reference, via the VaultInput component.

#### Scenario: Vault toggle switches input mode
- **WHEN** the user toggles "Use Vault" on a credential field
- **THEN** the input switches to vault reference mode showing the vault:// prefix
