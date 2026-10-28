# Spec Delta

## ADDED Requirements

### Requirement: Login route
The router SHALL provide a `/login` route outside the main shell, resolved under the `/ui` basename, that accepts an optional `return_to` query parameter.

#### Scenario: Login route resolves
- **WHEN** the user navigates to `/ui/login`
- **THEN** the login page renders without the main navigation chrome

### Requirement: Protected routes
Every route other than `/login` and the error page SHALL be wrapped in `ProtectedRoute`. While the auth state is unresolved it SHALL show a loading indicator. When the user is unauthenticated it SHALL redirect to `/login?return_to=<encoded current path and query>`.

#### Scenario: Deep link while signed out
- **WHEN** a signed-out user opens `/ui/projects/123`
- **THEN** the browser is redirected to `/ui/login?return_to=%2Fprojects%2F123`

#### Scenario: Authenticated pass-through
- **WHEN** an authenticated user opens a protected route
- **THEN** the page renders normally

#### Scenario: Loading state
- **WHEN** the auth state is still being resolved
- **THEN** a loading indicator is shown and no redirect occurs yet

### Requirement: Header user menu
When auth is enabled the application header SHALL show the signed-in user's name and a sign-out action. Choosing sign-out SHALL end the session and navigate to `/login`. When auth is disabled the menu SHALL NOT be shown.

#### Scenario: Sign out
- **WHEN** the user chooses sign-out
- **THEN** the session ends and the login page is shown

#### Scenario: Menu hidden when auth disabled
- **WHEN** `/auth/config` reports auth disabled
- **THEN** no user menu is rendered
