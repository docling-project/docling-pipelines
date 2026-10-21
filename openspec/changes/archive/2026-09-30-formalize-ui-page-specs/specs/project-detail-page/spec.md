# Spec Delta

## Purpose

The project-detail-page capability displays a single project's metadata and its associated flows, letting users create, edit, delete, and navigate to flows within that project.

## ADDED Requirements

### Requirement: Route parameter
The page SHALL read `project_id` from the path parameter `/projects/:project_id` and use it for all data fetches and navigation.

#### Scenario: Project loaded by route param
- **WHEN** the user navigates to `/projects/abc`
- **THEN** project `abc` is used for all data operations

---

### Requirement: Project bootstrap fetch
The page SHALL fetch the project from `GET /api/projects/:id` only when the project is not already in the Redux store (deep link or page refresh). On a 404 response the page SHALL redirect to the error page with status 404. On any other error it SHALL redirect to the error page with status 500. On unmount the in-flight request SHALL be cancelled.

#### Scenario: No fetch when project is already in store
- **WHEN** the project is already in the Redux store on mount
- **THEN** `GET /api/projects/:id` is NOT called

#### Scenario: 404 redirects to error page
- **WHEN** `GET /api/projects/:id` returns 404
- **THEN** the router replaces the current history entry with the error page showing "Project not found."

#### Scenario: Other error redirects to error page
- **WHEN** `GET /api/projects/:id` returns a non-404 error
- **THEN** the router replaces with the error page showing a generic failure message

---

### Requirement: Flows fetch triggered by project availability
The page SHALL fetch flows for the project via `GET /api/flows?project_id=:id` as soon as the project is available in the store. The flows SHALL be stored in the Redux flows store. Navigating back to the same project SHALL reuse cached rows; the Refresh button triggers a full re-fetch.

#### Scenario: Flows fetched when project is available
- **WHEN** the project object becomes available in the store
- **THEN** `GET /api/flows?project_id=:id` is called and results are written to the Redux flows store

#### Scenario: Refresh triggers full re-fetch
- **WHEN** the user clicks Refresh in the flows table toolbar
- **THEN** `GET /api/flows?project_id=:id` is called again and the table updates

---

### Requirement: Flow count kept in sync
After each flows fetch completes, if the project's `flowCount` does not match the number of fetched flows, the page SHALL update `flowCount` in the Redux store to match the authoritative list.

#### Scenario: Flow count corrected after fetch
- **WHEN** the flows fetch completes and `project.flowCount !== flows.length`
- **THEN** `setProject` is dispatched with the corrected `flowCount`

---

### Requirement: Collapsible project header
The project header SHALL display the project name, description, creation date, last-updated date, flow count, and tags. The description and meta section SHALL be collapsible via a toggle chevron. Tags SHALL remain visible in both collapsed and expanded states.

#### Scenario: Header collapses on chevron click
- **WHEN** the user clicks the collapse chevron
- **THEN** the description and meta row is hidden and the chevron changes to expand

#### Scenario: Tags always visible
- **WHEN** the header is collapsed
- **THEN** project tags are still rendered

---

### Requirement: Flows content states
The content zone SHALL show `FlowsTable` with a skeleton while loading, `NoDataEmptyState` when there are no flows and loading has settled, and the full table when flows exist.

#### Scenario: Skeleton during flows load
- **WHEN** the flows fetch is in-flight
- **THEN** `FlowsTable` renders a skeleton

#### Scenario: Empty state when no flows
- **WHEN** flows fetch resolves with zero flows and loading is complete
- **THEN** `NoDataEmptyState` is shown with a "Create flow" action

---

### Requirement: Create flow
The page SHALL allow the user to create a new flow via `CreateFlowTearsheet`. On success the new flow SHALL be added to the Redux store and the router SHALL navigate to the canvas for the new flow.

#### Scenario: Flow creation navigates to canvas
- **WHEN** the user submits the create flow form with a valid name
- **THEN** `POST /api/flows` is called, the flow is added to the store, and the router navigates to the canvas

#### Scenario: Create failure shows inline error
- **WHEN** `POST /api/flows` fails
- **THEN** an inline error is shown inside the tearsheet and it stays open

---

### Requirement: Edit flow
The page SHALL allow the user to edit a flow's name, description, and tags via `PATCH /api/flows/:id`. On success the Redux store SHALL be updated optimistically.

#### Scenario: Edit updates store optimistically
- **WHEN** the user saves an edit
- **THEN** `PATCH /api/flows/:id` is called and `updateFlow` is dispatched

---

### Requirement: Delete flow
The page SHALL allow the user to delete a flow. On success the flow SHALL be removed from the store and the project `flowCount` SHALL be decremented. On failure an error toast SHALL be shown.

#### Scenario: Delete removes flow and decrements count
- **WHEN** the user confirms deletion
- **THEN** `DELETE /api/flows/:id` is called, `removeFlow` is dispatched, and `flowCount` is decremented

---

### Requirement: Navigate to flow canvas and run history
The page SHALL allow the user to open a flow's canvas (edit) and its run history from the flows table.

#### Scenario: Open flow navigates to canvas
- **WHEN** the user opens a flow from the table
- **THEN** the router navigates to the canvas for that flow

#### Scenario: Open runs navigates to flow detail
- **WHEN** the user selects "View runs" for a flow
- **THEN** the router navigates to the flow detail page

---

### Requirement: Recently-visited recording
The page SHALL record the project as recently visited in the localStorage LRU list once the project name is available, using the project detail route as the path. The entry SHALL be recorded only once per project ID per mount (not on every re-render or name change).

#### Scenario: Project recorded on first load
- **WHEN** the project name becomes available
- **THEN** an entry is added to the recently-visited LRU list for that project

---

### Requirement: Null render while project is loading
The page SHALL render nothing (`null`) while the project bootstrap fetch is in-flight, to avoid a spinner flash for this brief window.

#### Scenario: Nothing rendered before project is available
- **WHEN** the project is not yet in the store
- **THEN** the page renders null (no spinner, no layout)
