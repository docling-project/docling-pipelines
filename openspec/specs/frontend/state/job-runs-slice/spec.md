# frontend/state/job-runs-slice Specification

## Purpose
The job-runs-slice is the Redux slice that manages job run execution state. It maintains a flat `items` map of `JobRun` objects, a `byJobId` index mapping flow IDs to their run IDs, tracks the active run's ID and running status, and holds `executionLogs` — the live poll response from the job run status API used by the ReadOnlyCanvas.

## Requirements

### Requirement: Job run items and byJobId index
The slice SHALL maintain a map of JobRun objects and a secondary index from job (flow) ID to run IDs.

#### Scenario: setJobRun upserts and updates index
- **WHEN** setJobRun is dispatched with a jobRunId and JobRun
- **THEN** the run is added to state.items and its ID is appended to state.byJobId[jobRun.jobId] if not already present

### Requirement: Active run tracking
The slice SHALL track the currently executing run via `isRunning`, `currentJobRunId`, and `currentJobId`.

#### Scenario: setRunning marks a run as active
- **WHEN** setRunning is dispatched with isRunning true, a jobRunId, and a jobId
- **THEN** state.isRunning is true, state.currentJobRunId and state.currentJobId are set

#### Scenario: Clearing running state
- **WHEN** setRunning is dispatched with isRunning false
- **THEN** state.isRunning is false

### Requirement: Execution logs for polling
The slice SHALL store the latest job run status poll response as `executionLogs`, used by ReadOnlyCanvas to render node decorations and the side panel.

#### Scenario: setExecutionLogs stores poll response
- **WHEN** setExecutionLogs is dispatched with a JobRunStatusResponse
- **THEN** state.executionLogs is set to that response

#### Scenario: setExecutionLogs null clears logs
- **WHEN** setExecutionLogs is dispatched with null
- **THEN** state.executionLogs is null

### Requirement: Loading and error state
The slice SHALL track a loading flag and error string for async operations.

#### Scenario: setLoading updates loading flag
- **WHEN** setLoading is dispatched
- **THEN** state.loading reflects the dispatched value

#### Scenario: setError stores the error message
- **WHEN** setError is dispatched with an error string
- **THEN** state.error is set to that string
