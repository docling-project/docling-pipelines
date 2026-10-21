# flow-detail-page Specification

## Purpose

The flow-detail-page capability is the per-flow run history page that shows execution metrics, a filterable runs table, and a slide-in info panel, letting users monitor, cancel, delete, and navigate to individual runs.

## Requirements

### Requirement: Route and query parameters
The page SHALL read `flow_id` from the path parameter and `project_id` from the `?project_id=` query string. Both SHALL be used for navigation and data fetches.

#### Scenario: Flow ID from path param
- **WHEN** the user navigates to `/projects/:projectId/:flowId`
- **THEN** `flow_id` drives all flow-related API calls and navigation

### Requirement: Flow bootstrap fetch
The page SHALL fetch the flow from `GET /api/flows/:id` only when it is not already in the Redux store. On 404 the page SHALL redirect to the error page with status 404. On other errors it SHALL redirect with status 500. The fetch SHALL be aborted on unmount.

#### Scenario: No fetch when flow is in store
- **WHEN** `state.flow.items[flowId]` is already populated
- **THEN** `GET /api/flows/:id` is NOT called

#### Scenario: 404 redirects to error page
- **WHEN** `GET /api/flows/:id` returns 404
- **THEN** the router replaces with the error page showing "Flow not found."

### Requirement: Project bootstrap fetch
The page SHALL fetch the project from `GET /api/projects/:id` if `projectId` is set and the project is not in the Redux store, so the breadcrumb and info panel can display the project name instead of the raw UUID. The fetch SHALL be cancelled on unmount.

#### Scenario: Project name resolved from store for panel
- **WHEN** the project is available in the Redux store
- **THEN** `FlowInfoPanel` receives the human-readable project name

### Requirement: Runs fetch from API (local state)
The page SHALL fetch job runs for the flow via `GET /api/job-runs?job_id=:flowId` on mount and hold them in local component state (not Redux). Runs are transient and SHALL NOT survive navigation away and back. Refresh SHALL trigger a full re-fetch.

#### Scenario: Runs loaded into local state on mount
- **WHEN** the page mounts with a valid `flowId`
- **THEN** `GET /api/job-runs?job_id=:flowId` is called and results are stored in component state

#### Scenario: Refresh re-fetches runs
- **WHEN** the user clicks Refresh in the runs table toolbar
- **THEN** `GET /api/job-runs?job_id=:flowId` is called again

### Requirement: Run metrics tiles
The page SHALL compute and display six run-count metrics from the local run list: total, successful (`run`), in-progress, run with issues, failed, and cancelled. Metrics SHALL update reactively when the run list changes.

#### Scenario: Metrics computed from run list
- **WHEN** runs are loaded
- **THEN** `FlowMetrics` receives counts for each status category

### Requirement: Runs content states
The content zone SHALL show an `ErrorEmptyState` when the runs fetch fails, a `NoDataEmptyState` when there are no runs and loading has settled (i.e. `runsLoading` is false and `runs.length === 0`), and the `FlowMetrics` + `FlowRunsTable` combination otherwise. When a manual Refresh is triggered while existing rows are present, the table remains visible and `FlowRunsTable` renders its own loading state via the `isLoading` prop — no top-level loading skeleton is shown in this page.

#### Scenario: Error state on fetch failure
- **WHEN** the runs fetch fails
- **THEN** `ErrorEmptyState` is shown with a "Try again" action

#### Scenario: Empty state when no runs
- **WHEN** the runs fetch resolves with zero runs
- **THEN** `NoDataEmptyState` is shown with a message directing the user to the canvas

### Requirement: Cancel in-progress run
The page SHALL allow the user to cancel an in-progress run. After the cancel API call completes (success or failure), the run list SHALL be re-fetched so the status reflects the terminal state.

#### Scenario: Cancel triggers run list refresh
- **WHEN** the user cancels a run
- **THEN** `cancelJobRun` is called and the runs are re-fetched on completion

### Requirement: Delete run
The page SHALL allow the user to delete a run via a confirmation modal. On success the run SHALL be removed from local state. On failure an error toast SHALL be shown.

#### Scenario: Delete removes run from local state
- **WHEN** the user confirms run deletion
- **THEN** `deleteJobRun` is called and the run row is removed from local state

#### Scenario: Delete failure shows error toast
- **WHEN** `deleteJobRun` fails
- **THEN** an error toast is shown and the row remains

### Requirement: View run navigates to run details
The page SHALL allow the user to navigate to the run details (read-only canvas viewer) for any run in the table.

#### Scenario: View run navigates to run details page
- **WHEN** the user clicks "View run" for a run
- **THEN** the router navigates to `/flows/:flow_id/runs/:run_id`

### Requirement: View flow navigates to canvas
The page SHALL provide a "View flow" button that navigates to the canvas editor for the current flow.

#### Scenario: View flow button navigates to canvas
- **WHEN** the user clicks "View flow"
- **THEN** the router navigates to the canvas for this flow with the `project_id` query param

### Requirement: Flow info side panel with breadcrumb injection
The page SHALL inject an ⓘ icon button into the breadcrumb bar that toggles `FlowInfoPanel`. The button's selected state SHALL reflect whether the panel is open. Breadcrumb actions SHALL be cleared on unmount.

#### Scenario: Info button toggles panel
- **WHEN** the user clicks the ⓘ breadcrumb button
- **THEN** `FlowInfoPanel` opens; clicking again closes it

#### Scenario: Breadcrumb actions cleared on unmount
- **WHEN** the flow detail page unmounts
- **THEN** breadcrumb actions are set to null

### Requirement: Edit flow details
The page SHALL allow the user to edit the flow's name, description, and tags via `EditDetailsModal` (opened from `FlowInfoPanel`). On save, `PATCH /api/flows/:id` SHALL be called and both the Redux flows store and `currentFlow` (if it matches) SHALL be updated optimistically so the canvas reflects the new name without a re-fetch.

#### Scenario: Edit updates flows store and currentFlow
- **WHEN** the user saves flow edits
- **THEN** `PATCH /api/flows/:id` is called, `updateFlow` and (if applicable) `setCurrentFlow` are dispatched

### Requirement: Recently-visited recording
The page SHALL record the flow as recently visited in the localStorage LRU list once the flow name is available, using the flow detail route as the path. Recording SHALL occur only once per flow ID per mount.

#### Scenario: Flow recorded on first load
- **WHEN** the flow name becomes available
- **THEN** an entry is added to the recently-visited LRU list for that flow

### Requirement: Loading spinner while flow resolves
The page SHALL show a spinner (`InlineLoading`) while the flow bootstrap fetch is in-flight or before a redirect fires.

#### Scenario: Spinner shown before flow resolves
- **WHEN** the flow is not yet in the store
- **THEN** an `InlineLoading` spinner is displayed
