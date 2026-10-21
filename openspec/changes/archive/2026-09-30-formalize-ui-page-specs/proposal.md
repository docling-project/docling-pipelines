# Proposal

## Why

Five frontend pages — Home, Projects, ProjectDetail, FlowDetail, and RunDetails — have no formal behavioral specification in OpenSpec. Formalizing them now establishes durable contracts for every future change that touches these pages, mirrors the pattern established by the `canvas-page` capability, and ensures the full set of first-class UI pages is covered.

## What Changes

- Introduce five new capability specs derived from the existing implementation files.
- No production code changes — this is a documentation-only formalization.

## Capabilities

### New Capabilities

- `home-page`: The product landing page. Covers the animated welcome banner, quick-start tiles, recently-visited chips (localStorage LRU with API fallback), recent-work card grid, and sample project modal.
- `projects-page`: The top-level projects list page. Covers three render states (loading skeleton, empty state, table), project CRUD (create via tearsheet, edit, delete), and the two-zone layout.
- `project-detail-page`: The per-project detail page at `/projects/:projectId`. Covers project header (collapsible description/meta/tags), flows table with CRUD, project/flows bootstrap fetches, recently-visited recording, and flow count synchronisation.
- `flow-detail-page`: The per-flow run history page at `/projects/:projectId/:flowId`. Covers run metrics tiles, runs table (with cancel/delete/view), flow info side panel, edit-details modal, breadcrumb ⓘ button injection, and bootstrap fetches for flow and project.
- `run-details-page`: The standalone run viewer page at `/flows/:flow_id/runs/:run_id`. Covers flow-definition snapshot fetch, poller bootstrap, run-again and stop handlers, loading/error guards, and cleanup on unmount.

### Modified Capabilities

*(none — no existing specs to modify)*

## Impact

- Adds five new spec files under `openspec/specs/`.
- Implementation references: `frontend/src/pages/Home/Home.tsx`, `frontend/src/pages/Projects/Projects.tsx`, `frontend/src/pages/ProjectDetail/ProjectDetail.tsx`, `frontend/src/pages/FlowDetail/FlowDetail.tsx`, `frontend/src/pages/RunDetails/RunDetails.tsx`.
- Future changes that modify any of these pages must declare the corresponding capability as modified and provide a delta spec.
