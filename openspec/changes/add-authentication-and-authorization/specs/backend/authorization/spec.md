# Spec Delta

## Purpose

The authorization capability defines the roles, the role-per-endpoint permission matrix, ownership rules for assets and the audit trail of denials and writes, applied after a caller is authenticated.

## ADDED Requirements

### Requirement: Role model
Every authenticated caller SHALL hold one or more of the roles `viewer`, `editor` and `admin`, ordered `viewer` < `editor` < `admin`, where each role includes the rights of those below it. Roles SHALL be carried in the session and returned by `GET /auth/me`.

#### Scenario: Roles ordered
- **WHEN** a route requires `editor`
- **THEN** callers with `editor` or `admin` pass and callers with only `viewer` receive 403

#### Scenario: Roles in session
- **WHEN** a user logs in
- **THEN** their roles are present in `GET /auth/me`

### Requirement: Group-to-role mapping
Roles SHALL be derived from OIDC `groups` or `roles` claims and from LDAP `memberOf` values through a configurable mapping of group identifiers to roles. A caller matching no mapping SHALL receive `viewer`. A caller matching several SHALL receive the highest.

#### Scenario: Mapped group grants role
- **WHEN** a user belongs to a group mapped to `editor`
- **THEN** the user's roles include `editor`

#### Scenario: Unmapped user is viewer
- **WHEN** a user belongs to no mapped group
- **THEN** the user's role is `viewer`

#### Scenario: Highest role wins
- **WHEN** a user belongs to groups mapped to `editor` and `admin`
- **THEN** the user is treated as `admin`

### Requirement: Read access for viewers
Callers with `viewer` SHALL be able to call every `GET` route under `/api/v1/`, plus the read-only `POST /api/v1/documents/search`, `POST /api/v1/validation/validate_flow` and `POST /api/v1/validation/enrich_flow_features`.

#### Scenario: Viewer reads
- **WHEN** a viewer calls `GET /api/v1/projects`
- **THEN** the response is 200

#### Scenario: Viewer validates a flow
- **WHEN** a viewer calls `POST /api/v1/validation/validate_flow`
- **THEN** the response is not 403

### Requirement: Write access for editors
Creating, updating, deleting and running assets through `POST`, `PUT`, `PATCH` or `DELETE` on flows, projects, event mappings, job runs, documents, document sets, document libraries and document classes SHALL require `editor`.

#### Scenario: Viewer cannot write
- **WHEN** a viewer calls `POST /api/v1/flows`
- **THEN** the response is 403 and nothing is created

#### Scenario: Editor can run a flow
- **WHEN** an editor calls `POST /api/v1/job_runs`
- **THEN** the request is processed

### Requirement: Administrator-only operations
Uploading, updating and deleting custom operators SHALL require `admin`, because they run arbitrary code. Reading custom operators SHALL remain available to `viewer`.

#### Scenario: Editor cannot upload operator
- **WHEN** an editor calls `POST /api/v1/custom_operators`
- **THEN** the response is 403

#### Scenario: Admin uploads operator
- **WHEN** an admin uploads a valid operator
- **THEN** the response is 201

### Requirement: Asset ownership
When a flow or project is created by an authenticated caller, its `created_by` SHALL be set to that caller's username. When it is updated by an authenticated caller, its `modified_by` SHALL be set to that caller's username. Updating or deleting it SHALL be allowed to its creator and to any `admin`, and refused with 403 to other `editor`s. An asset with no `created_by` SHALL be modifiable by any `editor`. Deleting a project SHALL also verify that every child flow in the project may be deleted by the caller before deleting any flow or the project.

#### Scenario: Owner edits
- **WHEN** an editor updates a flow they created
- **THEN** the update succeeds

#### Scenario: Other editor refused
- **WHEN** an editor deletes a flow created by another user
- **THEN** the response is 403 and the flow remains

#### Scenario: Admin overrides
- **WHEN** an admin deletes any flow
- **THEN** the delete succeeds

#### Scenario: Ownerless asset
- **WHEN** an editor updates a flow whose `created_by` is empty
- **THEN** the update succeeds

#### Scenario: Auth disabled leaves owner empty
- **WHEN** a flow is created while auth is disabled
- **THEN** its `created_by` is empty

### Requirement: Bulk operations honor ownership
A bulk delete of flows SHALL check ownership for each flow. Flows the caller may not delete SHALL be reported as failures and SHALL remain, without preventing deletion of the others.

#### Scenario: Mixed bulk delete
- **WHEN** an editor bulk-deletes two own flows and one flow owned by another user
- **THEN** the two own flows are deleted and the third is reported as refused

### Requirement: Non-API callers are unaffected
The command-line interface and the Python library SHALL continue to operate without an authenticated caller, and ownership checks SHALL NOT block them.

#### Scenario: CLI deletes an owned flow
- **WHEN** a flow is deleted through the library without an actor
- **THEN** the delete succeeds regardless of `created_by`

### Requirement: Audit of denials and writes
Every authorization denial and every successful create, update and delete under `/api/v1/` SHALL be written to the audit log with the username, action, target and outcome. Passwords and tokens SHALL NOT be logged.

#### Scenario: Denial logged
- **WHEN** a request is refused with 403
- **THEN** an audit entry records the user, the action, the target and the denial

#### Scenario: Write logged
- **WHEN** an editor creates a project
- **THEN** an audit entry records the user and the new project id
