# Spec Delta

## ADDED Requirements

### Requirement: Permission-gated flow actions
The create, edit and delete flow actions SHALL be disabled with an explanatory tooltip when the user lacks `editor`. Edit and delete SHALL also be disabled for a flow owned by another user unless the user is `admin`. A flow with no owner SHALL be actionable by any editor.

#### Scenario: Viewer cannot create a flow
- **WHEN** a viewer opens a project detail page
- **THEN** the create-flow action is disabled with a tooltip

#### Scenario: Editor and foreign flow
- **WHEN** an editor views a flow created by another user
- **THEN** edit and delete for that flow are disabled with a tooltip
