# backend/projects-api Specification

## Purpose

The projects-api capability is the REST API surface for project management. It lets callers create, retrieve, list, fully replace, partially update, and delete projects. It also provides a dedicated sub-resource endpoint that lists all flows belonging to a project, each enriched with aggregated job-run status, without returning flow definitions.

## Requirements

### Requirement: Create project
`POST /api/v1/projects` SHALL create and persist a new project with a generated UUID `project_id`. The response status SHALL be 201 with a `ProjectResponse` whose `flow_count` is 0. A duplicate project name SHALL return 409. Invalid request data SHALL return 400.

#### Scenario: Project created successfully
- **WHEN** `POST /api/v1/projects` is called with a valid `ProjectCreateRequest` body
- **THEN** the response is 201 with a `ProjectResponse` containing a generated `project_id` and `flow_count=0`

#### Scenario: Duplicate name returns 409
- **WHEN** `POST /api/v1/projects` is called with a `name` that already exists
- **THEN** the response is 409

#### Scenario: Missing name returns 400
- **WHEN** `POST /api/v1/projects` is called without a `name` field
- **THEN** the response is 400 with a validation error identifying the `name` field

### Requirement: List projects with pagination and filtering
`GET /api/v1/projects` SHALL return a paginated list of projects. Query parameters `limit` (default 100), `offset` (default 0), `name` (case-insensitive partial match), and `tags` (any-match) SHALL filter results. The response SHALL include `total_count`, `first`, `next`, and `prev` pagination links.

#### Scenario: List returns all projects
- **WHEN** `GET /api/v1/projects` is called with no filters
- **THEN** the response is 200 with a `PaginatedProjectResponse` containing all projects and correct `total_count`

#### Scenario: Name filter is case-insensitive partial match
- **WHEN** `GET /api/v1/projects?name=invoice` is called
- **THEN** only projects whose name contains "invoice" (case-insensitive) are returned

#### Scenario: Tags filter is any-match
- **WHEN** `GET /api/v1/projects?tags=finance&tags=ml` is called
- **THEN** only projects carrying at least one of `finance` or `ml` as a tag are returned

#### Scenario: Pagination links generated correctly
- **WHEN** `GET /api/v1/projects?offset=10&limit=10` is called and there are 25 total projects
- **THEN** `next` points to `offset=20&limit=10` and `prev` points to `offset=0&limit=10`

### Requirement: Get project by ID
`GET /api/v1/projects/{project_id}` SHALL retrieve a single project by its UUID. The response SHALL include the current `flow_count`. An unknown `project_id` SHALL return 404. An invalid UUID format SHALL return 400.

#### Scenario: Known project returned
- **WHEN** `GET /api/v1/projects/{project_id}` is called for an existing project
- **THEN** the response is 200 with a `ProjectResponse` including `flow_count`

#### Scenario: Unknown project returns 404
- **WHEN** `GET /api/v1/projects/{unknown_id}` is called
- **THEN** the response is 404 with `errors[0].code = "not_found"`

#### Scenario: Malformed UUID returns 400
- **WHEN** `GET /api/v1/projects/not-a-uuid` is called
- **THEN** the response is 400

### Requirement: Full replace project (PUT)
`PUT /api/v1/projects/{project_id}` SHALL fully replace a project's mutable fields (`name`, `description`, `tags`). Immutable fields (`project_id`, `created_on`, `created_by`) SHALL be preserved from the existing record. The response SHALL be 200 with the updated project. Unknown project SHALL return 404.

#### Scenario: Full replace preserves immutable fields
- **WHEN** `PUT /api/v1/projects/{project_id}` is called with a new `name`
- **THEN** the response is 200, `name` is updated, and `project_id` and `created_on` are unchanged

#### Scenario: Unknown project returns 404
- **WHEN** `PUT /api/v1/projects/{unknown_id}` is called
- **THEN** the response is 404

### Requirement: Partial update project (PATCH)
`PATCH /api/v1/projects/{project_id}` SHALL apply only the fields present in the request body, leaving all other fields unchanged. On success the response SHALL be 200 with the complete updated project.

#### Scenario: Partial update changes only supplied fields
- **WHEN** `PATCH /api/v1/projects/{project_id}` is called with only `{"tags": ["new-tag"]}`
- **THEN** the response is 200, `tags` is updated, and `name` and `description` are unchanged

### Requirement: Delete project with cascade
`DELETE /api/v1/projects/{project_id}` SHALL delete the project and cascade-delete all flows whose `container_id` matches the `project_id`. Individual flow deletion failures SHALL be logged as warnings but SHALL NOT block the project deletion. On success the response SHALL be 204 with no body. Unknown project SHALL return 404.

#### Scenario: Project and its flows deleted
- **WHEN** `DELETE /api/v1/projects/{project_id}` is called for a project with associated flows
- **THEN** the response is 204 and neither the project nor its flows are retrievable

#### Scenario: Flow deletion failure does not block project deletion
- **WHEN** `DELETE /api/v1/projects/{project_id}` is called and a flow deletion fails internally
- **THEN** the response is still 204 and the project is deleted; the failure is logged

#### Scenario: Unknown project returns 404
- **WHEN** `DELETE /api/v1/projects/{unknown_id}` is called
- **THEN** the response is 404

### Requirement: List project flows with run summary
`GET /api/v1/projects/{project_id}/flows` SHALL return a paginated list of flows scoped to the project, each enriched with metadata, tags, and execution `job_run_summary` (or null if never run) while omitting flow definitions.

#### Scenario: Flows returned with run summary
- **WHEN** `GET /api/v1/projects/{project_id}/flows` is called for a project with executed flows
- **THEN** each flow item includes `job_run_summary.total_runs`, `last_run_status`, and `status_counts`

#### Scenario: Never-executed flow has null summary
- **WHEN** `GET /api/v1/projects/{project_id}/flows` returns a flow that has never been run
- **THEN** `job_run_summary` is `null` for that flow

#### Scenario: Flow definition excluded from response
- **WHEN** `GET /api/v1/projects/{project_id}/flows` is called
- **THEN** no `definition` or `pipelines` field is present in any flow item

#### Scenario: Unknown project returns 404
- **WHEN** `GET /api/v1/projects/{unknown_id}/flows` is called
- **THEN** the response is 404
