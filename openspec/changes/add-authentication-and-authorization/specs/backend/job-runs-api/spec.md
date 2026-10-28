# Spec Delta

## MODIFIED Requirements

### Requirement: Create and start a job run
`POST /api/v1/job_runs` SHALL require the `editor` role and SHALL create a new job run from a `JobsAPIExecuteModel` request body and immediately start execution asynchronously. When called by an authenticated user with auth enabled, `user_id` on the created job run SHALL be set from the authenticated caller's username (overriding any client-supplied `entity.job_run.configuration.user_id`). When auth is disabled or the service is invoked without an actor, `user_id` SHALL fall back to `entity.job_run.configuration.user_id` (or `None`). The response status SHALL be 201 with a `JobRunCreateResponse` containing `job_run_id` and `status="Starting"`. Internal failures SHALL return 500.

#### Scenario: Job run created and started
- **WHEN** `POST /api/v1/job_runs` is called by an `editor` with a valid body referencing an existing flow
- **THEN** the response is 201 with a `job_run_id` UUID, `status="Starting"`, and `user_id` recorded as the caller's username

#### Scenario: Viewer cannot create a job run
- **WHEN** `POST /api/v1/job_runs` is called by a `viewer`
- **THEN** the response is 403 and no job run is created

#### Scenario: Creation failure returns 500
- **WHEN** `POST /api/v1/job_runs` is called and an internal error occurs
- **THEN** the response is 500 with an `ErrorResponse`

### Requirement: List job runs with filters
`GET /api/v1/job_runs` SHALL return a `JobRunListResponse` with a `list` array of job run summaries (including `user_id` for each run). Optional query parameters `job_id` (UUID, filter by flow), `status` (filter by `ExecutionStatus`), and `limit` (default 100) SHALL narrow results. The response SHALL also include `count` (items returned) and `total` (total matching records).

#### Scenario: List filtered by job_id
- **WHEN** `GET /api/v1/job_runs?job_id={flow_id}` is called
- **THEN** only job runs for that flow are returned, including each run's `user_id`

#### Scenario: List filtered by status
- **WHEN** `GET /api/v1/job_runs?status=Completed` is called
- **THEN** only runs with status `Completed` are returned

#### Scenario: Limit respected
- **WHEN** `GET /api/v1/job_runs?limit=5` is called and 20 runs exist
- **THEN** `count` is 5 and `total` is 20

### Requirement: Cancel a running job
`POST /api/v1/job_runs/{job_run_id}/cancel` SHALL request cancellation of a running job run. It SHALL be allowed only to the user who created the job run (`user_id`), to any `admin`, or to any `editor` when the job run has no `user_id`, and SHALL return 403 otherwise. The response status SHALL be 202 with a `JobRunCancelResponse` containing `status="Canceling"`. The cancellation is asynchronous — the caller must poll the status endpoint to observe the terminal `Cancelled` state. An unknown `job_run_id` SHALL return 404.

#### Scenario: Cancel accepted with 202
- **WHEN** `POST /api/v1/job_runs/{job_run_id}/cancel` is called by the run's creator or an `admin` for an active run
- **THEN** the response is 202 with `status="Canceling"` and a confirmation message

#### Scenario: Cancel by non-owner editor returns 403
- **WHEN** `POST /api/v1/job_runs/{job_run_id}/cancel` is called by an `editor` who did not create the run
- **THEN** the response is 403 and the run continues executing

#### Scenario: Cancel on unknown run returns 404
- **WHEN** `POST /api/v1/job_runs/{unknown_id}/cancel` is called
- **THEN** the response is 404

### Requirement: Delete a job run record
`DELETE /api/v1/job_runs/{job_run_id}` SHALL permanently delete the job run record and its associated data. It SHALL be allowed only to the user who created the job run (`user_id`), to any `admin`, or to any `editor` when the job run has no `user_id`, and SHALL return 403 otherwise. The response SHALL be 204 with no body. An unknown `job_run_id` SHALL return 404.

#### Scenario: Delete succeeds with 204
- **WHEN** `DELETE /api/v1/job_runs/{job_run_id}` is called by the run's creator or an `admin` for an existing run
- **THEN** the response is 204 and the run is no longer retrievable

#### Scenario: Delete by non-owner editor returns 403
- **WHEN** `DELETE /api/v1/job_runs/{job_run_id}/delete` (`DELETE /api/v1/job_runs/{job_run_id}`) is called by an `editor` who did not create the run
- **THEN** the response is 403 and the run remains

#### Scenario: Unknown run returns 404
- **WHEN** `DELETE /api/v1/job_runs/{unknown_id}` is called
- **THEN** the response is 404
