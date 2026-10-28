# Spec Delta

## ADDED Requirements

### Requirement: Permission-gated run and edit actions
Cancelling a run, deleting a run and editing flow details SHALL be disabled with an explanatory tooltip when the user lacks `editor`. Editing flow details SHALL also be disabled for a flow owned by another user unless the user is `admin`.

#### Scenario: Viewer cannot cancel a run
- **WHEN** a viewer opens a flow with an in-progress run
- **THEN** the cancel action is disabled with a tooltip

#### Scenario: Editor edits own flow details
- **WHEN** an editor opens a flow they created
- **THEN** the edit-details action is enabled

#### Scenario: Viewing runs stays available
- **WHEN** a viewer opens the flow detail page
- **THEN** the run list, metrics and view-run navigation remain available
