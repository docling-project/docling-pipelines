# Design

## Context

See `proposal.md — Why` for motivation. Five existing page components are being formalized. All implementation already exists; this change only adds OpenSpec artifacts. See `proposal.md — Impact` for the source files.

## Goals / Non-Goals

**Goals:**
- Translate the five page implementations into versioned OpenSpec capability specs so future changes have formal behavioral contracts to modify.
- Mirror the pattern established by the `canvas-page` capability.

**Non-Goals:**
- Refactoring or modifying any page component.
- Documenting internal implementation details (hook internals, Redux slice shapes, Carbon component props) — those belong in source comments or a developer reference, not in behavioral specs.
- Introducing any new page behavior.

## Decisions

**One capability per page, flat path layout**
Each page has a single top-level TSX file. The spec mirrors that boundary. Flat paths (`home-page`, `projects-page`, etc.) follow the same pattern as `canvas-page` and avoid introducing a domain nesting level the project does not yet have.

**Runs kept out of the spec for `flow-detail-page`**
Job run rows are held in local component state (not Redux) by design. The spec describes the observable behavior (load, refresh, cancel, delete, view) without prescribing the storage mechanism, so a future refactor to Redux would not require a spec change unless the behavior itself changes.

**`run-details-page` flow snapshot requirement is explicit**
The requirement that the canvas renders the snapshot definition (not the live flow) is observable behavior that downstream consumers rely on — it is not an implementation detail. It is specified explicitly.

## Risks / Trade-offs

- **Spec drift across six capability specs**: Home, Projects, ProjectDetail, FlowDetail, RunDetails, and Canvas all have specs now. Future Canvas changes (e.g. changes to how `handleStop` works) that affect `run-details-page` behavior must update both specs. The OpenSpec change workflow enforces delta specs when a capability is declared as modified.
- **Scope gaps**: Internal routing helpers, mapper functions, and Carbon component configurations are intentionally excluded. Any change that alters externally observable behavior (e.g. changing where "Run again" navigates) must raise a spec change.
