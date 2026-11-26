# frontend/api-client Specification

## Purpose

The api-client capability defines the frontend-backend communication boundary, providing base URL resolution (BFF proxy vs direct API), structured request and response logging interceptors, action-encapsulated HTTP communication with BFF headers, and error propagation conventions.

## Requirements

### Requirement: Base URL and proxy resolution
The API client layer SHALL configure a shared Axios instance (`apiClient`) with a default timeout and JSON content-type header, targeting relative `/api/*` endpoints delegated to the BFF proxy.

#### Scenario: Relative path resolution under BFF proxy
- **WHEN** an API request is initiated by any service client
- **THEN** the request targets `/api/*`, delegating upstream routing to the BFF proxy server

#### Scenario: Configured default request timeout and headers
- **WHEN** the shared `apiClient` instance is initialized
- **THEN** it sets `timeout = 10000` and default `Content-Type: application/json` headers

### Requirement: Structured request and response logging interceptors
The API client layer SHALL intercept all outgoing requests, successful responses, and network/server errors to emit structured log messages using the project logger utility (`logUtil`).

#### Scenario: Outgoing request logged at debug level
- **WHEN** any HTTP request is dispatched through `apiClient`
- **THEN** the request interceptor logs the HTTP method, request URL, and base URL at debug level

#### Scenario: Successful response logged at debug level
- **WHEN** an HTTP response is received
- **THEN** the response interceptor logs the HTTP method, URL, status code, and status text at debug level

#### Scenario: HTTP response error logged with status and payload
- **WHEN** the server returns an HTTP 4xx or 5xx error response
- **THEN** the error interceptor logs the error with HTTP status, URL, and response data payload

#### Scenario: Network failure without response logged
- **WHEN** a request fails due to network disconnection or timeout without receiving a server response
- **THEN** the error interceptor logs a "No response received from server" error with the request method and URL

### Requirement: Action-encapsulated HTTP communication
API calls SHALL be organized into domain-specific action modules that encapsulate endpoint paths and attach standard BFF headers (`Accept`, `X-Requested-With`). Standard actions return `AxiosResponse`, domain data helpers return unwrapped response data, and self-dispatching mount actions (`getOperatorMetadata`) dispatch directly into Redux and return `void`.

#### Scenario: Domain action attaches BFF headers
- **WHEN** a domain action (such as `createFlow` or `enrichFlowFeatures`) issues a request
- **THEN** the request sends `Accept: application/json` and `X-Requested-With: XMLHttpRequest` headers to the BFF endpoint

#### Scenario: Standard domain action returns typed Axios response
- **WHEN** a standard API action succeeds
- **THEN** the promise resolves with the typed `AxiosResponse` containing the domain payload

#### Scenario: Data-unwrapping action returns response payload directly
- **WHEN** an action helper such as `getProviderModels` succeeds
- **THEN** the promise resolves directly with `response.data` (`ModelsResponse`) rather than the Axios response envelope

#### Scenario: Self-dispatching action updates store directly
- **WHEN** a self-dispatching action such as `getOperatorMetadata` succeeds
- **THEN** it dispatches the payload directly to Redux and returns `Promise<void>` instead of returning response data

### Requirement: Error handling and propagation conventions
Domain API actions SHALL log operational errors with contextual details and re-throw caught exceptions by default for Redux thunks, with specific mount actions permitted to absorb errors to prevent unhandled rejection loops.

#### Scenario: Standard action logs error and re-throws
- **WHEN** a standard API action (e.g. `createFlow`, `getProviderModels`) fails
- **THEN** the action logs the error via `logUtil.error` and re-throws the error for caller handling

#### Scenario: Self-dispatching action absorbs error on failure
- **WHEN** `getOperatorMetadata` fails during canvas initialization
- **THEN** the action logs the error via `logUtil.error` and absorbs it without throwing, preventing global unhandled rejection cascades

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
