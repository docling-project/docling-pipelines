# Spec Delta

## ADDED Requirements

### Requirement: Get document set data card
`GET /api/v1/document-sets/{document_set_id}/data-card` SHALL return the data card of the document set as a `DataCardResponse` with status 200. A document set that has no card SHALL return 200 with every descriptive field null and `flows` empty. An unknown `document_set_id` SHALL return 404. An invalid UUID format SHALL return 400.

#### Scenario: Card returned
- **WHEN** `GET /api/v1/document-sets/{document_set_id}/data-card` is called for a document set that has recorded runs
- **THEN** the response is 200 with the descriptive fields and the `flows` list of the card

#### Scenario: Document set without a card
- **WHEN** the endpoint is called for a document set that no run has written to
- **THEN** the response is 200, every descriptive field is null, and `flows` is an empty list

#### Scenario: Unknown ID returns 404
- **WHEN** the endpoint is called with an unknown document set ID
- **THEN** the response is 404

#### Scenario: Malformed UUID returns 400
- **WHEN** `GET /api/v1/document-sets/not-a-uuid/data-card` is called
- **THEN** the response is 400

### Requirement: Flow names refreshed on read
When a flow listed in the card still exists, `GET .../data-card` SHALL return its current flow name in place of the name recorded at run time. When the flow no longer exists, or the flow lookup fails, the recorded name SHALL be returned and the request SHALL still succeed. Reading SHALL NOT modify the stored card.

#### Scenario: Flow renamed
- **WHEN** a flow recorded as `old-name` has since been renamed to `new-name` and the card is read
- **THEN** the response shows `new-name` and the stored card still holds `old-name`

#### Scenario: Flow deleted
- **WHEN** a flow listed in the card has been deleted
- **THEN** the response shows the name recorded at run time

### Requirement: Update document set data card descriptive fields
`PATCH /api/v1/document-sets/{document_set_id}/data-card` SHALL update `purpose`, `summary`, `curator`, `language`, `collection_criteria`, and `propagate_source_acls`. A field that is omitted or null SHALL be left unchanged. On success the response SHALL be 200 with the complete updated `DataCardResponse`. An unknown `document_set_id` SHALL return 404.

#### Scenario: Purpose updated, rest unchanged
- **WHEN** the endpoint is called with only `{"purpose": "Support knowledge base"}`
- **THEN** the response is 200, `purpose` is updated, and every other field including `flows` is unchanged

#### Scenario: Card created on first update
- **WHEN** the endpoint is called for a document set that has no card
- **THEN** the response is 200 with a card holding the supplied fields and an empty `flows` list

#### Scenario: Unknown ID returns 404
- **WHEN** the endpoint is called with an unknown document set ID
- **THEN** the response is 404

#### Scenario: Survives later runs
- **WHEN** `purpose` is set through the endpoint and a later pipeline run records itself
- **THEN** the card still holds the `purpose` that was set

### Requirement: Data card flows are read-only over the API
The update endpoint SHALL NOT accept the `flows` section or any other unknown field. A request body that contains one SHALL return 400 and change nothing.

#### Scenario: Flows rejected
- **WHEN** the endpoint is called with a body that contains `flows`
- **THEN** the response is 400 and the stored card is unchanged

#### Scenario: Unknown field rejected
- **WHEN** the endpoint is called with a body that contains a field the card does not define
- **THEN** the response is 400 and the stored card is unchanged

### Requirement: Data card field limits
The request SHALL reject values that exceed these limits with status 400: `purpose`, `summary`, and `collection_criteria` up to 10000 characters each, `language` up to 64 characters, and `curator.id` and `curator.type` up to 256 characters each.

#### Scenario: Overlong purpose
- **WHEN** the endpoint is called with a `purpose` longer than 10000 characters
- **THEN** the response is 400 and the stored card is unchanged

### Requirement: Existing document set responses unchanged
Adding the data card routes SHALL NOT change the request or response shape of any existing document set route. `DocumentSetResponse` SHALL NOT include the data card.

#### Scenario: Get document set unchanged
- **WHEN** `GET /api/v1/document-sets/{document_set_id}` is called for a set that has a card
- **THEN** the response has the same fields as before and does not contain `data_card`
