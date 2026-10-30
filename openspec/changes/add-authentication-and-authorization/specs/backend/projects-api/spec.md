# Spec Delta

## ADDED Requirements

### Requirement: Project ownership on write
When auth is enabled, creating a project SHALL record the caller as `created_by`, and updating it SHALL record the caller as `modified_by`. Replacing, partially updating or deleting a project SHALL be refused with 403 for an `editor` who is not the creator, unless the project has no creator. `viewer` SHALL receive 403 on every project write, and `admin` SHALL be allowed to modify or delete any project.

#### Scenario: Create records creator
- **WHEN** an editor creates a project with auth enabled
- **THEN** the returned project has `created_by` equal to the editor's username

#### Scenario: Other editor cannot update
- **WHEN** an editor sends `PUT` or `PATCH` for a project created by someone else
- **THEN** the response is 403 with `errors[0].code = "forbidden"` and the project is unchanged

#### Scenario: Other editor cannot delete
- **WHEN** an editor deletes a project created by someone else
- **THEN** the response is 403 and neither the project nor its flows are deleted

### Requirement: Project delete checks child flows
Deleting a project SHALL be refused with 403 before any cascade deletion occurs if any flow inside the project is owned by another user and the caller is not `admin`.

#### Scenario: Project delete refused when child flow belongs to another user
- **WHEN** an editor deletes their own project that contains a flow created by another user
- **THEN** the response is 403 and neither the project nor any of its flows are deleted

#### Scenario: Admin deletes any project
- **WHEN** an admin deletes a project created by another user
- **THEN** the project and its flows are deleted as before
