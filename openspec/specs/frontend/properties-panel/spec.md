# frontend/properties-panel Specification

## Purpose
The properties-panel capability is the operator configuration flyout that opens when a node is selected on the canvas. It renders the operator's icon, type label, an editable display name, a description, and three tabs: Configuration (operator-specific fields), Input (upstream features flowing into the node), and Output (the union of the node's own output features and the passthrough input features, representing everything a downstream node would receive). For the `merge` operator the Output tab shows only the node's own output features, because the backend already writes the full union into `output_features` directly. It is the primary surface through which users configure individual pipeline operators before saving or running a flow.

## Requirements

### Requirement: Three-tab structure
The panel SHALL always render three tabs — Configuration, Input, and Output — for every selected node.

#### Scenario: Configuration tab is default
- **WHEN** the user opens the panel by selecting a node
- **THEN** the Configuration tab is active and the operator-specific form is visible

#### Scenario: Input tab shows upstream features
- **WHEN** the user selects the Input tab
- **THEN** the features flowing into the selected node from upstream operators are displayed

#### Scenario: Output tab shows downstream features
- **WHEN** the user selects the Output tab
- **THEN** the combined set of features the node will emit to downstream operators is displayed

### Requirement: Editable display name
The panel SHALL allow the user to rename the node's display label inline via an edit icon.

#### Scenario: Edit mode activates on icon click
- **WHEN** the user clicks the edit icon next to the display name
- **THEN** the display name field becomes editable and receives focus

#### Scenario: Name saved on blur
- **WHEN** the user finishes editing and clicks away
- **THEN** the edited display name is persisted to the canvas model

### Requirement: Save button disabled when required params are missing
The Save button — owned by Elyra's `CommonProperties` flyout, not rendered by this panel — SHALL be disabled whenever any required operator parameter has no value. The panel controls this by calling `controller.setSaveButtonDisable(true/false)` after evaluating the current property values against the operator's required attribute metadata.

#### Scenario: Save disabled on missing required field
- **WHEN** a required configuration field is empty
- **THEN** the Save button is disabled

#### Scenario: Save enabled when all required fields have values
- **WHEN** all required configuration fields are filled
- **THEN** the Save button is enabled

### Requirement: Operator-specific configuration panel
The Configuration tab SHALL render the operator-specific form registered for the selected operator type. When no panel is registered for an operator, a placeholder message SHALL be shown.

#### Scenario: Known operator shows its form
- **WHEN** the selected node is a known operator (e.g. ingest_source, chunker)
- **THEN** the operator's custom configuration form is rendered in the Configuration tab

#### Scenario: Unknown operator shows placeholder
- **WHEN** the selected node has no registered configuration panel
- **THEN** a placeholder message is shown in the Configuration tab

### Requirement: General operator configuration lifecycle
The properties panel SHALL execute a unified 5-step lifecycle for all operator nodes: reading metadata from controller `appData`, loading persisted property values via `controller.getPropertyValue()`, rendering metadata-driven fields, evaluating required fields to toggle save readiness via `controller.setSaveButtonDisable()`, and writing modifications back via `controller.updatePropertyValue()`.

#### Scenario: Form loaded with initial node data
- **WHEN** an operator node is selected on the canvas
- **THEN** the panel retrieves its existing configuration from the canvas controller and populates the active inputs

#### Scenario: Value changes update canvas controller property
- **WHEN** the user updates a form field
- **THEN** the change is validated against operator schema and written to the canvas controller property cache

### Requirement: VectorDB feature mapping and backend configuration
The VectorDB custom panel SHALL support database backend selection (OpenSearch / Milvus), index/collection naming, and a feature mapping tearsheet that manages embeddings-to-field bindings and calls the feature enrichment endpoint.

#### Scenario: Backend selection displays relevant configuration fields
- **WHEN** the user selects "OpenSearch" or "Milvus" as the vector database provider
- **THEN** provider-specific connection and index settings are displayed

#### Scenario: Feature mapping tearsheet manages embedding field bindings
- **WHEN** the user opens the feature mapping tearsheet
- **THEN** upstream embedding features and document metadata can be mapped to vector database payload fields

### Requirement: AnnotationFilter SQL condition builder
The AnnotationFilter custom panel SHALL render an interactive SQL-like condition builder supporting dual storage formats (`criteria_list` for UI state and `criteria_json` for engine execution) with tearsheets for condition creation and full query inspection.

#### Scenario: Condition builder creates structured filter rules
- **WHEN** the user adds filter criteria (column, operator, comparison value)
- **THEN** the panel renders the rule in the condition builder and serializes it to both list and JSON formats

#### Scenario: Criteria full view tearsheet displays complete filter logic
- **WHEN** the user clicks to view the full criteria
- **THEN** the criteria full view tearsheet opens, rendering the complete composed query expression

### Requirement: Merging operator live feature enrichment and preview
The Merging operator panel SHALL trigger live `enrichFlowFeatures()` API requests on strategy or input changes and provide an interactive preview tearsheet with Venn diagrams illustrating incoming stream feature resolution.

#### Scenario: Strategy change triggers live feature enrichment
- **WHEN** the user alters the merge strategy or input stream mapping
- **THEN** the panel calls the enrichment API to compute the merged output feature schema

#### Scenario: Preview tearsheet displays Venn diagram representation
- **WHEN** the user opens the merge preview tearsheet
- **THEN** an interactive SVG Venn diagram displays the feature union and collision resolution across incoming streams

### Requirement: StorageOutput multi-provider backend configuration
The StorageOutput panel SHALL dynamically render connection and credential fields tailored to the selected storage provider (Filesystem, S3, Box, SharePoint, Google Drive), enforcing required credentials before enabling panel save.

#### Scenario: Provider change renders appropriate backend fields
- **WHEN** the user switches between storage providers (e.g. Filesystem to S3)
- **THEN** the panel updates the configuration form with the provider's specific connection and bucket parameters

### Requirement: Embeddings dynamic model resolution
The Embeddings custom panel SHALL fetch available models dynamically from the provider API endpoint when a provider (Ollama, WatsonX) is selected, populating the model dropdown with available options.

#### Scenario: Dynamic model list loaded on provider change
- **WHEN** the user selects an embedding provider
- **THEN** the panel queries the provider models endpoint and updates the model selection dropdown

### Requirement: Chunker Docling Serve hybrid mode coupling
The Chunker panel SHALL enforce hybrid chunking strategy when Docling Serve is selected as the upstream parser, disabling conflicting strategy choices.

#### Scenario: Docling Serve locks chunking strategy to hybrid
- **WHEN** the upstream pipeline uses Docling Serve parser
- **THEN** the chunker strategy selection is locked to hybrid mode with an informational helper message

### Requirement: Branching read-only configuration state
The Branching panel SHALL render as an informational read-only view in the properties flyout, explaining that branch conditions are configured directly on output canvas links rather than within the node properties panel.

#### Scenario: Branching panel shows link condition configuration instructions
- **WHEN** a branching node is selected
- **THEN** the panel displays read-only instructions directing the user to configure condition expressions on outgoing connection links

### Requirement: Properties panel accessibility and keyboard tab navigation
The properties panel SHALL support full keyboard navigation across the three tabs (Configuration, Input, Output) via Left/Right Arrow keys, ensure all input controls have associated accessible labels, and trap focus within modal tearsheets when open.

#### Scenario: Arrow keys switch active tab
- **WHEN** focus is on a properties tab header and the user presses the Right Arrow key
- **THEN** focus and active selection move to the adjacent tab header

#### Scenario: Form controls contain accessible labels
- **WHEN** operator fields are rendered
- **THEN** every input, select, and toggle element possesses an accessible name linked via `htmlFor` or `aria-label`
