# Spec Delta

## Purpose

The auth-slice capability defines the client-side authentication state: how it is bootstrapped from the server, what it exposes to components, and how permission flags are derived for gating UI actions.

## ADDED Requirements

### Requirement: Auth state shape
The `auth` Redux slice SHALL hold the current user, whether auth is enabled, the available OIDC providers, whether credential login is available, a status of `idle`, `loading`, `authenticated` or `unauthenticated`, and the last error message.

#### Scenario: Initial state
- **WHEN** the store is created
- **THEN** the auth status is `idle` and the user is empty

### Requirement: Bootstrap from the server
On application start the slice SHALL load `GET /auth/config` and, when auth is enabled, `GET /auth/me`. A 401 from `/auth/me` SHALL set the status to `unauthenticated` without showing an error or redirecting from within the slice.

#### Scenario: Signed-in user restored
- **WHEN** the page loads with a valid session
- **THEN** the status becomes `authenticated` and the user and roles are stored

#### Scenario: No session
- **WHEN** the page loads without a session
- **THEN** the status becomes `unauthenticated`

#### Scenario: Auth disabled
- **WHEN** `/auth/config` reports auth disabled
- **THEN** the status becomes `authenticated` with administrator rights and no `/auth/me` request is made

### Requirement: Login and logout actions
The slice SHALL provide a login action that posts credentials to `/auth/login` and stores only the returned `user` (ignoring any `access_token` field in the response body), and a logout action that posts to `/auth/logout`. A failed login SHALL store the server's message and keep the status `unauthenticated`. Logout SHALL clear the user regardless of the response.

#### Scenario: Login success
- **WHEN** valid credentials are submitted
- **THEN** the user and roles are stored and the status is `authenticated`

#### Scenario: Login failure
- **WHEN** invalid credentials are submitted
- **THEN** the status stays `unauthenticated` and the error message is stored

#### Scenario: Logout clears state
- **WHEN** the user signs out
- **THEN** the user is cleared and the status is `unauthenticated`

### Requirement: Permission flags
The `useAuth` hook SHALL return the `user`, `authEnabled`, `isAuthenticated`, `isLoading`, `canEdit` (true for `editor` or `admin`), `canAdmin` (true for `admin`), and `canModifyAsset(createdBy)` (true when `canAdmin`, or when `canEdit` and `createdBy` is empty or equals `user.username`). While the status is `idle` or `loading`, `isLoading` SHALL be true.

#### Scenario: Viewer flags
- **WHEN** the user's only role is `viewer`
- **THEN** `canEdit` and `canAdmin` are false

#### Scenario: Editor flags
- **WHEN** the user holds `editor`
- **THEN** `canEdit` is true and `canAdmin` is false

#### Scenario: Admin flags
- **WHEN** the user holds `admin`
- **THEN** `canEdit` and `canAdmin` are true

### Requirement: No credentials in JavaScript-accessible storage
The slice SHALL NOT store a token, and the application SHALL NOT write credentials to `localStorage`, `sessionStorage` or any URL.

#### Scenario: Token never exposed
- **WHEN** a user signs in
- **THEN** no token is present in Redux state, web storage or the address bar
