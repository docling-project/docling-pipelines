# Spec Delta

## ADDED Requirements

### Requirement: Permission-gated project actions
The create, edit and delete project actions SHALL be disabled with an explanatory tooltip when the user lacks `editor`. Edit and delete SHALL also be disabled for a project owned by another user unless the user is `admin`. A project with no owner SHALL be actionable by any editor.

#### Scenario: Viewer sees disabled actions
- **WHEN** a viewer opens the projects page
- **THEN** create, edit and delete are disabled and the tooltip explains the missing permission

#### Scenario: Editor and foreign project
- **WHEN** an editor views a project created by another user
- **THEN** edit and delete for that project are disabled with a tooltip naming ownership

#### Scenario: Admin acts on any project
- **WHEN** an admin views any project
- **THEN** edit and delete are enabled
