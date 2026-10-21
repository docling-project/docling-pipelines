# Spec Delta

## Purpose

The navigation capability provides the single-page application routing infrastructure, defining URL structure, the `/ui` router basename, `project_id` query parameter preservation for back-navigation, dynamic breadcrumb generation with action injection, localStorage LRU recently-visited history, and code-split route boundaries.

## ADDED Requirements

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
