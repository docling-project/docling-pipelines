/**
 * Shared type definitions for the Projects domain.
 *
 * Covers API wire types (HTTP responses/requests), Redux state shapes,
 * and UI-specific types for the projects page and forms.
 */

// ── API wire types ───────────────────────────────────────────────────────

/**
 * A single project returned by the backend API.
 */
export interface ProjectResponse {
  project_id: string;
  name: string;
  description: string | null;
  tags: string[];
  flow_count: number;
  created_on: string;
  modified_on: string;
  created_by: string | null;
  modified_by: string | null;
  href: string | null;
}

/**
 * Paginated response envelope for project list operations.
 */
export interface PaginatedProjectResponse {
  projects: ProjectResponse[];
  total_count: number;
  offset: number;
  limit: number;
  first: string | null;
  next: string | null;
  prev: string | null;
}

/**
 * Request body for creating a project (POST /api/v1/projects).
 */
export interface ProjectCreateRequest {
  name: string;
  description?: string | null;
  tags?: string[];
  created_by?: string | null;
}

/**
 * Request body for fully replacing a project (PUT /api/v1/projects/:id).
 */
export interface ProjectUpdateRequest {
  name: string;
  description?: string | null;
  tags?: string[];
  modified_by?: string | null;
}

/**
 * Request body for partially updating a project (PATCH /api/v1/projects/:id).
 */
export interface ProjectPatchRequest {
  name?: string | null;
  description?: string | null;
  tags?: string[] | null;
  modified_by?: string | null;
}

// ── Domain model ──────────────────────────────────────────────────────────

/**
 * Internal domain representation of a project.
 *
 * This is the type used throughout the application — in Redux, selectors,
 * and components. It is derived from {@link ProjectResponse} via
 * `projectMapper.fromResponse` and uses camelCase field names so the
 * rest of the codebase is decoupled from the API wire format.
 *
 * If the backend renames a field, only `project-mapper.ts` needs to change.
 */
export interface Project {
  /** Unique project identifier (`project_id` on the wire). */
  id: string;
  /** Human-readable project name. */
  name: string;
  /** Optional free-text description, or null if not set. */
  description: string | null;
  /** Zero or more tag strings. */
  tags: string[];
  /** Number of flows belonging to this project. */
  flowCount: number;
  /** ISO 8601 creation timestamp. */
  createdOn: string;
  /** ISO 8601 last-modified timestamp. */
  modifiedOn: string;
  /** User who created the project, or null. */
  createdBy: string | null;
  /** User who last modified the project, or null. */
  modifiedBy: string | null;
}

// ── Redux state type ──────────────────────────────────────────────────────

/**
 * Redux state slice for managing projects.
 * Owned exclusively by `projectsSlice` and mounted at `state.projects`.
 * The `items` map stores the {@link Project} domain model — not the raw API response.
 */
export interface ProjectsState {
  /** Map of `project.id` → {@link Project} domain model. */
  items: Record<string, Project>;
  /** ID of the currently selected project, or null. */
  selectedProjectId: string | null;
  /** True while any projects API request is in-flight. */
  loading: boolean;
  /** Error message from the last failed projects API call, or null. */
  error: string | null;
}

// ── UI types ─────────────────────────────────────────────────────────────

/**
 * Form values for creating or editing a project.
 *
 * Used by both {@link CreateProjectTearsheet} (step 1) and {@link EditProjectModal}.
 */
export interface CreateProjectFormValues {
  /** Human-readable project name. Required — the Submit button is disabled until filled. */
  name: string;
  /** Optional free-text description of the project. */
  description: string;
  /** Zero or more tag strings to attach to the project. */
  tags: string[];
}

/**
 * A single row in the projects table.
 * Derived from {@link Project} via `toProjectRow` in `Projects.tsx`.
 * Carries only the display fields needed by the table — `description` is excluded
 * and read directly from the Redux store when needed (e.g. in {@link EditProjectModal}).
 */
export interface ProjectRow {
  /** Unique project identifier (e.g. `"proj-1"`). */
  id: string;
  /** Human-readable project name. */
  name: string;
  /** Free-text description, or null if not set. Not shown as a table column but
   *  carried on the row so the edit modal can pre-seed the field without touching Redux. */
  description: string | null;
  /** Number of flows belonging to this project. */
  flows: number;
  /** Zero or more tag strings attached to the project. */
  tags: string[];
  /** Display string for the last-modified date (e.g. `"06/04/23"`). */
  lastModified: string;
  /** ISO date string or raw timestamp for last-modified date sorting. */
  lastModifiedRaw?: string;
  /** Display string for the created-on date (e.g. `"04/05/26"`). */
  createdOn: string;
  /** ISO date string or raw timestamp for created-on date sorting. */
  createdOnRaw?: string;
  /** Username of the project creator; null or absent when the project has no owner. */
  createdBy?: string | null;
}

// ── Flow UI types ────────────────────────────────────────────────────────────

/**
 * Run status summary for a flow — counts of errors, warnings, and active runs.
 */
export interface FlowRunStatus {
  errors: number;
  warnings: number;
  running: number;
}

/**
 * A single row in the flows table on the ProjectDetail page.
 */
export interface FlowRow {
  /** Unique flow identifier. */
  flow_id: string;
  /** ID of the project that owns this flow (`container_id` on the wire). */
  project_id: string;
  /** Human-readable flow name. */
  name: string;
  /** Free-text description, or empty string if not set. */
  description: string;
  /** Total number of runs, or null if none yet. */
  run_count: number | null;
  /** Run status summary, or null if no runs yet. */
  run_status: FlowRunStatus | null;
  /** Zero or more tag strings. */
  tags: string[];
  /** Display string for the created-on date. */
  created_on: string;
  /** Display string for the last-modified date. */
  modified_on: string;
  /** Username of the flow creator; null or absent when the flow has no owner. */
  created_by?: string | null;
}
