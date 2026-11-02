# Proposal

## Why

The existing `openspec/specs/frontend/` covers the six top-level pages only. The frontend has a
large component tree — PropertiesPanel with 15+ operator CustomPanels, ReadOnlyCanvas,
ElyraCanvas, shared common components, and six Redux slices — all with no formal behavioral
contracts. Formalizing these now establishes durable specs that future changes must declare as
modified capabilities, preventing silent regressions.

## What Changes

- Introduce new capability specs for every major component group below.
- No production code changes — this is documentation-only formalization.

## Capabilities

### New Capabilities

- `frontend/properties-panel`: The operator configuration side panel — open/close behaviour,
  tab structure (Info, Features), and the contract between the canvas and each CustomPanel.
- `frontend/properties-panel/custom-panels/ingest-source-panel`: Configuration fields for the
  IngestSource operator (provider, connection params, filters).
- `frontend/properties-panel/custom-panels/extract-panel`: Configuration fields for the Extract
  operator (docling settings, provider config).
- `frontend/properties-panel/custom-panels/chunker-panel`: Configuration fields for the Chunker
  operator (chunk size, overlap, tokenizer settings).
- `frontend/properties-panel/custom-panels/embeddings-panel`: Configuration fields for the
  Embeddings operator (model, provider, batch settings).
- `frontend/properties-panel/custom-panels/branching-panel`: The link condition editor for the
  Branching operator — condition rows, logic operators, tearsheet flow.
- `frontend/properties-panel/custom-panels/vectordb-panel`: Configuration fields for the VectorDB
  operator — backend selection, feature mapping table, and enrichment tearsheet.
- `frontend/read-only-canvas`: The read-only pipeline viewer shown during and after a job run —
  node status rendering, polling, and top panel controls.
- `frontend/read-only-canvas/run-side-panel`: The slide-in panel during run view — node
  summary, job run logs, and tab switching.
- `frontend/elyra-canvas`: The interactive Elyra-based pipeline editor — node rendering, link
  condition tearsheet, and callback contracts with the canvas page.
- `frontend/common/shared-data-table`: The reusable paginated data table used across pages.
- `frontend/common/shared-tearsheet`: The base tearsheet wrapper used by all multi-step forms.
- `frontend/common/delete-modal`: The confirmation modal used for all delete actions.
- `frontend/common/create-project-tearsheet`: The new-project creation tearsheet.
- `frontend/common/flow-info-panel`: The slide-in panel showing flow metadata and run history.
- `frontend/common/vault-input`: The credential/secret input field with show/hide toggle.
- `frontend/state/flows-slice`: Redux slice managing flow entities and fetch lifecycle.
- `frontend/state/projects-slice`: Redux slice managing project entities and fetch lifecycle.
- `frontend/state/job-runs-slice`: Redux slice managing job run entities and status polling.
- `frontend/state/operators-slice`: Redux slice managing operator metadata.

### Modified Capabilities

*(none — no existing specs are modified)*

## Impact

- Adds 20 new `spec.md` files under `openspec/changes/formalize-frontend-component-specs/specs/frontend/`.
- No changes to `frontend/src/` — implementation files are read-only references.
- Future changes that touch any of these components must declare the relevant capability as
  a Modified Capability in their proposal.

## Non-goals

- Does not spec operator-specific business logic in the Python backend.
- Does not add tests or change any existing component behaviour.
- Does not cover every component in the tree — only those with non-trivial behavioral contracts.

## Scope

Frontend-only.
