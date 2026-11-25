# frontend/navigation Specification

## Purpose
The navigation capability provides the single-page application routing infrastructure, defining URL structure, the `/ui` router basename, `project_id` query parameter preservation for back-navigation, dynamic breadcrumb generation with action injection, localStorage LRU recently-visited history, and code-split route boundaries.

## Requirements

### Requirement: Router basename and URL structure
The application router SHALL configure `/ui` as the root basename for all application routes, prefixing all page paths under `/ui`.

#### Scenario: Route resolved under UI basename
- **WHEN** the user navigates to `/projects` or `/flows/:flowId`
- **THEN** the router resolves the route relative to the `/ui` basename (`/ui/projects`, `/ui/flows/:flowId`) without 404ing

### Requirement: Project ID query parameter back-navigation convention
Flow and canvas routes SHALL accept and preserve an optional `project_id` query parameter to enable context-aware back-navigation to the parent project.

#### Scenario: Back navigation returns to originating project
- **WHEN** the user accesses a flow canvas with `?project_id=<id>` and clicks the back navigation control or project breadcrumb
- **THEN** the application navigates back to `/projects/<id>` instead of the global flows list

#### Scenario: Back navigation without project context
- **WHEN** the user accesses a flow canvas without a `project_id` query parameter and navigates back
- **THEN** the application navigates to the default flows index page

### Requirement: Dynamic breadcrumb generation and action injection
The application SHALL dynamically construct breadcrumbs based on the active route hierarchy and allow individual pages to inject context actions via `BreadcrumbActionsContext`.

#### Scenario: Page hierarchy reflected in breadcrumbs
- **WHEN** the user navigates to `/projects/:projectId/flows/:flowId`
- **THEN** the breadcrumb trail renders Home > Projects > [Project Name] > [Flow Name]

#### Scenario: Page injects custom breadcrumb action controls
- **WHEN** a page mounts within the breadcrumb context and provides custom actions (e.g. Save, Run, Edit)
- **THEN** the breadcrumb bar renders those action controls aligned with the trail

### Requirement: Recently-visited localStorage LRU cache
The navigation layer SHALL track visited projects and flows in a localStorage LRU cache (capped at a defined limit), updating entries upon navigation and omitting duplicates.

#### Scenario: Page visit updates LRU cache
- **WHEN** the user opens a project or flow detail page
- **THEN** the item ID, title, and timestamp are placed at the front of the recently-visited cache

#### Scenario: Oldest item evicted when cache limit reached
- **WHEN** a new item is visited and the cache exceeds its maximum capacity
- **THEN** the least recently opened entry is removed from the cache

### Requirement: Code-split route boundaries
The routing configuration SHALL load page components asynchronously using `React.lazy()` with a top-level `Suspense` fallback loading indicator, instantiated once at module scope to avoid unmount cycles.

#### Scenario: Lazy page loading displays fallback indicator
- **WHEN** navigating to an un-cached route
- **THEN** the application renders a loading spinner until the chunk finishes loading

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
When auth is enabled the application header SHALL show a profile button as its rightmost global action, after the theme toggle. Selecting it SHALL open a panel under the button with the signed-in user's display name (full name, or the username when there is none), email, role tags and a sign-out action. The panel SHALL close on sign-out, on an outside click and on Escape. Choosing sign-out SHALL end the session and navigate to `/login`. When auth is disabled the menu SHALL NOT be shown.

#### Scenario: Profile panel
- **WHEN** a signed-in user selects the profile button
- **THEN** the panel shows the user's name, email and roles and a sign-out action

#### Scenario: Panel dismissed
- **WHEN** the panel is open and the user presses Escape or clicks outside it
- **THEN** the panel closes

#### Scenario: Sign out
- **WHEN** the user chooses sign-out
- **THEN** the session ends and the login page is shown

#### Scenario: Menu hidden when auth disabled
- **WHEN** `/auth/config` reports auth disabled
- **THEN** no user menu is rendered
