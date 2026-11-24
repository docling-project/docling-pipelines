# Spec Delta

## ADDED Requirements

### Requirement: Permission-gated run and edit actions
Cancelling a run and deleting a run SHALL be disabled with an explanatory tooltip when the user lacks `editor` or when the run was created by another user (`user_id`) and the user is not `admin`. Editing flow details SHALL be disabled with an explanatory tooltip when the user lacks `editor` or when the flow is owned by another user (`created_by`) and the user is not `admin`.

#### Scenario: Viewer cannot cancel or delete a run
- **WHEN** a viewer opens a flow with job runs
- **THEN** the cancel and delete actions are disabled with a tooltip

#### Scenario: Editor cannot cancel or delete another user's run
- **WHEN** an editor opens a flow containing a job run created by another user
- **THEN** the cancel and delete actions for that run are disabled with a tooltip

#### Scenario: Run owner or admin can cancel and delete
- **WHEN** the editor who created a run (or an admin) opens the flow detail page
- **THEN** the cancel and delete actions for that run are enabled

#### Scenario: Editor edits own flow details
- **WHEN** an editor opens a flow they created
- **THEN** the edit-details action is enabled

#### Scenario: Viewing runs stays available
- **WHEN** a viewer opens the flow detail page
- **THEN** the run list, metrics and view-run navigation remain available
