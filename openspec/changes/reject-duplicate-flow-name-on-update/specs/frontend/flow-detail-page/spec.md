# Spec Delta

## ADDED Requirements

### Requirement: Duplicate flow name validation on edit
The `EditDetailsModal` on the page SHALL be given the names of the other flows in the same project and SHALL reject a duplicate name (trimmed, case-insensitive) with an inline error. A 409 response from `PATCH /api/flows/:id` SHALL be shown through the same inline error.

#### Scenario: Rename to a sibling flow's name is rejected
- **WHEN** the user renames the flow to the name of another flow in the same project and saves
- **THEN** an inline duplicate-name error is shown and `PATCH /api/flows/:id` is not called

#### Scenario: Duplicate detected on blur
- **WHEN** the name field loses focus with the name of another flow in the same project
- **THEN** the inline duplicate-name error is shown and Save is disabled

#### Scenario: Saving without a rename is allowed
- **WHEN** the user saves without changing the name
- **THEN** `PATCH /api/flows/:id` is called and no duplicate-name error is shown

#### Scenario: Backend 409 shown inline
- **WHEN** `PATCH /api/flows/:id` returns 409
- **THEN** the inline duplicate-name error is shown and the modal stays open
