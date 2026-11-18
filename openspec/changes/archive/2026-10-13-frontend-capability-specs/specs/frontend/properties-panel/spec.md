# Spec Delta

## ADDED Requirements

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
