# Spec Delta

## Purpose

The bff-proxy capability defines how the Node/Express backend-for-frontend relays browser requests, session cookies and authentication headers to the REST API without exposing backend addresses or credentials to browser scripts.

## ADDED Requirements

### Requirement: Credential and context header forwarding
Every proxied request SHALL forward the `Cookie`, `Authorization`, `X-Requested-With`, `X-Transaction-ID`, `X-Forwarded-For` and `X-Forwarded-Proto` headers from the browser request to the REST API when present.

#### Scenario: Cookie reaches backend
- **WHEN** the browser calls `GET /api/flows` with a session cookie
- **THEN** the REST API receives the same `Cookie` header

#### Scenario: CSRF header reaches backend
- **WHEN** the browser sends `X-Requested-With` on a mutation
- **THEN** the REST API receives it

### Requirement: Auth route proxy
The BFF SHALL expose `/api/auth/login`, `/api/auth/logout`, `/api/auth/me`, `/api/auth/config`, `/api/auth/oauth2/providers`, `/api/auth/oauth2/authorize`, `/api/auth/oauth2/callback` and `/api/auth/oauth2/discovery/:provider`, mapped to the REST API's `/auth/*` routes. Redirect responses (3xx) SHALL be passed through to the browser without being followed server-side (`maxRedirects: 0`).

#### Scenario: Login proxied
- **WHEN** the browser posts to `/api/auth/login`
- **THEN** the BFF forwards it to `/auth/login` and returns the status and body unchanged

#### Scenario: OIDC redirect passed through
- **WHEN** the REST API answers the callback with a 302
- **THEN** the BFF returns that 302 and its `Location` to the browser

### Requirement: Set-Cookie relay
All `Set-Cookie` headers returned by the REST API SHALL be relayed to the browser, including when more than one is present. The cookie SHALL NOT be readable or rewritten by the BFF's own scripts.

#### Scenario: Session cookie relayed
- **WHEN** the REST API responds to login with a `Set-Cookie`
- **THEN** the browser receives that cookie with its attributes intact

#### Scenario: Multiple cookies preserved
- **WHEN** the REST API sets two cookies in one response
- **THEN** both reach the browser

### Requirement: Authentication errors relayed unchanged
The BFF SHALL return 401 and 403 responses from the REST API to the browser with the same status and body, without converting them to a generic error.

#### Scenario: 401 relayed
- **WHEN** the REST API answers a proxied call with 401
- **THEN** the browser receives 401

#### Scenario: 403 relayed
- **WHEN** the REST API answers 403 with a message
- **THEN** the browser receives 403 with that message

### Requirement: Loopback binding by default
The BFF SHALL listen on `127.0.0.1` unless `BFF_HOST` is set. It SHALL NOT bundle backend addresses or secrets into browser JavaScript.

#### Scenario: Default bind
- **WHEN** the BFF starts with no `BFF_HOST`
- **THEN** it accepts connections only on the loopback interface

#### Scenario: Explicit host
- **WHEN** `BFF_HOST=0.0.0.0` is set
- **THEN** it accepts connections on all interfaces

### Requirement: Cookies survive the API reverse proxy
When the REST API reverse-proxies browser requests to the BFF, every `Set-Cookie` header from the BFF SHALL be preserved as a separate header in the response.

#### Scenario: Wheel deployment login
- **WHEN** a user logs in through the REST API's reverse proxy to the BFF
- **THEN** the session cookie reaches the browser
