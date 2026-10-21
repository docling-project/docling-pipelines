# frontend/state/flows-slice Specification

## Purpose
The flows-slice is the Redux slice that manages flow entity state across the application. It maintains two parallel representations: a `items` map of `FlowRow` display objects used by tables, and a `currentFlow` full `Flow` object (with pipeline definition) used by the Canvas page. It also owns the `flowRunProperties` settings for canvas run-time configuration.

## Requirements

### Requirement: Flow items map
The slice SHALL maintain a map of `FlowRow` display objects keyed by flow ID, used by the ProjectDetail and FlowDetail pages.

#### Scenario: setFlows replaces the entire map
- **WHEN** setFlows is dispatched with a record of flows
- **THEN** state.items is replaced with the provided map

#### Scenario: setFlow upserts a single entry
- **WHEN** setFlow is dispatched with a flowId and FlowRow
- **THEN** that entry is inserted or updated in state.items

#### Scenario: removeFlow deletes an entry
- **WHEN** removeFlow is dispatched with a flowId
- **THEN** that flow is removed from state.items

### Requirement: Current flow for Canvas
The slice SHALL hold a single full `Flow` object as `currentFlow` for the Canvas page, separate from the display items map.

#### Scenario: setCurrentFlow stores the full flow
- **WHEN** setCurrentFlow is dispatched with a Flow object
- **THEN** state.currentFlow is set to that object

#### Scenario: clearFlow nulls currentFlow
- **WHEN** clearFlow is dispatched
- **THEN** state.currentFlow is null

### Requirement: Fetch and save async thunks
The slice SHALL expose `fetchFlow` and `saveFlow` async thunks that set loading/error state during their lifecycle.

#### Scenario: fetchFlow sets loading while in flight
- **WHEN** fetchFlow is dispatched and pending
- **THEN** state.loading is true

#### Scenario: fetchFlow sets currentFlow on success
- **WHEN** fetchFlow resolves successfully
- **THEN** state.currentFlow is set to the fetched flow and state.loading is false

#### Scenario: saveFlow preserves canvas definition
- **WHEN** saveFlow resolves successfully
- **THEN** the canvas node definition from the sent flow is preserved — backend definition is ignored

### Requirement: Flow run properties
The slice SHALL maintain `flowRunProperties` (incremental processing, validation, node output preview, intermediate storage) as canvas run-time settings.

#### Scenario: setFlowRunProperties updates run settings
- **WHEN** setFlowRunProperties is dispatched
- **THEN** state.flowRunProperties is updated with the provided values
