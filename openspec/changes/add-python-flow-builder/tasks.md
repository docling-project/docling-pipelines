# Tasks

Each tracked task is scoped to at most two hours. Tests and documentation land with the corresponding behavior. No frontend work or new dependency is planned.

## 1. Pure configuration foundations

- [ ] 1.1 [backend] Add strict configuration primitives, reference-aware field types, and redacted path-based diagnostics; verify unit tests reject bool-as-int, coercion, unknown keys, and multiple invalid fields without exposing secrets. (2h)
- [ ] 1.2 [backend] Add detached explicit-field serialization and effective-config merging for recognized globals and node overrides; verify omitted defaults, explicitly supplied defaults, nested copies, and unknown-global-key tests. (2h)
- [ ] 1.3 [backend] Add pure schema/feature registration hooks and resolution by selected operator identity, preserving existing factory priority; verify custom overrides, disabled custom loading, and schema-less warnings with registry tests. (2h)
- [ ] 1.4 [backend] Document schema extension, provider passthrough, inheritance, and deferred-reference rules in a focused section of the custom-operator guide; verify examples against fixture schemas and all relative links. (1h)

## 2. Source and extraction configuration contracts

- [ ] 2.1 [backend] Add Ingest top-level configuration and pure filesystem/web source validation, moving path availability checks to execution; verify invalid fields fail statically while absent local paths can be authored. (2h)
- [ ] 2.2 [backend] Adapt S3/IBM COS and Google Drive source schema discovery without constructing adapters; verify required parameters, aliases, literal errors alongside references, and runtime credential checks. (2h)
- [ ] 2.3 [backend] Adapt SharePoint/OneDrive source schemas and pure discovery; verify nested configuration errors and valid existing fixtures. (2h)
- [ ] 2.4 [backend] Adapt Box/Dropbox and existing custom source configuration contracts; verify current aliases, extension behavior, and no network/path probes during authoring. (2h)
- [ ] 2.5 [backend] Add Extract text configuration covering current Docling library/serve options, OCR, formats, and provider selection; verify parity with current extraction fixtures and no converter initialization. (2h)
- [ ] 2.6 [backend] Add pure schemas for current standard/VLM/ASR extraction options and declared incompatible combinations; verify existing option fixtures and no model imports/downloads. (2h)
- [ ] 2.7 [backend] Add Extract entity configuration and current provider contracts; verify nested provider errors, output options, references, and existing entity extraction examples. (2h)
- [ ] 2.8 [backend] Add ACL configuration and document the source-metadata dependency; verify boolean validation and static required-feature checks using fixtures. (1h)
- [ ] 2.9 [backend] Update ingestion/extraction parameter reference examples to match shared schemas; verify current documented keys and aliases using schema-only tests without accessing sources. (1h)

## 3. Functional and quality configuration contracts

- [ ] 3.1 [backend] Add Chunker configuration for simple/hybrid modes and pure size/overlap relationships; verify boundary, enum, inheritance, and bool-as-int tests against existing chunker semantics. (2h)
- [ ] 3.2 [backend] Add semantic chunker and summarization nested configuration; verify thresholds, provider options, references, and no model initialization. (2h)
- [ ] 3.3 [backend] Add Embeddings configuration and pure LiteLLM/Watsonx/HuggingFace provider contracts; verify passthrough, required provider settings, output-column naming, and current embedding fixtures. (2h)
- [ ] 3.4 [backend] Add Branching, Branch, and Merge configurations in authoring format; verify predicates, empty fan-out branches, merge choices, and compiler-generated input-link compatibility. (2h)
- [ ] 3.5 [backend] Add Noop and EntityCuration configurations and keep DocIdHash internal; verify schema exports, known parameter errors, and entity-schema dependencies using fixtures. (1h)
- [ ] 3.6 [backend] Add DocumentClassifier configuration and pure provider selection; verify confidence range, document-type mapping/list forms, and current classification examples. (2h)
- [ ] 3.7 [backend] Add PIIAndHAP configuration including independent PII/HAP providers and redaction settings; verify provider fallback, threshold boundaries, Presidio restrictions, and current fixtures. (2h)
- [ ] 3.8 [backend] Add DocQuality, LanguageDetect, and Readability configurations; verify actual source defaults, supported metric/provider choices, and static validation without language-model initialization. (2h)
- [ ] 3.9 [backend] Add Redaction, ExactDedup, MLEnrichment, and SQLFilter configurations; verify regex/filter errors, required features, legacy unsupported-key rejection, and no NLTK downloads during authoring. (2h)
- [ ] 3.10 [backend] Update functional/quality parameter reference sections and schema-only example fixtures; verify documented parameters and defaults agree with the new schemas. (1h)

## 4. Destination configuration contracts and catalog coverage

- [ ] 4.1 [backend] Add VectorDB and OpenSearch configuration including mappings and provider resource settings; verify required index configuration and static validation without a client or index operation. (2h)
- [ ] 4.2 [backend] Add Milvus provider configuration and supported aliases using existing schema contracts; verify collection settings, passthrough policy, and existing vector-store fixtures. (2h)
- [ ] 4.3 [backend] Add DocumentSet and StorageOutput mode/format/structure configurations; verify current mode-required fields and table-column prerequisites. (2h)
- [ ] 4.4 [backend] Adapt filesystem and S3/IBM COS destination schemas for pure inspection; verify source references and destination path checks remain deferred to execution. (2h)
- [ ] 4.5 [backend] Adapt existing SharePoint/OneDrive/Google Drive/Box/Dropbox destination schema discovery; verify alias-specific schema selection and nested errors using current fixtures. (2h)
- [ ] 4.6 [backend] Expose lightweight `docpipe.config` imports and add the 21-public-operator coverage matrix; verify optional runtime packages can be absent and `doc_id_hash` has no public typed export. (2h)
- [ ] 4.7 [backend] Update storage/vector-store parameter reference examples and migration notes for stricter fields; verify schema-only fixture parity and links without updating CHANGELOG.md. (1h)

## 5. Shared static validation and metadata

- [ ] 5.1 [backend] Add the pure flow parameter validation service with normalized diagnostic aggregation and partial-editor mode; verify effective settings, reference deferral, and no runtime constructors using spies. (2h)
- [ ] 5.2 [backend] Extract pure input/output feature resolution for ingestion, extraction, embeddings, and chunking; verify propagation fixtures match current metadata, including configured column names. (2h)
- [ ] 5.3 [backend] Extract pure branch/merge and quality/functional feature checks; verify missing filter columns, join keys, merge schema compatibility, and overlapping branch fixtures. (2h)
- [ ] 5.4 [backend] Extract pure storage/vector/ACL feature checks and wire static validation through FlowValidator; verify existing DAG constraints, terminal warnings, and custom coverage warnings without constructing operators. (2h)
- [ ] 5.5 [backend] Derive representable parameter metadata from shared schemas while preserving labels/features and availability; verify existing metadata DTO shape, internal filtering, provider defaults, and schema agreement tests. (2h)
- [ ] 5.6 [backend] Document static versus execution validation and custom coverage limits in the reference; verify examples demonstrate warnings separately from errors and preserve existing message codes. (1h)

## 6. Entrypoint and execution integration

- [ ] 6.1 [backend] Route manager and CLI validation through the pure service while preserving existing result dictionaries and exit behavior; verify focused manager/CLI tests, offline paths, and missing-provider diagnostics. (2h)
- [ ] 6.2 [backend] Integrate shared schemas into REST authoring/Elyra validation and metadata services; verify HTTP envelopes, node/field errors, no persistence, and equivalent Python/JSON/Elyra fixtures. (2h)
- [ ] 6.3 [backend] Preserve feature-enrichment tolerance for incomplete editor flows using the pure path; verify warnings, partial enrichment, and request deep-copy tests. (2h)
- [ ] 6.4 [backend] Add parameter preflight after cancellation and before runtime resource initialization; verify invalid parameters fail before adapters, graph-validation bypass retains parameter checks, and cancelled runs skip preflight. (2h)
- [ ] 6.5 [backend] Revalidate resolved references and retain resource availability/runtime checks; verify referenced type errors, redacted failures, missing-source runtime errors, and schema-less custom hooks. (2h)
- [ ] 6.6 [backend] Update validation documentation for the stricter behavior and graph-bypass distinction; verify documented CLI/REST cases against entrypoint tests. (1h)

## 7. Public Python flow authoring

- [ ] 7.1 [backend] Add Flow/OperatorSpec node storage and lightweight public exports with detached configuration snapshots; verify duplicate names, optional imports, fluent returns, and caller-mutation isolation. (2h)
- [ ] 7.2 [backend] Implement atomic connect/connect_chain with named-output and graph checks; verify unknown nodes/outputs, duplicate edges, cycles, self-edges, and failed-chain rollback. (2h)
- [ ] 7.3 [backend] Implement authoring dictionary import/export and preserve explicit flow IDs through AuthoringFlow; verify JSON round trips, references, deterministic order, inheritance, and compiler branch/merge links. (2h)
- [ ] 7.4 [backend] Add validation report/raise_for_errors and connect Flow.validate to static services; verify error aggregation, warning-only validity, missing features, and no runtime resource access. (2h)
- [ ] 7.5 [backend] Delegate execution and metadata/log retrieval to DocpipeFlowManager with existing options and custom packages; verify manager call arguments, deep copies, micro-batching defaults/overrides, and repeated execution isolation. (2h)
- [ ] 7.6 [backend] Add generic custom-component authoring with selected schema resolution; verify custom built-in overrides, schema-less coverage warnings, disabled-custom behavior, and factory priority. (2h)
- [ ] 7.7 [backend] Create `docs/guides/PROGRAMMATIC_FLOW_AUTHORING_GUIDE.md` with the public API and configuration examples for all 21 public components; verify every example via schema-only fixtures and exclude internal DocIdHash from the public catalog. (2h)
- [ ] 7.8 [backend] Add linear output/vector-store, conditional branch/row merge, and dual-embedding/column merge examples and link the guide from existing documentation; verify exports compile and offline test fixtures exercise each graph. (2h)

## 8. Integration verification

- [ ] 8.1 [backend] Run differential builder-versus-dictionary execution tests using local fixtures and stubbed expensive services; verify equivalent table schemas/content/metadata, independent branch matches, duplicate-ID row rejection, both column join modes, and separate output leaves. (2h)
- [ ] 8.2 [backend] Run cross-surface validation parity and resource-side-effect tests across public schemas, metadata, CLI, manager, REST, and configuration imports; verify literal/reference combinations, globals, aliases, provider passthrough, and partial editor flows. (2h)
- [ ] 8.3 [backend] Activate the venv and run focused existing manager/compiler/config/operator/API tests plus affected backend regressions; verify failures introduced by strict validation are corrected or documented without changing runtime algorithms. (2h)
- [ ] 8.4 [backend] Run required backend Ruff/mypy checks and a wheel build using the existing project tooling; verify public imports and guide examples from the built package and record unrelated baseline failures separately. (2h)
- [ ] 8.5 [backend] Run `openspec validate add-python-flow-builder --strict`, verify documentation links and catalog coverage, and review the final diff for scope; verify no main specs, archived changes, frontend files, or CHANGELOG.md were modified. (1h)

## Workflow follow-up

- Review the planning artifacts before explicitly starting the apply workflow.
- After implementation review and tests pass, archive through the OpenSpec archive workflow; do not edit main specs directly.
- If committing/pushing is subsequently requested, use signed-off commits and the prescribed branch-diff pre-commit checks; do not run pre-commit with `--all-files`.
