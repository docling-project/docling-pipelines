# Spec Delta

## MODIFIED Requirements

### Requirement: Authentication required on all endpoints
When `DOCPIPE_AUTH_ENABLED` is `true`, both endpoints SHALL require a valid session cookie or JWT bearer token. Requests without a valid session or with an invalid/expired token SHALL return 401. When `DOCPIPE_AUTH_ENABLED` is `false`, requests without credentials SHALL be evaluated as the synthetic local administrator (`admin`). The authenticated user's `username` is extracted from the session and used exclusively to build the ACL filter — it is never passed as a query parameter.

#### Scenario: Missing token returns 401
- **WHEN** `DOCPIPE_AUTH_ENABLED` is `true` and `GET /api/v1/documents/{document_id}` is called without a session cookie or bearer token
- **THEN** the response is 401

#### Scenario: Invalid token returns 401
- **WHEN** `DOCPIPE_AUTH_ENABLED` is `true` and `POST /api/v1/documents/search` is called with an expired or malformed JWT
- **THEN** the response is 401

#### Scenario: Cookie session accepted
- **WHEN** `GET /api/v1/documents/{document_id}` is called with a valid session cookie for a user listed in `allowed_users`
- **THEN** the response is 200
