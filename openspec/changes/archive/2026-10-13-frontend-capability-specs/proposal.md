# Proposal

## Why

The current frontend OpenSpec documentation has structural fragmentation and capability gaps. Operator configuration is fragmented across seven separate spec files while omitting the three most complex operator panels (AnnotationFilter, Merging, StorageOutput). Key application-level capabilities (Navigation & Routing, API Client boundary) lack behavioral contracts, and core integrations (Elyra canvas, Home page) are underspecified. Formalizing these capabilities establishes durable contracts that prevent regressions.

## What Changes

- Consolidate operator configuration into `frontend/properties-panel` with a unified 5-step lifecycle pattern and explicit sections for notable deviations (including AnnotationFilter condition builder, Merging live enrichment/preview, and StorageOutput multi-provider backend).
- Create `frontend/navigation` capability spec contracting the `/ui` router basename, dynamic breadcrumb generation, `project_id` query parameter back-navigation convention, and localStorage LRU cache.
- Create `frontend/api-client` capability spec contracting base URL resolution, API error normalization into Redux payloads, response mapping, and request headers.
- Expand `frontend/elyra-canvas` with palette categorization, toolbar actions, canvas grid/zoom settings, node card rendering, and context menu handlers.
- Expand `frontend/home-page` with recent-work card item contracts, empty states, and sample project bootstrap workflows.
- Add accessibility requirements (keyboard navigation, ARIA roles, focus management) across interactive surfaces.
- Add source mapping sections to facilitate staleness tracking and cross-spec navigation.

## Capabilities

### New Capabilities

- `frontend/navigation`: Application routing and navigation infrastructure — `/ui` router basename, `project_id` query parameter preservation for back-navigation, dynamic breadcrumbs with `BreadcrumbActionsContext`, `useRecentlyVisited` localStorage LRU cache, and lazy load module boundaries.
- `frontend/api-client`: Frontend-backend API communication boundary — base URL resolution (BFF proxy vs direct API), HTTP error normalization into Redux-compatible error objects, endpoint constants, and transaction/auth header injection.

### Modified Capabilities

- `frontend/properties-panel`: Unify operator configuration into the 5-step metadata-driven lifecycle pattern, add contracts for AnnotationFilter, Merging, and StorageOutput deviations, and contract required parameter validation gating.
- `frontend/elyra-canvas`: Expand requirements to cover palette category grouping, toolbar button states, canvas layout and zoom behavior, `CardNodeWrapper` visual structure, and node/canvas context menu handlers.
- `frontend/home-page`: Expand requirements to contract `ProjectsCard`, `FlowsCard`, and `RunsCard` data models and click interactions, card empty states, and `SampleProjectModal` provisioning workflows.

## Impact

- Adds new capability specs under `specs/frontend/navigation/` and `specs/frontend/api-client/`.
- Updates modified capability specs for `frontend/properties-panel/`, `frontend/elyra-canvas/`, and `frontend/home-page/`.
- No runtime application code changes — documentation and behavioral contract formalization only.

## Non-goals

- Does not modify frontend or backend runtime code.
- Does not change API payload schemas or backend database models.
- Does not introduce new UI components or redesign existing panels.

## Scope

Frontend-only.
