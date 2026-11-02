# home-page Specification

## Purpose

The home-page capability is the product landing page that orients users with a welcome banner, quick-start tiles, a recently-visited navigation bar, and a grid of recent-work summary cards for projects, flows, and runs.

## Requirements

### Requirement: Welcome banner with theme-aware animation
The page SHALL render an animated welcome banner (`AnimatedHeader`) that adapts to the active colour theme. In dark mode (`g100`) it SHALL use the dark animation and static assets; in light mode it SHALL use the light variants.

#### Scenario: Dark mode banner
- **WHEN** the active theme is `g100`
- **THEN** `AnimatedHeader` receives the dark animation and static assets

#### Scenario: Light mode banner
- **WHEN** the active theme is not `g100`
- **THEN** `AnimatedHeader` receives the light animation and static assets

### Requirement: Quick-start tiles
The page SHALL display a "Quick start" tile group inside the animated header containing at least two tiles: a "Sample project" tile that opens the sample project modal, and a "Learn more" tile that links externally to the product documentation repository.

#### Scenario: Sample tile opens modal
- **WHEN** the user clicks the "Start" button on the sample project tile
- **THEN** `SampleProjectModal` opens

#### Scenario: Sample modal success navigates to new project
- **WHEN** `SampleProjectModal` reports success with a URL
- **THEN** the modal closes and the router navigates to that URL

#### Scenario: Learn more tile links externally
- **WHEN** the user clicks the "Learn more" button on the learn tile
- **THEN** the browser navigates to the external product documentation URL (no modal)

### Requirement: Recently-visited navigation bar
The page SHALL display a "Recently visited" bar showing up to four chips linking to recently opened projects and flows. The bar SHALL be hidden when no recent items exist. The primary source SHALL be the localStorage LRU list ordered most-recently-opened first. When the LRU list is empty the page SHALL fall back to API data (projects and flows already in the Redux store), sorted by `modifiedOn` descending.

#### Scenario: Bar hidden when no recent items
- **WHEN** the localStorage LRU list is empty and the Redux store has no projects or flows
- **THEN** the recently-visited bar is not rendered

#### Scenario: LRU order when history exists
- **WHEN** the user has visited items and the LRU list has entries
- **THEN** the chips are ordered by most-recently-opened and capped at four

#### Scenario: API fallback on first visit
- **WHEN** the LRU list is empty but the Redux store contains projects and flows
- **THEN** chips are derived from those items, sorted by `modifiedOn` descending, capped at four

#### Scenario: Each chip navigates to the correct route
- **WHEN** the user clicks a project chip
- **THEN** the router navigates to the project detail page for that project

### Requirement: Recent-work card grid
The page SHALL render a card grid in the "Recent work" zone containing `ProjectsCard`, `FlowsCard`, and `RunsCard`. The grid SHALL be visible regardless of recent-visit state.

#### Scenario: All three cards rendered
- **WHEN** the home page mounts
- **THEN** `ProjectsCard`, `FlowsCard`, and `RunsCard` are all present in the DOM

### Requirement: Recent-work card data and navigation
The `ProjectsCard`, `FlowsCard`, and `RunsCard` on the home page SHALL render the most recent items (up to 5 each), displaying item title, modification timestamp, status badges, and empty-state placeholders when no items exist, navigating directly to the selected item upon clicking.

#### Scenario: Clicking card item navigates to detail view
- **WHEN** the user clicks an item inside `ProjectsCard` or `FlowsCard`
- **THEN** the router navigates to `/projects/:id` or `/flows/:id` respectively

#### Scenario: Empty card renders placeholder and call-to-action
- **WHEN** no projects or flows exist in the system
- **THEN** the corresponding card displays an empty state message and a creation action button

### Requirement: Sample project bootstrap workflow
The `SampleProjectModal` triggered from the quick-start tiles SHALL provision a pre-configured sample project and starter pipeline flow, closing the modal and navigating directly to the generated project upon successful creation.

#### Scenario: Sample project creation initializes starter pipeline
- **WHEN** the user confirms sample project creation in the modal
- **THEN** the system generates the sample project with example flows, displays a success notification, and navigates to the project view
