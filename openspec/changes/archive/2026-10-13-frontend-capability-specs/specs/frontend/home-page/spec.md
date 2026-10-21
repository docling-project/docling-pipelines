# Spec Delta

## ADDED Requirements

### Requirement: Recent-work card data and navigation
The `ProjectsCard`, `FlowsCard`, and `RunsCard` on the home page SHALL render the most recent items (up to 5 each), displaying item title, modification timestamp, status badges, and empty-state placeholders when no items exist, navigating directly to the selected item upon clicking.

#### Scenario: Clicking card item navigates to detail view
- **WHEN** the user clicks an item inside `ProjectsCard` or `FlowsCard`
- **THEN** the router navigates to `/projects/:id` or `/flows/:id` respectively

#### Scenario: Empty card renders placeholder and call-to-action
- **WHEN** no projects or flows exist in the system
- **THEN** the corresponding card displays an empty state message and a creation action button

### Requirement: Sample project bootstrap workflow
The `SampleProjectModal` triggered from the quick-start tiles SHALL provision a pre-configured sample project and starter pipeline flow, closing the modal and navigating directly to the generated project upon successful creation.

#### Scenario: Sample project creation initializes starter pipeline
- **WHEN** the user confirms sample project creation in the modal
- **THEN** the system generates the sample project with example flows, displays a success notification, and navigates to the project view
