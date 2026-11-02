# Design

## Context

See `proposal.md — Why` for motivation. The existing implementation lives in `frontend/src/pages/Canvas/Canvas.tsx` (1673 lines) with a co-located `CANVAS_PAGE_SPEC.md` developer document that was the source of truth for the spec delta. No production code changes in this change.

## Goals / Non-Goals

**Goals:**
- Translate the existing `CANVAS_PAGE_SPEC.md` into a versioned OpenSpec capability so future changes have a formal behavioral contract to modify.

**Non-Goals:**
- Refactoring or modifying `Canvas.tsx`.
- Covering internal implementation details (class names, hook internals, Elyra API shapes) — those belong in `CANVAS_PAGE_SPEC.md`, which continues to serve as the low-level developer reference.
- Introducing any new canvas behavior.

## Decisions

**Single capability, flat path (`canvas-page`)**
The implementation is a single file; the spec mirrors that boundary. Splitting into sub-capabilities (e.g. `canvas-page/run-mode`, `canvas-page/branching`) would add organizational overhead with no benefit until the file itself is decomposed.

**Spec describes behavior, not internals**
`CANVAS_PAGE_SPEC.md` already documents the internal contract (state vars, ref names, Elyra config keys). The OpenSpec spec focuses on externally observable behavior — what users and downstream systems rely on — so the two documents complement rather than duplicate each other.

## Risks / Trade-offs

- **Spec drift**: `CANVAS_PAGE_SPEC.md` and `openspec/specs/canvas-page/spec.md` are now two representations of the same page. Future edits to Canvas must update both. Mitigation: the OpenSpec change workflow enforces a delta spec whenever `canvas-page` is declared as a modified capability.
- **Scope gaps**: The behavioral spec intentionally omits internal implementation details. Any refactor that changes observable behavior (e.g. different dirty-state semantics) must raise a change against `canvas-page`.
