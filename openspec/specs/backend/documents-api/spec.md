# backend/documents-api Specification

## Purpose

The documents-api capability provides ACL-enforced access to documents stored in OpenSearch. It exposes two endpoints — a single-document retrieval by ID and a full-text search — both of which require a valid JWT token and automatically restrict results to documents for which the authenticated user is explicitly listed in the `allowed_users` field. The ACL filter is applied server-side and cannot be bypassed by the caller.

## Requirements

### Requirement: Authentication required on all endpoints
Both endpoints SHALL require a valid JWT bearer token. Requests without a token or with an invalid/expired token SHALL return 401. The authenticated user's `username` is extracted from the token and used exclusively to build the ACL filter — it is never passed as a query parameter.

#### Scenario: Missing token returns 401
- **WHEN** `GET /api/v1/documents/{document_id}` is called without a bearer token
- **THEN** the response is 401

#### Scenario: Invalid token returns 401
- **WHEN** `POST /api/v1/documents/search` is called with an expired or malformed JWT
- **THEN** the response is 401

### Requirement: Get document by ID with ACL enforcement
`GET /api/v1/documents/{document_id}` SHALL retrieve a single document from OpenSearch by ID, applying a server-side ACL filter requiring the user to be in `allowed_users` and returning 404 for missing or unauthorized documents to prevent information leakage.

#### Scenario: Authorised user retrieves document
- **WHEN** `GET /api/v1/documents/{document_id}` is called by a user who is listed in the document's `allowed_users`
- **THEN** the response is 200 with a `DocumentResponse` containing the document's content and metadata

#### Scenario: Unauthorised user receives 404 (not 403)
- **WHEN** `GET /api/v1/documents/{document_id}` is called by a user who is NOT in the document's `allowed_users`
- **THEN** the response is 404, identical to the "not found" response — the user cannot determine whether the document exists

#### Scenario: Non-existent document returns 404
- **WHEN** `GET /api/v1/documents/{document_id}` is called with an ID that does not exist in OpenSearch
- **THEN** the response is 404

#### Scenario: OpenSearch index unavailable returns 503
- **WHEN** the OpenSearch index does not exist or the service is unreachable
- **THEN** the response is 503 with `detail = "Document service unavailable"`

### Requirement: Search documents with ACL enforcement
`POST /api/v1/documents/search` SHALL execute ACL-restricted document searches across content and metadata in OpenSearch, supporting full-text queries, exact match filters, sorting, and pagination.

#### Scenario: Search returns only documents accessible to the user
- **WHEN** `POST /api/v1/documents/search` is called with a query that would match documents owned by other users
- **THEN** only documents where the authenticated user is in `allowed_users` are returned

#### Scenario: Full-text query filters results
- **WHEN** `POST /api/v1/documents/search` is called with `{"query": "machine learning"}`
- **THEN** only documents whose content, title, or metadata contain "machine learning" are returned (subject to ACL filter)

#### Scenario: Pagination respected
- **WHEN** `POST /api/v1/documents/search` is called with `{"limit": 10, "offset": 20}`
- **THEN** the response contains at most 10 documents starting from position 20, with `has_more` indicating whether further results exist

#### Scenario: Missing OpenSearch index returns empty results (not error)
- **WHEN** `POST /api/v1/documents/search` is called and the OpenSearch index does not exist
- **THEN** the response is 200 with `documents=[]`, `total=0`, and `has_more=false`

#### Scenario: Malformed search request returns 400
- **WHEN** `POST /api/v1/documents/search` is called with an invalid query structure (e.g. bad sort field)
- **THEN** the response is 400

#### Scenario: OpenSearch service error returns 503
- **WHEN** `POST /api/v1/documents/search` is called and OpenSearch returns an unexpected error
- **THEN** the response is 503 with `detail = "Document search service error"`
