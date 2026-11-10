# Spec Delta

## ADDED Requirements

### Requirement: Permission-gated home page creation actions
The sample project quick-start action and the create-project actions on `ProjectsCard` (header button and empty-state CTA) SHALL be disabled with an explanatory tooltip when the user lacks `editor`. The documentation link tile and read navigation to existing projects, flows and runs SHALL remain enabled for all authenticated users.

#### Scenario: Viewer cannot start sample project or create project from home
- **WHEN** a viewer opens the home page
- **THEN** the sample project button and `ProjectsCard` create-project actions are disabled with a tooltip explaining the missing permission

#### Scenario: Editor can start sample project and create project from home
- **WHEN** an editor opens the home page
- **THEN** the sample project button and `ProjectsCard` create-project actions are enabled
