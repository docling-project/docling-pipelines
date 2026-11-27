# Spec Delta

## MODIFIED Requirements

### Requirement: Full replace flow (PUT)
`PUT /api/v1/flows/{flow_id}` SHALL fully replace the mutable fields of an existing flow. The same `is_elyra` format dispatch as `POST` applies. The `flow_id` in the path SHALL override any ID in the body. On success the response SHALL be 200. Unknown flow SHALL return 404. Invalid data SHALL return 400. A `name` that differs from the stored name and is already used by another flow SHALL return 409; an unchanged `name` SHALL NOT be treated as a duplicate.

#### Scenario: Full replace succeeds
- **WHEN** `PUT /api/v1/flows/{flow_id}` is called with a complete valid body
- **THEN** the response is 200 with the updated flow and a refreshed `modified_on` timestamp

#### Scenario: Unknown flow returns 404
- **WHEN** `PUT /api/v1/flows/{unknown_id}` is called
- **THEN** the response is 404

#### Scenario: Rename to an existing name returns 409
- **WHEN** `PUT /api/v1/flows/{flow_id}` is called with a `name` that another flow already uses
- **THEN** the response is 409 with an `ErrorResponse` whose `errors[0].code` is `"conflict"` and the stored flow is unchanged

#### Scenario: Unchanged name is accepted
- **WHEN** `PUT /api/v1/flows/{flow_id}` is called with the flow's current `name`
- **THEN** the response is 200

### Requirement: Partial update flow (PATCH)
`PATCH /api/v1/flows/{flow_id}` SHALL apply only the fields present in the request body, leaving all other fields unchanged. The same `is_elyra` format dispatch applies. On success the response SHALL be 200 with the complete updated flow. A `name` that differs from the stored name and is already used by another flow SHALL return 409; an unchanged `name`, or a body without `name`, SHALL NOT be treated as a duplicate.

#### Scenario: Partial update changes only supplied fields
- **WHEN** `PATCH /api/v1/flows/{flow_id}` is called with only `{"tags": ["new-tag"]}`
- **THEN** the response is 200, `tags` is updated, and `name` and `definition` are unchanged

#### Scenario: Unknown flow returns 404
- **WHEN** `PATCH /api/v1/flows/{unknown_id}` is called
- **THEN** the response is 404

#### Scenario: Rename to an existing name returns 409
- **WHEN** `PATCH /api/v1/flows/{flow_id}` is called with a `name` that another flow already uses
- **THEN** the response is 409 with an `ErrorResponse` whose `errors[0].code` is `"conflict"` and the stored flow is unchanged

#### Scenario: Unchanged name is accepted
- **WHEN** `PATCH /api/v1/flows/{flow_id}` is called with the flow's current `name`
- **THEN** the response is 200
