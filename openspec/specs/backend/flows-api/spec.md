# backend/flows-api Specification

## Purpose

The flows-api capability is the REST API surface for flow management. It lets callers create, retrieve, list, update, partially update, delete, and bulk-delete pipeline flow definitions. It supports two wire formats — Elyra (UI canvas format) and Authoring (human-readable DAG JSON) — controlled by an `is_elyra` query parameter, and returns paginated responses with navigation links.

## Requirements

### Requirement: Create flow
`POST /api/v1/flows` SHALL create and persist a new flow definition. When `is_elyra=true` the body SHALL be validated as `ElyraFlowCreateRequest`; otherwise it SHALL be validated as `AuthoringFlowCreateRequest` and the authoring format SHALL be structurally validated before storage. A UUID `flow_id` SHALL be generated and returned. On success the response status SHALL be 201. A duplicate name SHALL return 409. Invalid request data SHALL return 400.

#### Scenario: Elyra flow created successfully
- **WHEN** `POST /api/v1/flows?is_elyra=true` is called with a valid Elyra pipeline body
- **THEN** the response is 201 with a `FlowResponse` containing a generated `flow_id`

#### Scenario: Authoring flow created successfully
- **WHEN** `POST /api/v1/flows` is called with a valid authoring-format body (default `is_elyra=false`)
- **THEN** the response is 201 with an `AuthoringFlowResponse` containing a generated `flow_id`

#### Scenario: Duplicate name returns 409
- **WHEN** `POST /api/v1/flows` is called with a `name` that already exists
- **THEN** the response is 409 with an `ErrorResponse` whose `errors[0].code` is `"conflict"`

#### Scenario: Invalid body returns 400
- **WHEN** `POST /api/v1/flows` is called with a missing required field (e.g. no `flow_name`)
- **THEN** the response is 400 with an `ErrorResponse` listing the offending field

### Requirement: Get flow by ID
`GET /api/v1/flows/{flow_id}` SHALL retrieve a single flow by its UUID. The response format (Authoring vs Elyra) SHALL be detected from the stored definition: if `flow_name` is present at the top level it is Authoring format; otherwise it is Elyra format. A non-existent flow SHALL return 404. An invalid UUID format SHALL return 400.

#### Scenario: Authoring flow returned in authoring format
- **WHEN** `GET /api/v1/flows/{flow_id}` is called for a flow stored in authoring format
- **THEN** the response is 200 with an `AuthoringFlowResponse` (flat structure with `flow_name`)

#### Scenario: Elyra flow returned in Elyra format
- **WHEN** `GET /api/v1/flows/{flow_id}` is called for a flow stored in Elyra format
- **THEN** the response is 200 with a `FlowResponse` (wrapped structure with `definition.pipelines`)

#### Scenario: Unknown ID returns 404
- **WHEN** `GET /api/v1/flows/{flow_id}` is called with a UUID that does not exist
- **THEN** the response is 404 with `errors[0].code = "not_found"`

#### Scenario: Malformed UUID returns 400
- **WHEN** `GET /api/v1/flows/not-a-uuid` is called
- **THEN** the response is 400 with `errors[0].code = "validation_error"`

### Requirement: List flows with pagination and filtering
`GET /api/v1/flows` SHALL return a paginated list of flows. Query parameters `limit` (default 100, max 1000), `offset` (default 0), `name` (partial match), `tags` (any-match), and `is_hidden` SHALL filter results. `is_elyra=true` SHALL return only Elyra-format flows in a `PaginatedFlowResponse`; `is_elyra=false` or omitted SHALL return only authoring-format flows in a `PaginatedAuthoringFlowResponse`. The response SHALL include `total_count`, `first`, `next`, and `prev` pagination links.

#### Scenario: Default list returns authoring flows
- **WHEN** `GET /api/v1/flows` is called with no parameters
- **THEN** the response is 200 with a `PaginatedAuthoringFlowResponse` containing only authoring-format flows

#### Scenario: is_elyra=true returns only Elyra flows
- **WHEN** `GET /api/v1/flows?is_elyra=true` is called
- **THEN** the response is 200 with a `PaginatedFlowResponse` containing only Elyra-format flows

#### Scenario: Name filter applied
- **WHEN** `GET /api/v1/flows?name=invoice` is called
- **THEN** only flows whose name contains "invoice" (partial match) are returned

#### Scenario: Pagination links generated
- **WHEN** `GET /api/v1/flows?offset=0&limit=10` returns 10 items out of 25 total
- **THEN** `next` points to `?offset=10&limit=10` and `prev` is null

#### Scenario: Out-of-range limit returns 400
- **WHEN** `GET /api/v1/flows?limit=9999` is called
- **THEN** the response is 400

### Requirement: Full replace flow (PUT)
`PUT /api/v1/flows/{flow_id}` SHALL fully replace the mutable fields of an existing flow. The same `is_elyra` format dispatch as `POST` applies. The `flow_id` in the path SHALL override any ID in the body. On success the response SHALL be 200. Unknown flow SHALL return 404. Invalid data SHALL return 400.

#### Scenario: Full replace succeeds
- **WHEN** `PUT /api/v1/flows/{flow_id}` is called with a complete valid body
- **THEN** the response is 200 with the updated flow and a refreshed `modified_on` timestamp

#### Scenario: Unknown flow returns 404
- **WHEN** `PUT /api/v1/flows/{unknown_id}` is called
- **THEN** the response is 404

### Requirement: Partial update flow (PATCH)
`PATCH /api/v1/flows/{flow_id}` SHALL apply only the fields present in the request body, leaving all other fields unchanged. The same `is_elyra` format dispatch applies. On success the response SHALL be 200 with the complete updated flow.

#### Scenario: Partial update changes only supplied fields
- **WHEN** `PATCH /api/v1/flows/{flow_id}` is called with only `{"tags": ["new-tag"]}`
- **THEN** the response is 200, `tags` is updated, and `name` and `definition` are unchanged

#### Scenario: Unknown flow returns 404
- **WHEN** `PATCH /api/v1/flows/{unknown_id}` is called
- **THEN** the response is 404

### Requirement: Delete flow
`DELETE /api/v1/flows/{flow_id}` SHALL permanently delete the flow and CASCADE delete all associated job runs. On success the response SHALL be 204 with no body. Unknown flow SHALL return 404.

#### Scenario: Delete succeeds with 204
- **WHEN** `DELETE /api/v1/flows/{flow_id}` is called for an existing flow
- **THEN** the response is 204 and the flow is no longer retrievable

#### Scenario: Associated job runs deleted on flow delete
- **WHEN** `DELETE /api/v1/flows/{flow_id}` is called for a flow that has existing job runs
- **THEN** all job runs associated with that flow are also permanently deleted

#### Scenario: Unknown flow returns 404
- **WHEN** `DELETE /api/v1/flows/{unknown_id}` is called
- **THEN** the response is 404

### Requirement: Bulk delete flows
`DELETE /api/v1/flows?flow_ids=id1,id2,…` SHALL delete multiple flows in one request. The `flow_ids` parameter SHALL be a comma-separated list of UUIDs. The response SHALL be 200 with a `BulkDeleteResponse` containing `deleted`, `failed`, `total_requested`, `total_deleted`, and `total_failed`. Individual flow failures SHALL NOT abort the operation for other flows.

#### Scenario: Mixed success and failure reported
- **WHEN** `DELETE /api/v1/flows?flow_ids=existing-id,missing-id` is called
- **THEN** the response is 200 with `total_deleted=1`, `total_failed=1`, and `failed[0].error` describing the failure

#### Scenario: Empty flow_ids returns 400
- **WHEN** `DELETE /api/v1/flows?flow_ids=` is called
- **THEN** the response is 400 with a validation error

### Requirement: Error response format
All error responses SHALL conform to the `ErrorResponse` schema: a JSON object with `errors` (list of objects with `code`, `message`, and optional `target`), `trace` (request trace ID), and `status_code`. The `trace` field SHALL match the `X-Transaction-ID` request header when present.

#### Scenario: Error response includes trace ID
- **WHEN** any request that produces an error includes an `X-Transaction-ID` header
- **THEN** the `ErrorResponse.trace` field matches that header value
