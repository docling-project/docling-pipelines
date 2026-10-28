# Spec Delta

## ADDED Requirements

### Requirement: Credentialed requests
The shared `apiClient` SHALL send the browser's cookies with every request and SHALL attach `X-Requested-With: XMLHttpRequest` to every state-changing request, including authentication calls.

#### Scenario: Cookies sent
- **WHEN** any request is dispatched through `apiClient`
- **THEN** credentials are included

#### Scenario: Mutation carries CSRF header
- **WHEN** a `POST`, `PUT`, `PATCH` or `DELETE` is dispatched
- **THEN** it carries `X-Requested-With: XMLHttpRequest`

### Requirement: Single redirect on session expiry
A 401 response from any request other than login and the initial `/auth/me` probe SHALL clear the auth state and navigate to `/login` carrying the current path as `return_to`. When several requests fail with 401 at once, the redirect SHALL happen exactly once.

#### Scenario: Expired session
- **WHEN** a request returns 401 while the user is on a flow page
- **THEN** the user is sent to `/login?return_to=<that page>`

#### Scenario: Concurrent failures
- **WHEN** three in-flight requests all return 401
- **THEN** only one navigation to `/login` occurs

#### Scenario: Login failure not redirected
- **WHEN** `POST /api/auth/login` returns 401
- **THEN** no redirect occurs and the login page shows the error

### Requirement: Permission denied feedback
A 403 response SHALL show an error toast stating that the user lacks permission for the action and SHALL NOT sign the user out.

#### Scenario: Forbidden action
- **WHEN** a delete returns 403
- **THEN** a toast "You do not have permission to perform this action" is shown and the session is kept
