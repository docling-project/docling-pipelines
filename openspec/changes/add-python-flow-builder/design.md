# Design

## Context

See [proposal.md](proposal.md) for motivation and scope. `DocpipeFlowManager` already accepts authoring dictionaries, compiles them with `AuthoringCompiler`, and exposes `validate()`/`execute()`. `AuthoringFlow` and `AuthoringOperator` are dataclasses that validate graph authoring structure. The compiler owns UUID generation, `operator.branch` references, and merge input-link generation. Reuse these contracts.

Current gaps are concrete:

- `validate_config_from_metadata()` checks presence, nested objects, and selected provider keys; it does not fully enforce scalar types, ranges, or enums.
- `FlowValidator` constructs operators with `validating_flow=True`. Some custom parameter checks are then skipped by `should_validate_field()`, while constructors can load models or instantiate adapters.
- Filesystem source config validation checks path existence; static schema reuse therefore needs a pure mode, not unconditional use of the existing validators.
- `AuthoringFlow.to_dict()` currently omits its optional flow ID. Round-trip support needs to preserve it without changing generated runtime-ID semantics.
- The actual registry has 22 classes: 21 public components plus internal `doc_id_hash`. Do not expose the internal class merely to match registry size.

Relevant existing tests include `tests/unit/test_docpipe_flow_manager*.py`, authoring model/compiler tests under `tests/unit/core/assets_management/`, and `tests/unit/utils/operators/test_config_validation.py`. Active source/extraction proposals overlap some provider config files; this change adds schemas for current behavior only.

## Goals / Non-Goals

**Goals:** One authoring representation, one set of parameter contracts, explicit graph wiring, offline authoring/validation, and execution through the existing manager. Preserve valid documented configurations and identify stricter validation failures clearly.

**Non-Goals:** New processing algorithms, adapter implementations, scheduling semantics, general workflow loops, first-match routing, frontend redesign, or global cleanup of legacy validation code.

## Decisions

### 1. A small public builder over the authoring model

Expose `Flow` and `OperatorSpec` from `docpipe`, and stable configuration classes from `docpipe.config`. Put the facade in `src/docpipe/lib/flow.py`, report types in the library layer, and shared schemas/services under `src/docpipe/core/operators/configuration/`. Import schema definitions without importing concrete runtime operators or adapters. Existing top-level imports may need lazy exports to avoid pulling runtime dependencies into configuration-only use.

Public shape:

```python
from docpipe import Flow
from docpipe import config as cfg

flow = Flow(
    name="prepare-documents",
    description="Docling extraction and output",
    global_config={"doc_column": "content"},
    custom_operator_packages=[],
    enable_custom_operators=True,
)
flow.add(
    name="source",
    operator=cfg.Ingest(
        provider="filesystem",
        provider_config={"paths": ["./documents"]},
    ),
)
flow.add(
    name="extract",
    operator=cfg.Extract(
        text_extraction={"provider": "docling_library"},
    ),
)
flow.add(
    name="output",
    operator=cfg.StorageOutput(
        mode="processed_content",
        destination_config={
            "provider": "filesystem",
            "provider_config": {"root_path": "./output"},
        },
    ),
)
flow.connect_chain(nodes=["source", "extract", "output"])
report = flow.validate()
report.raise_for_errors()
definition = flow.to_dict()
result = flow.execute()
```

Also support `Flow.from_dict(data=...)`, `Flow(flow_id=...)`, and `execute()` keyword options corresponding to current manager job IDs, reporting, and logging controls. Preserve metadata/log access through facade methods delegating to the most recent manager. Keep `DocpipeFlowManager` unchanged as a supported public entrypoint.

`add`, `connect`, and `connect_chain` return the flow for optional fluent usage. They validate candidate mutations before committing them, so invalid batch connections cannot leave partial state. Complete-flow constraints are deferred to `validate()`; intermediate builders can be incomplete. Unknown names and outputs, repeated edges, self-edges, and cycles fail immediately. Preserve current graph semantics for non-merge dependencies rather than introducing new implicit aggregation rules.

Alternative: directly instantiate existing operator classes as Haystack components. Rejected because their constructors take runtime dictionaries and can initialize resources; configuration objects give autocomplete without those side effects. A fluent-only pipeline chain is insufficient for branching.

### 2. Explicit public configuration classes with a shared schema registry

Use existing Pydantic v2 without a new dependency. Define explicit models and annotated fields rather than generating anonymous classes from incomplete metadata. Use strict scalar types, constrained numeric fields, enums, and validators for declared cross-field relationships. Reject bool-as-int. Closed authored objects forbid extra keys; provider-declared passthrough remains open where currently supported, notably LiteLLM. Retain existing aliases and normalization rather than imposing byte-for-byte string strictness on valid aliases.

Baseline exports:

| Public model | Operator short name |
| --- | --- |
| Ingest | ingest_source |
| Extract | extract_operator |
| ACL | acl_operator |
| DocumentClassifier | document_classifier |
| DocQuality | doc_quality |
| LanguageDetect | lang_detect |
| Readability | readability |
| Redaction | redaction |
| PIIAndHAP | pii_and_hap |
| ExactDedup | ededup |
| MLEnrichment | ml_enrichment |
| SQLFilter | sql_filter |
| Chunker | chunker |
| Embeddings | embeddings |
| EntityCuration | entity_curation |
| Branching | branching |
| Merge | merge |
| Noop | noop |
| VectorDB | vectordb |
| DocumentSet | document_set |
| StorageOutput | storage_output |

`Branch` is a nested configuration model, not an executable operator. Existing provider config models are reused after separating environment checks. Nested mappings are accepted and parsed by provider-specific schemas; model instances can be accepted too and serialize to the same dictionary. Preserve extraction's text/entity blocks, PII/HAP independent provider selection, chunker summarization, vector feature mappings, and output-format/structure settings.

Schema registration associates the selected operator class identity with its pure model and optional static feature resolver. Do not key extension schemas only by short name: overrides can have different contracts. Add an optional schema hook to the operator contract with a backward-compatible default of no schema; providers register their schema classes without adapter instantiation. Runtime factories keep priority resolution. Use lazy imports for schema discovery and optional providers.

Alternative: infer everything from `get_metadata()`. Rejected because hand-maintained metadata lacks several parameter and relationship constraints. Generate representable parameter metadata from schemas and preserve existing display/feature metadata as overlays; test consistency rather than maintaining two separate constraint sets.

### 3. Validate explicit settings first, effective settings in flow context

Models retain which fields users explicitly supplied. `to_dict()` exports detached explicit values, including an explicitly supplied default, so omitted defaults do not overwrite global inheritance. Typed construction checks local values and relationships with all known operands; flow validation merges recognized globals, node overrides, and defaults before checking contextual relationships. The same effective-config function serves dictionary, Elyra, Python, and execution paths.

Separate known flow-wide settings and compiler/runtime envelope fields from strict authored operator keys. Validate authored node dictionaries before injecting fields such as available features and generated merge links. Internally generated fields are an explicit trusted set, not a blanket exemption for unknown authored keys. Flow-global extension keys are allowed only when claimed by a selected extension; do not let arbitrary globals bypass typo detection.

Deferred secret references use the existing supported syntax, represented by a schema-level reference type without resolving their values. Validate literal fields normally; defer only checks depending on references. Resolve through the existing environment/vault path and revalidate the resolved effective config before use. Never include raw input values in secret-related diagnostics. Export preserves references for the caller's existing execution environment.

Alternative: materialize every default on model construction. Rejected because that would silently override inherited `doc_column` and other global settings. Blind Pydantic coercion would also hide user mistakes.

### 4. Separate static validation from runtime checks

Introduce a pure configuration validation service and an explicit static path in flow validation. Keep feature propagation on normalized dictionaries and static feature descriptors/resolvers, not operator instances. Migrate public built-in feature checks needed for the builder to pure functions; invoke existing runtime validation hooks only during execution. Legacy custom components without a pure schema/resolver receive a coverage warning and retain their runtime validation hooks. Missing runtime dependencies are reported separately from parameter validity.

Stages:

1. Typed construction: validate known authored values without resource access.
2. `Flow.validate()`, manager validation, CLI validation, REST validation: validate effective schemas, structural rules, and known input/output features without runtime constructors.
3. Execution: existing cancellation check first, pure parameter preflight next, secret resolution and deferred/environment checks before affected resources, then existing orchestrator execution. Mandatory parameter checks remain active when DAG validation is disabled.

Filesystem source existence, destination access, model availability, vector index compatibility, and network credentials remain execution concerns. Existing provider validators that perform these checks must be split or supplied with an explicit pure context that does not probe resources. Existing execution checks are retained. Do not promise that static success proves credentials or remote index compatibility.

Reports use a lightweight typed value with `valid`, `errors`, `warnings`, and `raise_for_errors()`. Diagnostics carry stable code, node name, and dotted parameter path; existing manager dictionaries, API DTO envelopes, and known codes such as `INGEST_PROVIDER_MISSING` are preserved through adapters. Warnings do not invalidate a report. Feature enrichment explicitly selects partial-flow tolerance.

Alternative: call `manager.validate()` unchanged from the builder. Rejected because it currently instantiates operators and skips some checks in flow-validation mode.

### 5. Reuse branch/merge authoring semantics

`cfg.Branching(branches={"english": cfg.Branch(filter_criteria_list=["lang_name = 'en'"])})` serializes to the current branch dictionary. `connect(source="route", output="english", target="chunk_en")` serializes as `depends_on=["route.english"]`. The compiler generates runtime branch IDs and input links. No runtime IDs leak into the Python API.

Conditional branches are independent filters; no first-match or implicit else behavior. Empty branches are unconditional copies. Branch predicates can leave rows unmatched. Row merging concatenates distinct IDs and retains runtime duplicate rejection; column merging joins on `id`, preserving current duplicate-column suffix behavior and nested-column handling. Recommend distinct embedding column names. Static checks catch missing join keys and known incompatible schemas, but data-dependent duplicates remain runtime errors. Separate output leaves require no merge. Preserve current terminal warnings.

Serialization round trips authoring semantics, not generated runtime UUIDs. Preserve an explicit flow ID and deterministic authoring node/edge order. `Flow.execute()` passes a deep copy to the manager because the existing compilation path mutates the input with `flow_source`. Keep the original builder and user's dictionaries untouched.

Alternative: implicit branching from an overloaded `>>` operator and automatic merges. Rejected to keep table routing and recombination visible and consistent with the visual/JSON representation.

### 6. Preserve architectural boundaries

Flow domain dataclasses remain framework-free and do not import concrete adapters or Pydantic configuration models. The library/application facade converts typed configs into plain authoring dictionaries. Pure configuration services receive schema/feature providers wired by factories. Runtime resource access stays in existing adapter ports and execution services. No changes to operator transform signatures, table schemas, or metrics are required.

No new REST routes or DTO shape changes. Existing metadata/validation service adapters consume shared schema results. No frontend components, Redux actions, BFF routes, or SCSS changes are involved.

## Risks / Trade-offs

- Stricter checks reject formerly ignored fields -> Explicit breaking-change notice, validated existing examples, documented aliases and provider passthrough; do not silently drop unknown settings.
- Provider/schema drift and evolving extraction features -> Schema-to-metadata tests, registry coverage tests, and coordination with active proposals; never implement their planned features here.
- Optional imports initialize resources -> Lazy schema imports and tests that fail if constructors, network, downloads, storage opens, or path probes are used during static operations.
- Inheritance/reference handling changes behavior -> Differential tests for omitted fields, explicit defaults, nested references, node overrides, and JSON/Elyra parity.
- Static feature extraction cannot prove dynamic extension behavior -> Explicit coverage warnings; retain runtime extension hooks and avoid falsely advertising full validation.
- Large catalog migration -> Implement operator families in small tasks with fixture parity before enabling the shared service across entrypoints.

## Migration Plan

Implement pure contracts and registry coverage first, then integrate validation and metadata, then expose the builder. Keep existing file/dictionary manager entrypoints and authoring JSON shape. Run focused compatibility tests and validate documented examples before enabling strict checks. Document corrected invalid configurations in the programmatic guide/reference; do not modify CHANGELOG.md.

No persistent data migration is needed. Rollback consists of reverting the new validation/builder integration; previously stored valid authoring dictionaries and runtime outputs remain usable. No dependency changes are planned; if implementation genuinely requires one, regenerate `uv.lock` and sync the venv according to repository policy.
