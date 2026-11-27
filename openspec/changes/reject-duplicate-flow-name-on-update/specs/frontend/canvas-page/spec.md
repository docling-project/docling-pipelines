# Spec Delta

## ADDED Requirements

### Requirement: Duplicate flow name validation on edit
While `EditDetailsModal` is open, the page SHALL supply the names of the other flows in the current project for duplicate-name validation. A 409 from the save request SHALL be shown inline in the modal instead of the generic save-failure toast.

#### Scenario: Duplicate name rejected inline
- **WHEN** the user enters the name of another flow in the project in `EditDetailsModal`
- **THEN** an inline duplicate-name error is shown

#### Scenario: Backend 409 shown inline
- **WHEN** `PATCH /api/flows/:id` returns 409 from `EditDetailsModal`
- **THEN** the inline duplicate-name error is shown and no save-failure toast is displayed
