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

#### Scenario: Logout carries CSRF header
- **WHEN** the SPA calls `POST /auth/logout`
- **THEN** the request carries `X-Requested-With: XMLHttpRequest`

### Requirement: Authentication calls go to the REST API origin
The SPA SHALL call `/auth/*` on the origin that serves it and SHALL NOT call `/api/auth/*`. The OIDC provider buttons SHALL use the `authorize_url` that `GET /auth/config` returns for each provider.

#### Scenario: Login path
- **WHEN** the SPA submits the login form
- **THEN** it posts to `/auth/login`

### Requirement: Vite dev server proxies authentication routes
`frontend/vite.config.ts` SHALL proxy `/auth` to the REST API. The target SHALL be `BACKEND_API_URL`, read with `loadEnv`, and SHALL be `http://localhost:8080` when the variable is unset or empty. The proxy SHALL apply to `vite preview` unless `preview.proxy` is set.

#### Scenario: Default target
- **WHEN** `BACKEND_API_URL` is unset and the dev server receives `GET /auth/config`
- **THEN** the request is forwarded to `http://localhost:8080/auth/config`

#### Scenario: Configured target
- **WHEN** `BACKEND_API_URL` is `http://localhost:9000`
- **THEN** `/auth` requests are forwarded to that address

#### Scenario: OIDC callback in development
- **WHEN** the identity provider redirects to `http://localhost:3000/auth/oauth2/callback`
- **THEN** the dev server forwards it to the REST API and the browser stays on port 3000 after the redirect

### Requirement: Single redirect on session expiry
A 401 response from any request other than login and the initial `/auth/me` probe SHALL clear the auth state and navigate to `/login` carrying the current path as `return_to`. When several requests fail with 401 at once, the redirect SHALL happen exactly once.

#### Scenario: Expired session
- **WHEN** a request returns 401 while the user is on a flow page
- **THEN** the user is sent to `/login?return_to=<that page>`

#### Scenario: Concurrent failures
- **WHEN** three in-flight requests all return 401
- **THEN** only one navigation to `/login` occurs

#### Scenario: Login failure not redirected
- **WHEN** `POST /auth/login` returns 401
- **THEN** no redirect occurs and the login page shows the error

### Requirement: Permission denied feedback
A 403 response SHALL show an error toast stating that the user lacks permission for the action and SHALL NOT sign the user out.

#### Scenario: Forbidden action
- **WHEN** a delete returns 403
- **THEN** a toast "You do not have permission to perform this action" is shown and the session is kept
