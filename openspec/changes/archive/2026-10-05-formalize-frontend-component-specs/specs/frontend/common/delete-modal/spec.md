# common/delete-modal Specification

## Purpose

The delete-modal-component is the reusable confirmation modal for all destructive delete actions in the application. It presents the asset type and name to the user, manages a loading state internally while the delete operation is in flight, and closes only after the operation resolves.

## ADDED Requirements

### Requirement: Confirmation copy with asset name
The modal SHALL display the asset type in the heading and the asset name in bold in the body.

#### Scenario: Heading and body show asset details
- **WHEN** the modal opens for a flow named "My Flow"
- **THEN** the heading reads "Delete Flow" and the body shows "My Flow" in bold

### Requirement: Loading state on delete
The modal SHALL show a loading indicator on the Delete button while the delete operation is in progress and disable both buttons to prevent double submission.

#### Scenario: Buttons disabled during delete
- **WHEN** the user clicks Delete
- **THEN** both Cancel and Delete buttons are disabled and the Delete button shows a loading indicator

### Requirement: Modal stays open on error
The modal SHALL remain open if the delete operation fails, allowing the user to retry or cancel.

#### Scenario: Modal stays open on failure
- **WHEN** the onDelete Promise rejects
- **THEN** the modal remains open and buttons are re-enabled

### Requirement: Cancel closes without deleting
The modal SHALL call onCancel when the user clicks Cancel or the modal close icon, without triggering a delete.

#### Scenario: Cancel does not delete
- **WHEN** the user clicks Cancel
- **THEN** onCancel is called and onDelete is not called

### Requirement: Click outside does not close
The modal SHALL NOT close when the user clicks outside it, preventing accidental dismissal during a destructive action.

#### Scenario: Outside click ignored
- **WHEN** the user clicks outside the modal while it is open
- **THEN** the modal remains open
