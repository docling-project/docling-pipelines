# Spec Delta

## MODIFIED Requirements

### Requirement: Authentication required on all endpoints
When `DOCPIPE_AUTH_ENABLED` is `true`, both endpoints SHALL require a valid session cookie or JWT bearer token. Requests without a valid session or with an invalid/expired token SHALL return 401. When `DOCPIPE_AUTH_ENABLED` is `false`, requests without credentials SHALL be evaluated as the reserved local principal. The authenticated user's `username` is extracted from the session and used exclusively to build the ACL filter. It is never passed as a query parameter.

#### Scenario: Missing token returns 401
- **WHEN** `DOCPIPE_AUTH_ENABLED` is `true` and `GET /api/v1/documents/{document_id}` is called without a session cookie or bearer token
- **THEN** the response is 401

#### Scenario: Invalid token returns 401
- **WHEN** `DOCPIPE_AUTH_ENABLED` is `true` and `POST /api/v1/documents/search` is called with an expired or malformed JWT
- **THEN** the response is 401

#### Scenario: Cookie session accepted
- **WHEN** `GET /api/v1/documents/{document_id}` is called with a valid session cookie for a user listed in `allowed_users`
- **THEN** the response is 200

## ADDED Requirements

### Requirement: Local principal and the document ACL
The `allowed_users` filter SHALL treat the reserved local principal explicitly. When auth is disabled, the local principal SHALL see every document, because no real user identity exists. When auth is enabled, the reserved username SHALL never match any `allowed_users` entry and no login can produce it.

#### Scenario: Auth disabled sees all documents
- **WHEN** `DOCPIPE_AUTH_ENABLED` is `false` and `GET /api/v1/documents/{document_id}` is called for a document whose `allowed_users` lists other users
- **THEN** the response is 200

#### Scenario: Reserved name matches no ACL entry
- **WHEN** `DOCPIPE_AUTH_ENABLED` is `true` and a document lists the reserved username in `allowed_users`
- **THEN** no caller is granted access through that entry
