# Spec Delta

## Purpose

The run-details-page capability is the standalone run viewer page that renders a read-only canvas for a specific job run, fetching the flow-definition snapshot and arming the background poller so users can inspect live or historical execution state.

## ADDED Requirements

### Requirement: Route and query parameters
The page SHALL read `flow_id` and `run_id` from the path parameters at `/flows/:flow_id/runs/:run_id` and `project_id` from the `?project_id=` query string. All three SHALL be used for API calls and back-navigation.

#### Scenario: Flow and run IDs from path params
- **WHEN** the user navigates to `/flows/abc/runs/xyz`
- **THEN** `flowId = 'abc'` and `runId = 'xyz'` are used for all API calls

---

### Requirement: Flow-definition snapshot fetch
The page SHALL fetch the flow definition as it was at run time via `GET /api/job-runs/:runId/flow-definition`. This snapshot SHALL be used to render the canvas, ensuring the viewer shows exactly what ran rather than the current (potentially modified) live definition.

#### Scenario: Snapshot used for canvas rendering
- **WHEN** the bootstrap fetch completes
- **THEN** `ReadOnlyCanvas` receives the snapshot definition, not the current live flow

#### Scenario: Missing snapshot shows error
- **WHEN** the snapshot response has no definition
- **THEN** an inline error notification is shown: "Flow definition not available for this run."

---

### Requirement: Poller bootstrap on mount
After the snapshot and initial run status are fetched, the page SHALL dispatch `setCurrentRun` (with `jobId` and `jobRunId`) and start the background poller via `startPoll(runId)` so execution logs are kept up to date. Stale logs from previous viewer sessions SHALL be cleared (`setExecutionLogs(null)`) before the poller starts.

#### Scenario: Poller started after bootstrap
- **WHEN** the snapshot and initial run fetch both succeed
- **THEN** `setCurrentRun` is dispatched and `startPoll(runId)` is called

#### Scenario: Stale logs cleared before new poller
- **WHEN** the bootstrap sequence starts
- **THEN** `setExecutionLogs(null)` is dispatched before polling begins

---

### Requirement: Loading and error guards
The page SHALL show an `InlineLoading` spinner while the snapshot is being fetched. It SHALL show an `InlineNotification` with `kind="error"` when the bootstrap sequence fails (API error or missing definition). The canvas SHALL NOT be rendered until the snapshot is available.

#### Scenario: Spinner while loading
- **WHEN** the snapshot has not yet resolved
- **THEN** an `InlineLoading` spinner is displayed

#### Scenario: Error notification on bootstrap failure
- **WHEN** the bootstrap fetch throws an error
- **THEN** an inline error notification is shown with "Failed to load run details. Please try again."

---

### Requirement: Exit navigates back to flow detail
The page SHALL navigate back to the flow detail page (`/flows/:flow_id?project_id=…`) when the user exits the run viewer.

#### Scenario: Exit navigates to flow detail
- **WHEN** the user triggers `onExit`
- **THEN** the router navigates to the flow detail page for this flow

---

### Requirement: Run-again replaces current run
When the user triggers "Run again", the page SHALL update Redux with the new job run ID, start polling for the new run, and replace the current URL with the new run's route so the URL always reflects what is shown.

#### Scenario: Run-again updates URL and starts new poll
- **WHEN** the user clicks "Run again" and a new job run ID is returned
- **THEN** `setCurrentRun` is dispatched with the new IDs, `startPoll` is called, and the URL is replaced with the new run route

---

### Requirement: Stop cancels run and resumes polling
When the user stops an in-progress run, the page SHALL stop the poller, call `cancelJobRun`, and restart the poller to observe the terminal status.

#### Scenario: Stop halts poll, cancels run, then resumes polling
- **WHEN** the user clicks Stop
- **THEN** `stopPoll()` is called, `cancelJobRun` is invoked, and `startPoll(runId)` resumes polling after the cancel settles

---

### Requirement: Cleanup on unmount
The page SHALL stop the poller and clear all run-related Redux state (`setCurrentRun(null)`, `setExecutionLogs(null)`, `setRunning(false)`) on unmount, leaving no residual state for the next page.

#### Scenario: State cleared on unmount
- **WHEN** the run details page unmounts
- **THEN** `stopPoll()` is called and `setCurrentRun`, `setExecutionLogs`, and `setRunning` are all reset
