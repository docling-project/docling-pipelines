# Spec Delta

## Purpose

The auth-api capability defines how callers establish, present and end an authenticated session with the REST API: login, logout, current-user lookup, auth discovery, session credentials, CSRF defense, throttling and startup safety.

## ADDED Requirements

### Requirement: Authentication toggle
The API SHALL read `DOCPIPE_AUTH_ENABLED` on each request, defaulting to `true`. When it is `false`, `/api/v1/*` routes SHALL accept requests without credentials and treat the caller as a local administrator.

#### Scenario: Auth enabled by default
- **WHEN** `DOCPIPE_AUTH_ENABLED` is unset and `GET /api/v1/flows` is called without credentials
- **THEN** the response is 401

#### Scenario: Auth disabled preserves previous behavior
- **WHEN** `DOCPIPE_AUTH_ENABLED=false` and `GET /api/v1/flows` is called without credentials
- **THEN** the response is 200

#### Scenario: Toggle change applies without restart of the caller
- **WHEN** the setting is changed between two requests in the same process
- **THEN** the second request is evaluated under the new value

### Requirement: Session enforced on all versioned routes
When auth is enabled, every `APIRoute` under `/api/v1/` SHALL require a valid session. Only `GET /`, `GET /health`, `GET /auth/config`, `POST /auth/login`, the OIDC `authorize`, `callback`, `providers` and `discovery` routes, the `/ui/*` static SPA routes, and FastAPI's built-in documentation routes (`/api/v1/docs`, `/api/v1/redoc`, `/api/v1/openapi.json`) SHALL be public.

#### Scenario: Unauthenticated call rejected
- **WHEN** any `/api/v1/*` API route is called without a cookie or Bearer token
- **THEN** the response is 401 with a `WWW-Authenticate: Bearer` header

#### Scenario: Newly added route is covered
- **WHEN** an `APIRoute` is registered under `/api/v1/` without a session requirement
- **THEN** the automated route-inventory test fails

### Requirement: Session credentials
A session SHALL be carried by an `HttpOnly`, `SameSite=Lax` cookie with `Path=/` holding the signed JWT, or by an `Authorization: Bearer` header. When both are present the cookie SHALL be used. The cookie SHALL be marked `Secure` when `request.url.scheme == "https"`, when `DOCPIPE_TRUST_PROXY_HEADERS=true` and `X-Forwarded-Proto == "https"`, or when `DOCPIPE_AUTH_COOKIE_SECURE=true`. `CORSMiddleware` SHALL enable `allow_credentials=True` when `CORS_ORIGINS` does not contain `*`.

#### Scenario: Cookie session accepted
- **WHEN** a request carries a valid session cookie and no Authorization header
- **THEN** the request is authenticated as the cookie's user

#### Scenario: Bearer token accepted
- **WHEN** a request carries a valid Bearer token and no cookie
- **THEN** the request is authenticated as the token's user

#### Scenario: Expired or malformed credential rejected
- **WHEN** the presented token is expired, malformed or signed with another key
- **THEN** the response is 401

### Requirement: CSRF defense for cookie sessions
Cookie-authenticated requests using `POST`, `PUT`, `PATCH` or `DELETE` SHALL include a non-empty `X-Requested-With` header. Requests authenticated by Bearer token SHALL be exempt.

#### Scenario: Cookie mutation without header rejected
- **WHEN** a cookie-authenticated `DELETE /api/v1/flows/{id}` omits `X-Requested-With`
- **THEN** the response is 403 and nothing is deleted

#### Scenario: Cookie read needs no header
- **WHEN** a cookie-authenticated `GET` omits `X-Requested-With`
- **THEN** the request is processed normally

#### Scenario: Bearer mutation exempt
- **WHEN** a Bearer-authenticated `POST` omits `X-Requested-With`
- **THEN** the request is processed normally

### Requirement: Login
`POST /auth/login` SHALL validate credentials through the configured authenticators, and on success SHALL set the session cookie and return the `access_token` (for API and script clients) together with the authenticated `user` and `roles`. Failure SHALL return 401 with a generic "Invalid credentials" message that does not reveal whether the username exists.

#### Scenario: Successful login sets cookie and returns user and token
- **WHEN** valid credentials are posted to `/auth/login`
- **THEN** the response is 200 with `access_token` and `user` (including `roles`), and a `Set-Cookie` header for the session

#### Scenario: Wrong password
- **WHEN** an invalid password is posted
- **THEN** the response is 401 with "Invalid credentials" and no cookie

#### Scenario: No login method configured
- **WHEN** no LDAP configuration and no bootstrap administrator are configured
- **THEN** `POST /auth/login` returns 503 and `GET /auth/config` reports no credential login

### Requirement: Bootstrap administrator
A local administrator login SHALL be available only when both `DOCPIPE_AUTH_BOOTSTRAP_USERNAME` and `DOCPIPE_AUTH_BOOTSTRAP_PASSWORD_HASH` (a bcrypt hash) are set in the environment. It SHALL always grant the `admin` role.

#### Scenario: Both variables set
- **WHEN** both variables are set and the matching password is posted
- **THEN** login succeeds with the `admin` role

#### Scenario: Partial or invalid configuration fails startup
- **WHEN** only one variable is set, or the hash is not a valid bcrypt hash
- **THEN** the API refuses to start with a configuration error

#### Scenario: Oversized password rejected safely
- **WHEN** a password longer than 72 bytes is posted
- **THEN** the response is 401, not 500

### Requirement: Logout
`POST /auth/logout` SHALL require a session and SHALL clear the session cookie. A Bearer token is not invalidated server-side.

#### Scenario: Logout clears cookie
- **WHEN** an authenticated browser calls `POST /auth/logout` with `X-Requested-With`
- **THEN** the response is 200 and the cookie is expired in the response

#### Scenario: Logout without a session
- **WHEN** `POST /auth/logout` is called without a session
- **THEN** the response is 401

### Requirement: Current user and auth discovery
`GET /auth/me` SHALL return the authenticated user's id, username, email and roles. The public `GET /auth/config` SHALL return whether auth is enabled, whether credential login is available, and the configured OIDC providers.

#### Scenario: Me returns roles
- **WHEN** an authenticated user calls `GET /auth/me`
- **THEN** the response includes a `roles` list

#### Scenario: Config is public
- **WHEN** `GET /auth/config` is called without credentials
- **THEN** the response is 200 and contains no secrets

### Requirement: OIDC login issues a cookie
`/auth/oauth2/authorize` SHALL accept a `return_to` query parameter (aliasing `redirect_after` for backward compatibility). The OIDC callback SHALL set the session cookie and redirect to a validated same-origin `return_to` path, prefixing `/ui` when the relative path does not already start with `/ui` and defaulting to `/ui/projects`. The token SHALL NOT appear in any URL. A `return_to` value that is absolute, protocol-relative, contains backslashes or is on another origin SHALL be ignored and replaced with `/ui/projects`.

#### Scenario: Callback sets cookie and redirects
- **WHEN** the OIDC callback succeeds with `return_to=/flows/abc`
- **THEN** the response is a redirect to `/ui/flows/abc` with a session cookie and no token in the URL

#### Scenario: Open redirect refused
- **WHEN** `return_to` is `https://evil.example/`
- **THEN** the redirect goes to `/ui/projects`

### Requirement: Login throttling
`POST /auth/login` SHALL allow at most 5 failed attempts per client address per minute and SHALL lock a username for 5 minutes after 5 consecutive failures. Throttled responses SHALL be 429 with a `Retry-After` header. Successful logins SHALL NOT count toward the limit.

#### Scenario: Address limit
- **WHEN** one address makes a sixth failed attempt within a minute
- **THEN** the response is 429 with `Retry-After`

#### Scenario: Username lockout
- **WHEN** a username fails 5 consecutive times from varying addresses
- **THEN** further attempts for that username return 429 until the lockout expires

#### Scenario: Forwarded client address
- **WHEN** `DOCPIPE_TRUST_PROXY_HEADERS=true` and `X-Forwarded-For` is present
- **THEN** the first forwarded address is used as the client address

### Requirement: Startup validation
When auth is enabled the API SHALL fail to start unless `JWT_SECRET_KEY` is set, is not a placeholder and is at least 32 characters. It SHALL log a security warning when `CORS_ORIGINS` contains `*`.

#### Scenario: Weak secret blocks startup
- **WHEN** auth is enabled and `JWT_SECRET_KEY` is unset or shorter than 32 characters
- **THEN** startup fails with a clear configuration error

#### Scenario: Disabled auth needs no secret
- **WHEN** `DOCPIPE_AUTH_ENABLED=false` and no secret is set
- **THEN** the API starts normally

### Requirement: Internal service calls authenticate
Internal components that call the API over HTTP, such as event-triggered job submission, SHALL authenticate with a system credential so they continue to work when auth is enabled.

#### Scenario: Event-triggered job run succeeds
- **WHEN** an event dispatch submits a job run while auth is enabled
- **THEN** the job run is accepted rather than rejected with 401
