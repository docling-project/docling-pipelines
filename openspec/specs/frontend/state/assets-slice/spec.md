# frontend/state/assets-slice Specification

## Purpose

The assets-slice capability is the Redux slice that manages shared navigation asset state for flows and job runs. It holds a keyed map of flow and job run assets used across pages for breadcrumb navigation, run history lookup, and canvas entry. Projects are explicitly excluded — they are owned by `projectsSlice`. The slice also tracks `selectedFlowId` and `selectedJobRunId` for the current navigation context.

## Requirements

### Requirement: Flow asset map management
The slice SHALL maintain a `flows` map keyed by `flowId`. `setFlows` SHALL replace the entire map atomically. `setFlow` SHALL upsert a single entry without affecting other entries.

#### Scenario: setFlows replaces entire map
- **WHEN** `setFlows` is dispatched with a new flows map
- **THEN** `state.flows` is replaced entirely with the provided map

#### Scenario: setFlow upserts a single entry
- **WHEN** `setFlow` is dispatched with `{ flowId, flow }`
- **THEN** `state.flows[flowId]` is set to `flow` and all other entries are unchanged

### Requirement: Job run asset map management
The slice SHALL maintain a `jobRuns` map keyed by `jobRunId`. `setJobRuns` SHALL replace the entire map atomically. `setJobRun` SHALL upsert a single entry without affecting other entries.

#### Scenario: setJobRuns replaces entire map
- **WHEN** `setJobRuns` is dispatched with a new job runs map
- **THEN** `state.jobRuns` is replaced entirely with the provided map

#### Scenario: setJobRun upserts a single entry
- **WHEN** `setJobRun` is dispatched with `{ jobRunId, jobRun }`
- **THEN** `state.jobRuns[jobRunId]` is set to `jobRun` and all other entries are unchanged

### Requirement: Selected flow and job run tracking
The slice SHALL track `selectedFlowId` and `selectedJobRunId` as nullable strings. `selectFlow` and `selectJobRun` SHALL set the respective ID, accepting `null` to clear the selection.

#### Scenario: selectFlow sets the selected flow ID
- **WHEN** `selectFlow` is dispatched with a flow ID string
- **THEN** `state.selectedFlowId` is set to that ID

#### Scenario: selectFlow clears the selection when null is dispatched
- **WHEN** `selectFlow` is dispatched with `null`
- **THEN** `state.selectedFlowId` is `null`

#### Scenario: selectJobRun sets the selected job run ID
- **WHEN** `selectJobRun` is dispatched with a job run ID string
- **THEN** `state.selectedJobRunId` is set to that ID

### Requirement: Projects are not managed by this slice
The slice SHALL NOT contain any actions or state for project entities. Projects are owned exclusively by `projectsSlice`.

#### Scenario: No project actions exist on the slice
- **WHEN** the assets slice actions are enumerated
- **THEN** no action relating to projects is present
