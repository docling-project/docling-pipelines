# backend/custom-operators-api Specification

## Purpose

The custom-operators-api capability is the REST API surface for managing user-supplied Python operator scripts. It allows callers to upload, list, retrieve, update, and delete custom operators that extend the pipeline's built-in operator catalog. Uploaded scripts are statically validated against the operator contract before storage. The file size limit is 512 KB per script. Only `.py` files are accepted.

## Requirements

### Requirement: Create custom operator via file upload
`POST /api/v1/custom_operators` SHALL accept a multipart form upload containing `name`, optional `description`, and a `.py` `operator_file`. The service SHALL statically validate the script against the operator contract and persist valid files up to 512 KB, returning 201 with a `FileUploadResponse`.

#### Scenario: Valid operator created and returns 201
- **WHEN** `POST /api/v1/custom_operators` is called with a valid `.py` file and name
- **THEN** the response is 201 with `success=true` and a generated `operator_id`

#### Scenario: Duplicate short_name returns 409
- **WHEN** `POST /api/v1/custom_operators` is called with a script whose `short_name` already exists
- **THEN** the response is 409

#### Scenario: File exceeding 512 KB returns 413
- **WHEN** `POST /api/v1/custom_operators` is called with a file larger than 512 KB
- **THEN** the response is 413

#### Scenario: Non-.py file returns 400
- **WHEN** `POST /api/v1/custom_operators` is called with a file that does not have a `.py` extension
- **THEN** the response is 400

#### Scenario: Operator contract violation returns 400
- **WHEN** `POST /api/v1/custom_operators` is called with a `.py` file that fails static validation
- **THEN** the response is 400

### Requirement: List all custom operators
`GET /api/v1/custom_operators` SHALL return a `CustomOperatorListResponse` with an `operators` array and a `count` field reflecting all registered custom operators in the catalog.

#### Scenario: All custom operators returned
- **WHEN** `GET /api/v1/custom_operators` is called
- **THEN** the response is 200 with `operators` listing all registered operators and `count` matching the array length

#### Scenario: Empty catalog returns empty list
- **WHEN** no custom operators have been created
- **THEN** the response is 200 with `operators=[]` and `count=0`

### Requirement: Get single custom operator by ID
`GET /api/v1/custom_operators/{operator_id}` SHALL return a `CustomOperatorResponse` for the matching UUID. An unknown ID SHALL return 404.

#### Scenario: Existing operator returned
- **WHEN** `GET /api/v1/custom_operators/{operator_id}` is called with a valid existing ID
- **THEN** the response is 200 with a `CustomOperatorResponse`

#### Scenario: Unknown ID returns 404
- **WHEN** `GET /api/v1/custom_operators/{unknown_id}` is called
- **THEN** the response is 404

### Requirement: Get directory tree of operator files
`GET /api/v1/custom_operators/directory_tree` SHALL return a `DirectoryTreeResponse` with a nested representation of all custom operator files stored on disk.

#### Scenario: Directory tree returned
- **WHEN** `GET /api/v1/custom_operators/directory_tree` is called
- **THEN** the response is 200 with a `DirectoryTreeResponse` reflecting the current file layout

### Requirement: Update custom operator metadata or script
`PATCH /api/v1/custom_operators/{operator_id}` SHALL accept an optional `name`, `description`, and/or replacement `operator_file`. At least one field must change. A replacement script SHALL be statically validated before the existing file is replaced. The `short_name` derived from the script SHALL NOT change between updates — attempting to change it SHALL return 400. Unknown operator SHALL return 404. File size and extension rules from create apply.

#### Scenario: Metadata-only update succeeds
- **WHEN** `PATCH /api/v1/custom_operators/{operator_id}` is called with only a new `name`
- **THEN** the response is 200 with `success=true`

#### Scenario: Script replacement succeeds after validation
- **WHEN** `PATCH /api/v1/custom_operators/{operator_id}` is called with a valid replacement `.py` file
- **THEN** the response is 200 with `success=true` and the stored script is replaced

#### Scenario: short_name change returns 400
- **WHEN** the replacement script has a different `short_name` than the stored operator
- **THEN** the response is 400

#### Scenario: Unknown operator returns 404
- **WHEN** `PATCH /api/v1/custom_operators/{unknown_id}` is called
- **THEN** the response is 404

### Requirement: Delete custom operator
`DELETE /api/v1/custom_operators/{operator_id}` SHALL permanently delete the custom operator record and its associated files from disk. On success the response SHALL be 200 with a `CustomOperatorDeleteResponse` containing `success=true`. Unknown operator SHALL return 404.

#### Scenario: Delete succeeds with 200
- **WHEN** `DELETE /api/v1/custom_operators/{operator_id}` is called for an existing operator
- **THEN** the response is 200 with `success=true` and the operator is no longer retrievable

#### Scenario: Unknown operator returns 404
- **WHEN** `DELETE /api/v1/custom_operators/{unknown_id}` is called
- **THEN** the response is 404
