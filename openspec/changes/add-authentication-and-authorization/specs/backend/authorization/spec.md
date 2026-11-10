# Spec Delta

## Purpose

The authorization capability defines the roles, the role-per-endpoint permission matrix, ownership rules for assets and the audit trail of denials and writes, applied after a caller is authenticated.

## ADDED Requirements

### Requirement: Role model
Every authenticated caller SHALL hold a set of roles drawn from `viewer`, `editor` and `admin`, ordered `viewer` < `editor` < `admin`. The effective role is the highest one in the set, and it includes the rights of those below it. Roles SHALL be carried in the session and returned by `GET /auth/me`.

#### Scenario: Roles ordered
- **WHEN** a route requires `editor`
- **THEN** callers with `editor` or `admin` pass and callers with only `viewer` receive 403

#### Scenario: Roles in session
- **WHEN** a user logs in
- **THEN** their roles are present in `GET /auth/me`

### Requirement: Group-to-role mapping
Roles SHALL be derived from OIDC `groups` or `roles` claims and from LDAP `memberOf` values through a configurable mapping of group identifiers to roles. A caller matching no mapping SHALL receive `viewer`. A caller matching several SHALL receive the highest. Group identifiers SHALL be compared as exact strings after trimming whitespace, and LDAP distinguished names SHALL be compared case-insensitively.

#### Scenario: Mapped group grants role
- **WHEN** a user belongs to a group mapped to `editor`
- **THEN** the user's roles include `editor`

#### Scenario: Unmapped user is viewer
- **WHEN** a user belongs to no mapped group
- **THEN** the user's role is `viewer`

#### Scenario: Highest role wins
- **WHEN** a user belongs to groups mapped to `editor` and `admin`
- **THEN** the user is treated as `admin`

#### Scenario: LDAP group name case
- **WHEN** an LDAP `memberOf` value differs from the mapped distinguished name only in letter case
- **THEN** the mapping matches

### Requirement: Group claim limits
The API SHALL log at startup which claim and attribute it reads for groups. A provider that sends no group claim, such as Google, or that omits groups on overage, such as Azure with many groups, SHALL leave the user with `viewer`. Only the bootstrap administrator can promote such a user, and the setup guide SHALL state this. Nested LDAP groups are not expanded.

#### Scenario: Provider without groups
- **WHEN** a user logs in through a provider that returns no group claim
- **THEN** the user holds `viewer`

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

### Requirement: Ownership is recorded from the session
When a flow or project is created by an authenticated caller, its `created_by` SHALL be set to that caller's username. When a job run is created by an authenticated caller, its `user_id` SHALL be set to that caller's username. When a flow or project is updated by an authenticated caller, its `modified_by` SHALL be set to that caller's username, and the server SHALL ignore any `modified_by` value in the request body.

#### Scenario: Creator recorded
- **WHEN** an editor creates a flow
- **THEN** the flow's `created_by` is the editor's username

#### Scenario: Client-supplied modifier ignored
- **WHEN** an editor updates a flow and sends another user's name as `modified_by`
- **THEN** the stored `modified_by` is the editor's username

#### Scenario: Auth disabled leaves owner empty
- **WHEN** a flow is created while auth is disabled
- **THEN** its `created_by` is empty

### Requirement: Ownership limits modification
Updating or deleting a flow or project, or cancelling or deleting a job run, SHALL be allowed to its creator (`created_by` / `user_id`) and to any `admin`, and refused with 403 to other `editor`s. An asset or job run with no owner SHALL be modifiable by any `editor`, until an operator backfills the owner.

#### Scenario: Owner edits
- **WHEN** an editor updates a flow they created
- **THEN** the update succeeds

#### Scenario: Other editor refused
- **WHEN** an editor deletes a flow or cancels/deletes a job run created by another user
- **THEN** the response is 403 and the resource remains

#### Scenario: Admin overrides
- **WHEN** an admin deletes any flow or cancels/deletes any job run
- **THEN** the operation succeeds

#### Scenario: Ownerless asset
- **WHEN** an editor updates a flow whose `created_by` is empty
- **THEN** the update succeeds

### Requirement: Project delete checks child flows first
Deleting a project SHALL verify that the caller may delete the project and every child flow before deleting anything. The check and the cascade are not atomic, so a flow created in the project between them can be deleted, and the design records this as accepted.

#### Scenario: Foreign child flow blocks delete
- **WHEN** an editor deletes their own project that contains a flow owned by another user
- **THEN** the response is 403 and nothing is deleted

### Requirement: Bulk operations honor ownership
A bulk delete of flows SHALL check ownership for each flow. Flows the caller may not delete SHALL be reported as failures and SHALL remain, without preventing deletion of the others. The failure entry SHALL give a generic permission reason and SHALL NOT name the flow's owner.

#### Scenario: Mixed bulk delete
- **WHEN** an editor bulk-deletes two own flows and one flow owned by another user
- **THEN** the two own flows are deleted and the third is reported as refused without the other user's name

### Requirement: Non-API callers are unaffected
The command-line interface and the Python library SHALL continue to operate without an authenticated caller, and ownership checks SHALL NOT block them.

#### Scenario: CLI deletes an owned flow
- **WHEN** a flow is deleted through the library without an actor
- **THEN** the delete succeeds regardless of `created_by`

### Requirement: Audit of denials and writes
Every authorization denial and every successful create, update and delete under `/api/v1/` SHALL be written to the audit log with the username, action, target and outcome. Failures other than 403, such as 404 and 409 on a write, SHALL be logged with the same fields and the status code. Usernames and targets that come from untrusted sources SHALL have newlines and control characters removed before logging. Passwords and tokens SHALL NOT be logged.

#### Scenario: Denial logged
- **WHEN** a request is refused with 403
- **THEN** an audit entry records the user, the action, the target and the denial

#### Scenario: Failed write logged
- **WHEN** an editor updates a flow that does not exist and gets 404
- **THEN** an audit entry records the user, the action, the target and the status code

#### Scenario: Newline in username sanitised
- **WHEN** a username from an external directory contains a newline
- **THEN** the audit entry contains no newline

#### Scenario: Write logged
- **WHEN** an editor creates a project
- **THEN** an audit entry records the user and the new project id

### Requirement: Backend is the authority
Hiding or disabling an action in the UI SHALL be a convenience only. The REST API SHALL enforce every role and ownership rule, and each action that the UI hides SHALL have a backend test that expects 403.

#### Scenario: Hidden action still refused
- **WHEN** a viewer sends a request that the UI would not offer
- **THEN** the response is 403
