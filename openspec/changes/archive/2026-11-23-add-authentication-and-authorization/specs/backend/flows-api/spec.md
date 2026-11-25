# Spec Delta

## ADDED Requirements

### Requirement: Flow ownership on write
When auth is enabled, creating a flow SHALL record the caller as `created_by`, and updating it SHALL record the caller as `modified_by`. Replacing, partially updating or deleting a flow SHALL be refused with 403 for an `editor` who is not the creator, unless the flow has no creator. Callers holding `viewer` only SHALL receive 403 on every flow write. `admin` SHALL be allowed to modify any flow.

#### Scenario: Create records creator
- **WHEN** an editor creates a flow with auth enabled
- **THEN** the returned flow has `created_by` equal to the editor's username

#### Scenario: Other editor cannot update
- **WHEN** an editor sends `PUT` or `PATCH` for a flow created by someone else
- **THEN** the response is 403 with `errors[0].code = "forbidden"` and the flow is unchanged

#### Scenario: Other editor cannot delete
- **WHEN** an editor sends `DELETE` for a flow created by someone else
- **THEN** the response is 403 and the flow remains

#### Scenario: Viewer cannot write
- **WHEN** a viewer calls `POST /api/v1/flows`
- **THEN** the response is 403

### Requirement: Bulk delete reports refused flows
`DELETE` bulk flow deletion SHALL check ownership per flow. Flows the caller may not delete SHALL be listed as failed with a permission reason and SHALL NOT stop the remaining flows from being deleted.

#### Scenario: Partial bulk delete
- **WHEN** an editor bulk-deletes flows where one belongs to another user
- **THEN** that flow is reported failed and the others are deleted
