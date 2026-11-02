# backend/job-runs-api Specification

## Purpose

The job-runs-api capability is the REST API surface for job run lifecycle management. It lets callers create and start pipeline runs, poll their execution status with per-node statistics, cancel in-progress runs, delete run records, download a CSV report of document-level results, and retrieve the exact flow definition snapshot that was used for a given run.

## Requirements

### Requirement: Create and start a job run
`POST /api/v1/job_runs` SHALL create a new job run from a `JobsAPIExecuteModel` request body and immediately start execution asynchronously. The response status SHALL be 201 with a `JobRunCreateResponse` containing `job_run_id` and `status="Starting"`. Internal failures SHALL return 500.

#### Scenario: Job run created and started
- **WHEN** `POST /api/v1/job_runs` is called with a valid body referencing an existing flow
- **THEN** the response is 201 with a `job_run_id` UUID and `status="Starting"`

#### Scenario: Creation failure returns 500
- **WHEN** `POST /api/v1/job_runs` is called and an internal error occurs
- **THEN** the response is 500 with an `ErrorResponse`

### Requirement: List job runs with filters
`GET /api/v1/job_runs` SHALL return a `JobRunListResponse` with a `list` array of job run summaries. Optional query parameters `job_id` (UUID, filter by flow), `status` (filter by `ExecutionStatus`), and `limit` (default 100) SHALL narrow results. The response SHALL also include `count` (items returned) and `total` (total matching records).

#### Scenario: List filtered by job_id
- **WHEN** `GET /api/v1/job_runs?job_id={flow_id}` is called
- **THEN** only job runs for that flow are returned

#### Scenario: List filtered by status
- **WHEN** `GET /api/v1/job_runs?status=Completed` is called
- **THEN** only runs with status `Completed` are returned

#### Scenario: Limit respected
- **WHEN** `GET /api/v1/job_runs?limit=5` is called and 20 runs exist
- **THEN** `count` is 5 and `total` is 20

### Requirement: Get job run status and node statistics
`GET /api/v1/job_runs/{job_run_id}` SHALL return a `JobRunStatusResponse` containing `job_stats` (overall run metadata and per-node `node_stats`), `node_sequence` (ordered node execution list), and `node_metadata` (per-node document counts). When `include_logs=true` the response SHALL also include per-node execution log strings keyed by node ID. An unknown `job_run_id` SHALL return 404.

#### Scenario: Status returned with node stats
- **WHEN** `GET /api/v1/job_runs/{job_run_id}` is called for a running or completed run
- **THEN** the response is 200 with `job_stats.status`, `node_stats` per node, and `node_sequence`

#### Scenario: Logs included when requested
- **WHEN** `GET /api/v1/job_runs/{job_run_id}?include_logs=true` is called
- **THEN** the response includes per-node log strings in addition to the standard fields

#### Scenario: Logs excluded by default
- **WHEN** `GET /api/v1/job_runs/{job_run_id}` is called without `include_logs`
- **THEN** no per-node log strings are present in the response

#### Scenario: Unknown job run returns 404
- **WHEN** `GET /api/v1/job_runs/{unknown_id}` is called
- **THEN** the response is 404 with `errors[0].code = "not_found"`

### Requirement: Cancel a running job
`POST /api/v1/job_runs/{job_run_id}/cancel` SHALL request cancellation of a running job run. The response status SHALL be 202 with a `JobRunCancelResponse` containing `status="Canceling"`. The cancellation is asynchronous — the caller must poll the status endpoint to observe the terminal `Cancelled` state. An unknown `job_run_id` SHALL return 404.

#### Scenario: Cancel accepted with 202
- **WHEN** `POST /api/v1/job_runs/{job_run_id}/cancel` is called for an active run
- **THEN** the response is 202 with `status="Canceling"` and a confirmation message

#### Scenario: Cancel on unknown run returns 404
- **WHEN** `POST /api/v1/job_runs/{unknown_id}/cancel` is called
- **THEN** the response is 404

### Requirement: Delete a job run record
`DELETE /api/v1/job_runs/{job_run_id}` SHALL permanently delete the job run record and its associated data. The response SHALL be 204 with no body. An unknown `job_run_id` SHALL return 404.

#### Scenario: Delete succeeds with 204
- **WHEN** `DELETE /api/v1/job_runs/{job_run_id}` is called for an existing run
- **THEN** the response is 204 and the run is no longer retrievable

#### Scenario: Unknown run returns 404
- **WHEN** `DELETE /api/v1/job_runs/{unknown_id}` is called
- **THEN** the response is 404

### Requirement: Download job run CSV report
`GET /api/v1/job_runs/{job_run_id}/report` SHALL return a CSV file download containing document-level processing details for a completed run. The CSV SHALL include columns: `GUID`, `File name`, `Status`, `Status reason`, `Time stamp`, `Pages`, and `Processing time (in seconds)`. Requesting a report for a run that has not yet completed SHALL return 425. An unknown run SHALL return 404.

#### Scenario: Completed run returns CSV download
- **WHEN** `GET /api/v1/job_runs/{job_run_id}/report` is called for a completed run
- **THEN** the response is 200 with `Content-Type: text/csv` and a CSV body with the required columns

#### Scenario: In-progress run returns 425
- **WHEN** `GET /api/v1/job_runs/{job_run_id}/report` is called for a run still in progress
- **THEN** the response is 425 with `errors[0].code = "too_early"`

#### Scenario: Unknown run returns 404
- **WHEN** `GET /api/v1/job_runs/{unknown_id}/report` is called
- **THEN** the response is 404

### Requirement: Get flow definition snapshot for a run
`GET /api/v1/job_runs/{job_run_id}/flow_definition` SHALL return the exact flow definition (in compiled DAG format) that was used when the job run was created. This snapshot is captured at run creation time for audit and reproducibility. An unknown `job_run_id` SHALL return 404. A run for which no snapshot was saved SHALL return 404.

#### Scenario: Snapshot returned as JSON
- **WHEN** `GET /api/v1/job_runs/{job_run_id}/flow_definition` is called for a run with a saved snapshot
- **THEN** the response is 200 with the flow definition JSON that was active at run time

#### Scenario: Missing snapshot returns 404
- **WHEN** `GET /api/v1/job_runs/{job_run_id}/flow_definition` is called for a run with no saved snapshot
- **THEN** the response is 404 with `errors[0].code = "not_found"`
