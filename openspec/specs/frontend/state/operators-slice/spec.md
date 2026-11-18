# frontend/state/operators-slice Specification

## Purpose
The operators-slice is the Redux slice that manages operator metadata and feature state. It holds the full operator metadata map (attribute definitions, valid values, defaults) used by CustomPanels to render their configuration forms, per-node enriched feature maps (input and output features for each canvas node), and a separate loading flag for feature enrichment API calls.

## Requirements

### Requirement: Operator metadata map
The slice SHALL maintain a map of operator metadata keyed by operator short_name, used by all CustomPanel components to resolve attribute definitions, valid values, and defaults.

#### Scenario: setOperatorMetadata replaces the map
- **WHEN** setOperatorMetadata is dispatched
- **THEN** state.metadata is replaced with the provided map, loading is false, and error is null

### Requirement: Per-node feature map
The slice SHALL store enriched feature metadata keyed by node ID, where each entry contains the node's input_features and output_features.

#### Scenario: setNodeFeatures stores enriched features
- **WHEN** setNodeFeatures is dispatched with a node feature map
- **THEN** state.nodeFeatures is set to that map

### Requirement: Separate features loading state
The slice SHALL maintain a `featuresLoading` flag that is independent of the main `loading` flag, to track feature enrichment API calls without blocking other operator state reads.

#### Scenario: setFeaturesLoading updates only features loading
- **WHEN** setFeaturesLoading is dispatched with true
- **THEN** state.featuresLoading is true and state.loading is unchanged

### Requirement: Loading and error state
The slice SHALL track a loading flag and error string for the main metadata fetch lifecycle.

#### Scenario: setLoading updates loading flag
- **WHEN** setLoading is dispatched
- **THEN** state.loading reflects the dispatched value

#### Scenario: setError stores the error message
- **WHEN** setError is dispatched with an error string
- **THEN** state.error is set to that string
