# Spec Delta

## Purpose

The login-page capability defines the `/login` page where an unauthenticated user signs in with credentials or an OIDC provider and returns to the page they originally requested.

## ADDED Requirements

### Requirement: Login route and layout
The application SHALL serve a `/login` page, outside the main shell navigation, built from Carbon components: a slim header with the application name and a theme toggle, a brand panel beside a form panel with username and password fields, a primary log-in button and an inline notification area. The page SHALL be usable on narrow screens.

#### Scenario: Page renders
- **WHEN** an unauthenticated user opens `/ui/login`
- **THEN** the header, the brand panel, the form and the log-in button are shown without the main navigation, the notification bell or the profile menu

#### Scenario: Brand panel follows the theme
- **WHEN** the application theme is light or dark
- **THEN** the brand panel shows the product tagline with the animated artwork for that theme

#### Scenario: Narrow screen
- **WHEN** the viewport is below the large breakpoint
- **THEN** the brand panel collapses to a compact tagline strip above the form

### Requirement: Credential sign-in
The credential form SHALL be shown only when `/auth/config` reports credential login available. It SHALL validate that both fields are non-empty before submitting and when a field loses focus while empty, show a loading state while the request is pending and disable the button to prevent double submit. The password field SHALL offer a show/hide toggle.

#### Scenario: Empty field blocked
- **WHEN** the user submits with an empty password
- **THEN** an inline field error is shown and no request is sent

#### Scenario: Failed sign-in
- **WHEN** the server rejects the credentials
- **THEN** an inline notification shows the server's message, the password field is cleared and focus returns to the username field

#### Scenario: Throttled sign-in
- **WHEN** the server answers 429
- **THEN** the notification tells the user to retry later

#### Scenario: Credential login unavailable
- **WHEN** `/auth/config` reports no credential login
- **THEN** the form is hidden and only provider buttons are shown

### Requirement: OIDC sign-in
One button per configured OIDC provider SHALL start the provider flow by navigating to the `authorize_url` that `GET /auth/config` returns for that provider, with the requested `return_to` path appended.

#### Scenario: Provider button
- **WHEN** the user selects a provider
- **THEN** the browser navigates to the authorize URL for that provider carrying `return_to`

#### Scenario: No method available
- **WHEN** there is neither credential login nor a provider
- **THEN** the page shows a notification that no login method is configured

### Requirement: Return to requested page
After a successful sign-in the user SHALL be sent to the `return_to` path from the query string, or to the projects page when absent or not a same-application relative path.

#### Scenario: Deep link restored
- **WHEN** a signed-out user opens `/ui/flows/abc` and then signs in
- **THEN** the user lands on `/ui/flows/abc`

#### Scenario: Unsafe return value
- **WHEN** `return_to` is an absolute URL
- **THEN** the user lands on the projects page

### Requirement: Already signed in
A user who is already authenticated and opens `/login` SHALL be redirected to the `return_to` path or the projects page.

#### Scenario: Authenticated visit
- **WHEN** a signed-in user opens `/ui/login`
- **THEN** the user is redirected away from the login page

### Requirement: Accessibility
The form SHALL be keyboard operable, associate labels with inputs, and announce errors to assistive technology.

#### Scenario: Error announced
- **WHEN** a sign-in error is shown
- **THEN** the notification is exposed with an alert role
