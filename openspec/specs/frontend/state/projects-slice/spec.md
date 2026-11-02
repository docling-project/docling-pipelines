# frontend/state/projects-slice Specification

## Purpose
The projects-slice is the Redux slice that manages project entity state. It maintains a `items` map of `Project` domain models keyed by project ID, tracks the currently selected project ID for navigation, and provides actions for CRUD lifecycle management.

## Requirements

### Requirement: Projects items map
The slice SHALL maintain a map of `Project` objects keyed by project ID.

#### Scenario: setProjects replaces the map and clears loading
- **WHEN** setProjects is dispatched with a record of projects
- **THEN** state.items is replaced, state.loading is false, and state.error is null

#### Scenario: setProject upserts a single project
- **WHEN** setProject is dispatched with a projectId and Project
- **THEN** that entry is inserted or updated in state.items

#### Scenario: removeProject deletes an entry
- **WHEN** removeProject is dispatched with a projectId
- **THEN** that project is removed from state.items

### Requirement: Selected project cleared on deletion
The slice SHALL clear `selectedProjectId` when the currently selected project is removed.

#### Scenario: selectedProjectId nulled when deleted project was selected
- **WHEN** removeProject is dispatched with the currently selectedProjectId
- **THEN** state.selectedProjectId is set to null

### Requirement: Loading and error state
The slice SHALL track a loading flag and error string for async operations.

#### Scenario: setLoading updates loading flag
- **WHEN** setLoading is dispatched with true
- **THEN** state.loading is true

#### Scenario: setError stores the error message
- **WHEN** setError is dispatched with an error string
- **THEN** state.error is set to that string
