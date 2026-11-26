# frontend/common/flow-info-panel Specification

## Purpose
The flow-info-panel-component is the "About flow" side panel that slides in from the right on the FlowDetail page. It displays flow metadata (name, description, tags, creation date, modification date, project name) as a pure read-only view and provides navigation callbacks for viewing the flow on canvas, viewing the parent project, editing flow details, and closing the panel.

## Requirements

### Requirement: Read-only flow metadata display
The panel SHALL display all provided flow metadata fields without any editable inputs.

#### Scenario: Metadata fields visible when panel opens
- **WHEN** the panel opens with a flow object
- **THEN** the flow name, description, tags, created date, modified date, and project name are all visible

### Requirement: Navigation callbacks
The panel SHALL invoke the appropriate callback when the user interacts with the flow name link, project name link, or edit icon.

#### Scenario: Flow name click navigates to canvas
- **WHEN** the user clicks the flow name link
- **THEN** the onViewFlow callback is invoked

#### Scenario: Project name click navigates to project
- **WHEN** the user clicks the project name link
- **THEN** the onViewProject callback is invoked

#### Scenario: Edit icon opens edit modal
- **WHEN** the user clicks the edit (pencil) icon
- **THEN** the onEdit callback is invoked

### Requirement: Close button dismisses panel
The panel SHALL call the onClose callback when the user clicks the close (×) button.

#### Scenario: Close button calls onClose
- **WHEN** the user clicks the × button
- **THEN** the onClose callback is invoked

### Requirement: No internal state or API calls
The panel SHALL be a pure display component — it makes no API calls and holds no internal state.

#### Scenario: Panel renders with provided data only
- **WHEN** the panel mounts
- **THEN** it renders purely from the flow prop with no additional data fetching

### Requirement: Permission-gated edit details button
`FlowInfoPanel` SHALL disable or hide the edit (pencil) icon button with an explanatory tooltip when the caller cannot modify the flow (lacks `editor`, or the flow is owned by another user and the caller is not `admin`).

#### Scenario: Unauthorized caller views flow info panel
- **WHEN** a viewer or a non-owner editor opens `FlowInfoPanel`
- **THEN** the edit details button is disabled with a tooltip explaining the missing permission or ownership
