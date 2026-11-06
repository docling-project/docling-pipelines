# Proposal

Feature tracking: [Issue #447](https://github.com/docling-project/docling-pipelines/issues/447). This PR introduces planning artifacts for review; implementation starts only after the OpenSpec review is complete. Merging the planning PR does not complete the feature issue.

## Why

Python users can execute dictionaries through `DocpipeFlowManager`, but must manually author operator dictionaries and dependency strings without parameter autocomplete or consistent early validation. A typed flow builder will make Docling-based document preparation and delivery to vector stores or output destinations usable directly from applications and notebooks.

## What Changes

- Add `Flow`, exported from `docpipe`, with typed node configuration, explicit connections, named branch outputs, merge inputs, chain connections, authoring-dictionary import/export, validation reports, and execution through the existing manager/compiler/runtime.
- Add `docpipe.config` with keyword-based configuration models for every public built-in operator and nested provider settings. Retain existing JSON parameter names, defaults, provider aliases, and documented passthrough settings.
- Add `OperatorSpec` for registered custom operators, preserving factory priority and optional custom schemas. Keep internal `doc_id_hash` unavailable as a public component.
- Share pure parameter validation across Python, CLI/JSON, REST validation, and execution preflight. Separate schema errors from upstream-feature checks and environment-dependent checks; construction and serialization perform no model loading, network access, or filesystem writes.
- Preserve conditional multi-match branches, unconditional fan-out, row concatenation with duplicate-ID rejection, and column merges on `id`. Generate branch identifiers and merge input links automatically.
- **BREAKING:** Configurations with previously ignored unknown authored operator keys, invalid scalar types, or invalid ranges will fail schema validation. Explicit provider passthrough fields, supported aliases, unresolved secret references, and runtime-injected settings remain supported. Document these stricter checks and corrective examples.
- Add a programmatic authoring guide and verified parameter examples for all public built-ins, including linear, conditional, and dual-embedding flows.

## Capabilities

### New Capabilities

- `backend/python-flow-authoring`: Python construction, connection, serialization, validation, and execution of document ingestion flows.
- `backend/operator-configuration`: Shared typed operator/provider schemas, catalog coverage, configuration diagnostics, and static validation without runtime initialization.

### Modified Capabilities

- `backend/flow-execution-engine`: Shared parameter preflight before operator initialization while preserving cancellation, graph-validation controls, and runtime table contracts.
- `backend/operators-api`: Schema-consistent operator metadata and parameter diagnostics through existing REST validation and metadata routes.

## Impact

Backend-only, plus documentation and examples. Likely implementation areas are `src/docpipe/lib/`, package exports, operator configuration/metadata services, `FlowValidator`, `FlowExecutor`, provider config models, and existing CLI/API validation services. Existing routes affected are `GET /api/v1/operators/metadata` and `POST /api/v1/validation/validate_flow`; no new routes are needed. Feature enrichment must continue tolerating incomplete editor flows.

No changes to `/ui` routing, BFF routes, Redux slices, Carbon components, or SCSS. No new vector-store/source adapters or dependency upgrades are required; Pydantic is already installed. Existing adapter schemas need pure-validation wrappers where they currently inspect the environment. Coordinate with in-flight extraction/source changes without implementing their features here.

## Non-goals

- General-purpose agent workflows, cyclic graphs, first-match routing, new scheduling/distribution semantics, or changes to document processing algorithms.
- Replacing Docling extraction, changing operator `transform()` signatures, changing PyArrow schemas/metadata, or implementing a second execution engine.
- Automatically deduplicating row merges, arbitrary join keys, automatic graph rewrites, or changing existing terminal-output warnings into errors.
- Publishing internal operators as public components, introducing a new visual editor, or modifying unrelated active OpenSpec changes.
