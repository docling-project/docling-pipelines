# Spec Delta

## Purpose

The auth-api capability defines how callers establish, present and end an authenticated session with the REST API: login, logout, current-user lookup, auth discovery, session credentials, CSRF defense, throttling and startup safety.

## ADDED Requirements

### Requirement: Authentication toggle
The API SHALL read `DOCPIPE_AUTH_ENABLED` on each request, defaulting to `true`. When it is `false`, `/api/v1/*` routes SHALL accept requests without credentials and treat the caller as the reserved local principal.

#### Scenario: Auth enabled by default
- **WHEN** `DOCPIPE_AUTH_ENABLED` is unset and `GET /api/v1/flows` is called without credentials
- **THEN** the response is 401

#### Scenario: Auth disabled preserves previous behavior
- **WHEN** `DOCPIPE_AUTH_ENABLED=false` and `GET /api/v1/flows` is called without credentials
- **THEN** the response is 200

### Requirement: Toggle is fixed per deployment
The toggle SHALL be set through the environment before the process starts. Reading it on each request exists so tests can change it, and operators SHALL NOT rely on changing it at runtime.

#### Scenario: Test changes the toggle
- **WHEN** a test changes the setting between two requests in the same process
- **THEN** the second request is evaluated under the new value

### Requirement: Local principal when auth is disabled
When auth is disabled, `get_current_user` SHALL return a reserved local principal with the `admin` role and a username that no LDAP, OIDC or bootstrap login can produce. Authenticators SHALL reject that username.

#### Scenario: Local principal on a route
- **WHEN** auth is disabled and a route reads the current user
- **THEN** the user is the reserved local principal with the `admin` role

#### Scenario: Reserved name cannot log in
- **WHEN** a login is attempted with the reserved username
- **THEN** the response is 401

### Requirement: No silent fallback on invalid configuration
The API SHALL NOT disable authentication or login because of a configuration error. The `except` block in `main.py` that currently turns login off on a JWT configuration error SHALL be removed, so that a bad configuration stops startup.

#### Scenario: Bad configuration stops startup
- **WHEN** auth is enabled and the JWT configuration is invalid
- **THEN** the API fails to start rather than serving without login

### Requirement: Session enforced on all versioned routes
When auth is enabled, every `APIRoute` under `/api/v1/` SHALL require a valid session. Only `GET /`, `GET /health`, `GET /auth/config`, `POST /auth/login`, the OIDC `authorize`, `callback`, `providers` and `discovery` routes, the `/ui/*` static SPA routes, and FastAPI's built-in documentation routes (`/api/v1/docs`, `/api/v1/redoc`, `/api/v1/openapi.json`) SHALL be public.

#### Scenario: Unauthenticated call rejected
- **WHEN** any `/api/v1/*` API route is called without a cookie or Bearer token
- **THEN** the response is 401 with a `WWW-Authenticate: Bearer` header

#### Scenario: Newly added route is covered
- **WHEN** an `APIRoute` is registered under `/api/v1/` without a session requirement
- **THEN** the automated route-inventory test fails

### Requirement: Public documentation and provider routes
The documentation routes expose the API schema and the OIDC `discovery` route returns the provider's public discovery document, so both reveal endpoint addresses to unauthenticated callers. The setup guide SHALL state this. The `providers` route SHALL return only `name`, `display_name` and `authorize_url`.

#### Scenario: Providers route leaks no client data
- **WHEN** an unauthenticated caller reads the OIDC `providers` route
- **THEN** the response contains no client id, client secret or tenant id

### Requirement: Session credentials
A session SHALL be carried by an `HttpOnly`, `SameSite=Lax` cookie with `Path=/` holding the signed JWT, or by an `Authorization: Bearer` header. When both are present the Bearer header SHALL be used and the request SHALL be treated as a Bearer request.

#### Scenario: Cookie session accepted
- **WHEN** a request carries a valid session cookie and no Authorization header
- **THEN** the request is authenticated as the cookie's user

#### Scenario: Bearer token accepted
- **WHEN** a request carries a valid Bearer token and no cookie
- **THEN** the request is authenticated as the token's user

#### Scenario: Header wins over cookie
- **WHEN** a request carries a valid Bearer token and a session cookie for another user
- **THEN** the request is authenticated as the Bearer token's user and is exempt from the CSRF header rule

#### Scenario: Expired or malformed credential rejected
- **WHEN** the presented token is expired, malformed or signed with another key
- **THEN** the response is 401

### Requirement: Secure cookie attribute
The cookie SHALL be marked `Secure` when `request.url.scheme == "https"`, when `DOCPIPE_TRUST_PROXY_HEADERS=true` and `X-Forwarded-Proto == "https"`, or when `DOCPIPE_AUTH_COOKIE_SECURE=true`. The API SHALL log a warning at startup when auth is enabled and none of these can apply, so that an operator behind a TLS-terminating proxy notices an insecure cookie.

#### Scenario: Secure over HTTPS
- **WHEN** login is served over HTTPS
- **THEN** the cookie carries `Secure`

#### Scenario: Secure behind a trusted proxy
- **WHEN** `DOCPIPE_TRUST_PROXY_HEADERS=true` and the request carries `X-Forwarded-Proto: https`
- **THEN** the cookie carries `Secure`

#### Scenario: Warning without any Secure signal
- **WHEN** auth is enabled and neither `DOCPIPE_TRUST_PROXY_HEADERS` nor `DOCPIPE_AUTH_COOKIE_SECURE` is true
- **THEN** a warning is logged at startup

### Requirement: CORS stays non-credentialed
`CORSMiddleware` SHALL keep `allow_credentials=False`. The SPA and the API share one origin, so cookies do not need CORS credentials. The startup warning for `CORS_ORIGINS` containing `*` SHALL remain.

#### Scenario: Credentials not allowed cross-origin
- **WHEN** a preflight request arrives from an allowed origin
- **THEN** the response does not include `Access-Control-Allow-Credentials: true`

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
A local administrator login SHALL be available when both `DOCPIPE_AUTH_BOOTSTRAP_USERNAME` and `DOCPIPE_AUTH_BOOTSTRAP_PASSWORD_HASH` (a bcrypt hash) are set in the environment. It SHALL always grant the `admin` role and SHALL stay available when LDAP or OIDC is configured, as a break-glass login. Every successful bootstrap login SHALL be written to the audit log.

#### Scenario: Both variables set
- **WHEN** both variables are set and the matching password is posted
- **THEN** login succeeds with the `admin` role

#### Scenario: Partial or invalid configuration fails startup
- **WHEN** only one variable is set, or the hash is not a valid bcrypt hash
- **THEN** the API refuses to start with a configuration error

#### Scenario: Oversized password rejected safely
- **WHEN** a password longer than 72 bytes is posted
- **THEN** the response is 401, not 500

#### Scenario: Break-glass login audited
- **WHEN** the bootstrap administrator logs in while LDAP is also configured
- **THEN** an audit entry records the login

### Requirement: Bootstrap secrets are not shipped as defaults
The Docker Compose files SHALL NOT contain a default bootstrap password hash. They SHALL reference variables that the operator supplies.

#### Scenario: Compose has no default hash
- **WHEN** a Compose file is rendered with no bootstrap variables set
- **THEN** the bootstrap administrator is not configured

### Requirement: Logout
`POST /auth/logout` SHALL clear the session cookie and SHALL succeed whether or not the request carries a valid session, so that an expired cookie can still be cleared. A Bearer token is not invalidated server-side, and a token that was issued stays valid until it expires, up to 30 minutes. The setup guide SHALL state this.

#### Scenario: Logout clears cookie
- **WHEN** an authenticated browser calls `POST /auth/logout` with `X-Requested-With`
- **THEN** the response is 200 and the cookie is expired in the response

#### Scenario: Logout with an expired session
- **WHEN** `POST /auth/logout` is called with an expired cookie
- **THEN** the response is 200 and the cookie is expired in the response

### Requirement: Current user and auth discovery
`GET /auth/me` SHALL return the authenticated user's id, username, email and roles. The public `GET /auth/config` SHALL return whether auth is enabled, whether credential login is available, and the configured OIDC providers.

#### Scenario: Me returns roles
- **WHEN** an authenticated user calls `GET /auth/me`
- **THEN** the response includes a `roles` list

#### Scenario: Config is public
- **WHEN** `GET /auth/config` is called without credentials
- **THEN** the response is 200 and contains no secrets

### Requirement: Auth config fields
`GET /auth/config` SHALL return `auth_enabled`, `credential_login` and, for each OIDC provider, `name`, `display_name` and `authorize_url`. It SHALL NOT return client ids, tenant ids, secrets or provider endpoint addresses.

#### Scenario: Provider entry is minimal
- **WHEN** an OIDC provider is configured
- **THEN** its entry has exactly `name`, `display_name` and `authorize_url`

### Requirement: OIDC login issues a cookie
`/auth/oauth2/authorize` SHALL accept a `return_to` query parameter, aliasing `redirect_after` for backward compatibility. The OIDC callback SHALL set the session cookie and redirect to a validated same-origin `return_to` path. The token SHALL NOT appear in any URL.

#### Scenario: Callback sets cookie and redirects
- **WHEN** the OIDC callback succeeds with `return_to=/flows/abc`
- **THEN** the response is a redirect to `/ui/flows/abc` with a session cookie and no token in the URL

### Requirement: OIDC return path validation
The callback SHALL prefix `/ui` when the relative `return_to` path does not already start with `/ui`, and SHALL default to `/ui/projects`. A `return_to` value that is absolute, protocol-relative, contains backslashes or is on another origin SHALL be ignored and replaced with `/ui/projects`.

#### Scenario: Open redirect refused
- **WHEN** `return_to` is `https://evil.example/`
- **THEN** the redirect goes to `/ui/projects`

### Requirement: OIDC login binds to the browser
`/auth/oauth2/authorize` SHALL set a short-lived `HttpOnly` nonce cookie and tie the stored `state` to it. The callback SHALL reject a request whose nonce cookie is missing or does not match, so that an attacker cannot complete a login in a victim's browser. The `state` store is in-memory and per process, and the setup guide SHALL state that limit.

#### Scenario: Matching nonce
- **WHEN** the callback arrives with the nonce cookie that `authorize` set
- **THEN** the login completes

#### Scenario: Missing nonce
- **WHEN** the callback arrives with a valid `state` but no nonce cookie
- **THEN** the response is 400 and no session cookie is set

#### Scenario: Mismatched nonce
- **WHEN** the callback arrives with a nonce cookie that does not match the stored one
- **THEN** the response is 400 and no session cookie is set

### Requirement: Login throttling
`POST /auth/login` SHALL allow at most 5 failed attempts per client address per minute and SHALL lock the pair of client address and username for 5 minutes after 5 consecutive failures. Throttled responses SHALL be 429 with a `Retry-After` header. Successful logins SHALL NOT count toward the limit.

#### Scenario: Address limit
- **WHEN** one address makes a sixth failed attempt within a minute
- **THEN** the response is 429 with `Retry-After`

#### Scenario: Pair lockout
- **WHEN** one address fails 5 consecutive times for the same username
- **THEN** further attempts from that address for that username return 429 until the lockout expires

#### Scenario: Other address unaffected
- **WHEN** an address is locked out for a username
- **THEN** the same user can still log in from another address

### Requirement: Client address for throttling
The client address SHALL be the TCP peer address by default. When `DOCPIPE_TRUST_PROXY_HEADERS=true` it SHALL be the rightmost `X-Forwarded-For` entry, which is the address the trusted proxy observed. Earlier entries come from the client and SHALL be ignored. Operators SHALL set the flag only when the API sits behind exactly one ingress or load balancer that appends to the header, and the setup guide SHALL say so.

#### Scenario: Peer address by default
- **WHEN** `DOCPIPE_TRUST_PROXY_HEADERS` is unset and `X-Forwarded-For` is present
- **THEN** the TCP peer address is used

#### Scenario: Forwarded address behind a trusted proxy
- **WHEN** `DOCPIPE_TRUST_PROXY_HEADERS=true` and `X-Forwarded-For` is `spoofed, 203.0.113.9`
- **THEN** `203.0.113.9` is used as the client address

### Requirement: Startup validation
When auth is enabled the API SHALL fail to start unless `JWT_SECRET_KEY` is set, is not a placeholder and is at least 32 characters. It SHALL log a security warning when `CORS_ORIGINS` contains `*`.

#### Scenario: Weak secret blocks startup
- **WHEN** auth is enabled and `JWT_SECRET_KEY` is unset or shorter than 32 characters
- **THEN** startup fails with a clear configuration error

#### Scenario: Disabled auth needs no secret
- **WHEN** `DOCPIPE_AUTH_ENABLED=false` and no secret is set
- **THEN** the API starts normally

### Requirement: Internal service calls authenticate
Internal components that call the API over HTTP, such as event-triggered job submission, SHALL authenticate with a system credential so they continue to work when auth is enabled. The credential SHALL be a Bearer token with the `editor` role, a fixed system username and a lifetime of at most 5 minutes. The API SHALL NOT accept the system username or role from any user input.

#### Scenario: Event-triggered job run succeeds
- **WHEN** an event dispatch submits a job run while auth is enabled
- **THEN** the job run is accepted rather than rejected with 401

#### Scenario: System token lacks admin rights
- **WHEN** the system token is used on a custom operator route
- **THEN** the response is 403
