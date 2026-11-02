# Design

## Context

The frontend architecture is built on React 18, TypeScript, Redux Toolkit, and Carbon Design System with Elyra Canvas for pipeline graph manipulation. The OpenSpec audit revealed that while page-level workflows are well-specified, core application infrastructure (navigation, API client boundary), complex custom operator panels (AnnotationFilter, Merging, StorageOutput), and graph engine integration details (Elyra canvas) lack formal behavioral contracts.

See `proposal.md` for motivation and scope.

## Goals / Non-Goals

**Goals:**
- Unify operator configuration specifications under `frontend/properties-panel` with a standardized 5-step metadata-driven lifecycle.
- Specify the contract for notable panel deviations: AnnotationFilter condition builder, Merging live enrichment/preview, StorageOutput multi-provider backend, VectorDB feature mapping, Embeddings dynamic model loading, Chunker hybrid mode coupling, and Branching read-only states.
- Formalize SPA navigation behavior (`/ui` basename, `project_id` query param back-navigation, breadcrumb context injection, LRU caching).
- Formalize frontend-backend communication contracts (base URL resolution, error normalization into Redux payloads, auth/transaction headers).
- Complete underspecified requirements in `frontend/elyra-canvas` and `frontend/home-page`.

**Non-Goals:**
- Modifying production React components or runtime logic.
- Rewriting backend operator endpoints or database schemas.

## Decisions

### Decision 1: Consolidated Properties Panel vs Individual Panel Specs
- **Choice**: Consolidate operator configuration contracts into `frontend/properties-panel` rather than maintaining separate specs for each operator panel.
- **Rationale**: 90% of operator panels follow an identical 5-step lifecycle (read appData -> load property values -> render fields -> validate and toggle save button -> persist property values). Deviations (AnnotationFilter, Merging, VectorDB) are explicitly documented as specialized requirements within the same capability.
- **Alternatives Considered**: Creating 20+ individual panel specs (rejected due to excessive redundancy and maintenance overhead).

### Decision 2: Distinct Navigation & API Client Capabilities
- **Choice**: Introduce `frontend/navigation` and `frontend/api-client` as distinct first-class capability specs.
- **Rationale**: Navigation conventions (such as `/ui` basename and `project_id` query parameter preservation) and API client conventions (error normalization and base URL resolution) are cross-cutting boundaries that protect against regressions across all pages.
- **Alternatives Considered**: Documenting routing and API client behavior inline within individual page specs (rejected due to duplication and fragmentation).

## Risks / Trade-offs

- **[Risk]** Spec delta bloat if every minor component detail is included.
  - **Mitigation:** Focus strictly on observable behavioral contracts and breakable conventions; omit trivial rendering details.
- **[Risk]** Divergence between spec contracts and future UI refactors.
  - **Mitigation:** Use strict validation (`openspec validate --strict`) and map requirements directly to observable user/data workflows.
