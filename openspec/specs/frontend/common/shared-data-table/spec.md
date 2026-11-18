# frontend/common/shared-data-table Specification

## Purpose
The shared-data-table capability is the reusable paginated data table used across the application for displaying lists of flows, projects, job runs, and other entities. It wraps Carbon's DataTable with built-in pagination, optional search filtering, optional toolbar left-slot content, and an empty state when search produces no results.

## Requirements

### Requirement: Paginated rows
The table SHALL paginate rows and show only the current page's subset when pagination is enabled (default).

#### Scenario: First page shown on mount
- **WHEN** the table renders with more rows than the initial page size
- **THEN** only the first page of rows is shown and a pagination control is rendered

#### Scenario: Pagination disabled shows all rows
- **WHEN** the paginated prop is false
- **THEN** all rows are shown without a pagination control

### Requirement: Client-side search filtering
When searchable is enabled, the table SHALL filter visible rows in real time based on the search input.

#### Scenario: Rows filtered by search term
- **WHEN** the user types in the search box
- **THEN** only rows whose searchable fields contain the search term are shown

#### Scenario: Empty state shown when no matches
- **WHEN** the search term matches no rows
- **THEN** a not-found empty state is shown instead of an empty table body

#### Scenario: Search resets to page one
- **WHEN** the search term changes
- **THEN** the visible page resets to page 1

### Requirement: Loading skeleton
The table SHALL show a DataTableSkeleton when loading is true.

#### Scenario: Skeleton shown while loading
- **WHEN** loading is true
- **THEN** the DataTableSkeleton is rendered instead of the table

### Requirement: Toolbar left slot
The table SHALL render caller-provided content at the left of the toolbar when renderToolbarLeft is supplied.

#### Scenario: Toolbar left content rendered
- **WHEN** renderToolbarLeft is provided
- **THEN** the returned content is shown at the left end of the toolbar
