# Spec Delta

## Purpose

The projects-page capability is the top-level projects list that lets users view, create, edit, delete, and navigate to all their projects from a single table page.

## ADDED Requirements

### Requirement: Three render states
The page SHALL render exactly one of three states at a time: a loading skeleton (while the initial fetch is in-flight), an empty state (when the list is empty and loading has settled), or a data table. The loading state SHALL use a skeleton shaped like the final toolbar and table to avoid layout shift.

#### Scenario: Skeleton during initial load
- **WHEN** the projects fetch is in-flight on mount
- **THEN** `ProjectsTable` renders a `DataTableSkeleton` and no empty-state or error UI is shown

#### Scenario: Empty state when no projects
- **WHEN** the fetch resolves with zero projects
- **THEN** `NoDataEmptyState` is shown with a "Create Project" action button

#### Scenario: Table when projects exist
- **WHEN** the fetch resolves with one or more projects
- **THEN** `ProjectsTable` renders with the project rows

---

### Requirement: Error state with retry
The page SHALL show an `ErrorEmptyState` with a "Try again" action when the projects fetch fails. Clicking "Try again" SHALL clear the error and re-fetch.

#### Scenario: Error state on fetch failure
- **WHEN** `GET /api/projects` returns an error
- **THEN** `ErrorEmptyState` is shown with the error message

#### Scenario: Retry clears error and re-fetches
- **WHEN** the user clicks "Try again"
- **THEN** the error is cleared and `GET /api/projects` is called again

---

### Requirement: Fetch projects on mount
The page SHALL fetch the full project list from `GET /api/projects` on mount, map responses to domain objects, and write them to the Redux projects store.

#### Scenario: Projects loaded into store on mount
- **WHEN** the page mounts
- **THEN** `GET /api/projects` is called and the results are stored in Redux

---

### Requirement: Create project with optional initial flow
The page SHALL allow the user to create a new project via `CreateProjectTearsheet`. If the tearsheet's optional flow name is filled in, the page SHALL also create a flow via `POST /api/flows` (with `container_id` set to the new project's ID) and navigate directly to the canvas for that flow. If no flow name is provided, the page SHALL navigate to the new project's detail page.

#### Scenario: Project-only creation navigates to project detail
- **WHEN** the user submits the tearsheet with a project name but no flow name
- **THEN** `POST /api/projects` is called, the project is added to the store, and the router navigates to the project detail page

#### Scenario: Project + flow creation navigates to canvas
- **WHEN** the user submits the tearsheet with both a project name and a flow name
- **THEN** `POST /api/projects` and `POST /api/flows` are both called and the router navigates to the new flow's canvas

#### Scenario: Create failure shows error
- **WHEN** `POST /api/projects` fails
- **THEN** an error is dispatched to the store and an error toast is shown; the tearsheet stays open

---

### Requirement: Edit project
The page SHALL allow the user to edit a project's name, description, and tags via `PUT /api/projects/:id`. On success the store SHALL be updated immediately without a full re-fetch.

#### Scenario: Edit updates store without re-fetch
- **WHEN** the user saves an edit
- **THEN** `PUT /api/projects/:id` is called and `setProject` is dispatched with the updated project

---

### Requirement: Delete project
The page SHALL allow the user to delete a project. On success the row SHALL be removed from the store immediately. On failure an error toast SHALL be shown.

#### Scenario: Delete removes row immediately
- **WHEN** the user confirms deletion
- **THEN** `DELETE /api/projects/:id` is called and `removeProject` is dispatched

#### Scenario: Delete failure shows toast
- **WHEN** `DELETE /api/projects/:id` fails
- **THEN** an error toast is shown and the row remains in the table

---

### Requirement: Manual refresh
The page SHALL provide a Refresh control that re-fetches the full project list from `GET /api/projects`.

#### Scenario: Refresh re-fetches projects
- **WHEN** the user clicks Refresh
- **THEN** `GET /api/projects` is called and the table updates with the latest data

---

### Requirement: Navigate to project
Clicking a project row SHALL navigate the user to that project's detail page.

#### Scenario: Row click navigates to project detail
- **WHEN** the user opens a project row
- **THEN** the router navigates to `/projects/:projectId`
