# Spec Delta

## MODIFIED Requirements

### Requirement: Edit flow
The page SHALL allow the user to edit a flow's name, description, and tags via `PATCH /api/flows/:id`. On success the Redux store SHALL be updated optimistically. The edit modal SHALL reject a name used by another flow listed on the page (trimmed, case-insensitive) with an inline error without calling `PATCH`, and a 409 from `PATCH` SHALL be shown through the same inline error instead of the generic failure toast.

#### Scenario: Edit updates store optimistically
- **WHEN** the user saves an edit
- **THEN** `PATCH /api/flows/:id` is called and `updateFlow` is dispatched

#### Scenario: Rename to an existing flow name is rejected
- **WHEN** the user renames a flow to the name of another listed flow and saves
- **THEN** an inline duplicate-name error is shown and `PATCH /api/flows/:id` is not called

#### Scenario: Backend 409 shown inline
- **WHEN** `PATCH /api/flows/:id` returns 409
- **THEN** the inline duplicate-name error is shown and no failure toast is displayed
