/**
 * @fileoverview Mapper between the Flows API wire type and internal UI types.
 *
 * This is the **only** place in the codebase that knows about `Flow` field names
 * from the API response. All components, slices, and selectors work with
 * {@link FlowRow} exclusively.
 *
 * If the backend renames a field (e.g. `flow_id` → `id`), only this file changes.
 *
 * Public API:
 * - {@link fromResponse}     — `Flow` → `FlowRow`  (list + single-flow responses)
 * - {@link toCreateRequest}  — form values + definition → `POST /api/flows` body
 * - {@link toPatchRequest}   — edit-modal values → `PATCH /api/flows/:id` body
 *
 * Follows the same structure as `project-mapper.ts`.
 */

import type { Flow, CreateFlowFormValues } from '@/types';
import type { FlowRow, FlowRunStatus } from '@/types/projects';
import type { FlowDefinition, JobRunSummary } from '@/types/flow';
import { ERROR_STATUSES, WARNING_STATUSES, RUNNING_STATUSES } from '@/constants/flowStatus';

// ── Private helpers ───────────────────────────────────────────────────────

/**
 * Converts a {@link JobRunSummary} into the {@link FlowRunStatus} shape used by
 * {@link FlowsTable}. Returns null when the summary is absent (flow never run).
 *
 * The mapping from API status strings to UI categories:
 * - errors   → Failed, Aborted, Failing
 * - warnings → CompletedWithWarnings, CompletedWithErrors
 * - running  → Queued, Pending, Starting, Running, Resuming, Paused, Canceling
 */
function toRunStatus(summary: JobRunSummary | null | undefined): FlowRunStatus | null {
  if (!summary || summary.total_runs === 0) { return null; }
  const counts = summary.status_counts ?? {};
  let errors = 0;
  let warnings = 0;
  let running = 0;
  for (const [status, count] of Object.entries(counts)) {
    if (ERROR_STATUSES.has(status))   { errors   += count; }
    if (WARNING_STATUSES.has(status)) { warnings += count; }
    if (RUNNING_STATUSES.has(status)) { running  += count; }
  }
  return { errors, warnings, running };
}

// ── Public mappers ────────────────────────────────────────────────────────

/**
 * Converts a raw {@link Flow} API response object into a {@link FlowRow} suitable
 * for display in `FlowsTable`, `ProjectDetail`, and `FlowDetail`.
 *
 * - `run_count` is read from `job_run_summary.total_runs`. Defaults to `null` when
 *   the summary is absent (flow never run, or fetched via `GET /api/flows/:id`).
 * - `run_status` is derived from `job_run_summary.status_counts` via {@link toRunStatus}.
 *   Defaults to `null` when there are no runs.
 * - Timestamps are stored as raw ISO 8601 strings; format at the render site via
 *   `new Date(ts).toLocaleDateString()`.
 *
 * @param flow - Raw `Flow` object from the API response.
 * @returns A {@link FlowRow} ready for the Redux `flow.items` map.
 */
export function fromResponse(flow: Flow): FlowRow {
  const summary = flow.job_run_summary;
  return {
    flow_id:    flow.flow_id ?? '',
    project_id: flow.container_id ?? '',
    name:        flow.name ?? '',
    description: flow.description ?? '',
    run_count:   summary?.total_runs ?? null,
    run_status:  toRunStatus(summary),
    tags:        flow.tags ?? [],
    created_on:  flow.created_on  ?? '',
    modified_on: flow.modified_on ?? '',
    created_by:  flow.created_by ?? null,
  };
}

/**
 * Converts {@link CreateFlowFormValues} (from `CreateFlowTearsheet`) into a
 * `POST /api/flows` request body.
 *
 * The `definition` is built by `buildFlowDefinition()` in `lib/helpers/flow.ts`
 * and must be passed in — this mapper does not construct it.
 *
 * @param values      - Validated form values from the Create Flow modal.
 * @param containerId - UUID of the project that will own this flow.
 * @param definition  - Initial Elyra pipeline definition blob from `buildFlowDefinition`.
 * @returns A `Pick<Flow, ...>` body ready to POST to the BFF.
 */
export function toCreateRequest(
  values: CreateFlowFormValues,
  containerId: string,
  definition: FlowDefinition
): Pick<Flow, 'container_id' | 'container_kind' | 'name' | 'description' | 'tags' | 'definition'> {
  return {
    container_id:   containerId,
    container_kind: 'project',
    name:           values.name,
    description:    values.description || undefined,
    tags:           values.tags,
    definition,
  };
}

/**
 * Converts an edit-modal update shape into a `PATCH /api/flows/:id` request body.
 *
 * Only the fields present in `updates` are sent — omitted fields are left
 * unchanged on the backend. All callers (`ProjectDetail`, `FlowDetail`) go through
 * this function so that if the PATCH contract changes, only this file needs updating.
 *
 * An empty `description` string is sent as `undefined` (omitted from the body)
 * so the backend treats it as "no change" rather than an explicit clear.
 *
 * @param updates - The edited name, description, and tags from {@link EditDetailsModal}.
 * @returns A `Pick<Flow, 'name' | 'description' | 'tags'>` body ready to PATCH.
 */
export function toPatchRequest(
  updates: { name: string; description: string; tags: string[] }
): Pick<Flow, 'name' | 'description' | 'tags'> {
  return {
    name:        updates.name,
    description: updates.description || undefined,
    tags:        updates.tags,
  };
}

/**
 * @deprecated Use {@link fromResponse} instead.
 * Retained as a re-export alias while any remaining callers are migrated.
 * Will be removed once no imports of `flowResponseToRow` remain.
 */
export const flowResponseToRow = fromResponse;
