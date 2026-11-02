# Proposal

## Why

The Canvas page (`Canvas.tsx`) is the most complex page in the frontend — 1673 lines spanning pipeline editing, save/run flows, branching logic, background polling, and overlays — with no formal specification in OpenSpec. Formalizing it now establishes a durable behavioral contract and a reference point for every future change that touches the pipeline editor.

## What Changes

- Introduce a new `canvas-page` capability spec derived from the existing `CANVAS_PAGE_SPEC.md` developer document.
- No production code changes — this is a documentation-only formalization.

## Capabilities

### New Capabilities

- `canvas-page`: The pipeline editor page. Covers the two visual modes (edit / run), state management, data loading effects, save and run flows, node properties panel, branching/link condition system, background job run polling, node suggestion, flow run properties, notification panel system, and all overlay components.

### Modified Capabilities

*(none — no existing specs to modify)*

## Impact

- Adds `openspec/specs/canvas-page/spec.md` (new file, no code touched).
- `frontend/src/pages/Canvas/Canvas.tsx` and its co-located files are the primary implementation reference.
- Future changes that modify Canvas page behaviour must declare `canvas-page` as a modified capability and provide a delta spec.
