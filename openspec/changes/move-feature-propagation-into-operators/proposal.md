# Proposal

## Why

`FeaturePropagator._apply_special_case_logic()` hard-codes per-operator behavior behind an `if/elif` chain on
`operator_short_name` (Extract, Embeddings, SQLFilter, Merge). Two more name checks live next to it
(`propagate_features()` for VectorDB, `_propagate_global_params()` for Embeddings), and `FlowValidator` has a Merge
branch of its own. Every new operator that changes the feature set (including custom operators) forces an edit to
this generic engine, and the operator's behavior is split between its own class and the propagator. Moving the logic
onto the operator classes gives each operator one home for its behavior and makes the propagator operator-agnostic.

## What Changes

- Add two default no-op class-level hooks on `AbstractOperator`: `propagate_features(...)` (adjust the node's feature
  metadata) and `get_global_params(...)` (publish flow-wide parameters), plus a `produces_output_features` class
  attribute (default `True`) for terminal operators. The hooks are `@classmethod`s so they run without
  instantiating the operator, which keeps untrusted custom-operator descriptors from ever being imported or built
  during validation.
- Move the existing special-case logic out of `FeaturePropagator` into the owning operators:
  - `ExtractOperator`: entity feature add/remove from `entity_extraction.provider`.
  - `EmbeddingsOperator`: `vector_binary` typing and description from `quantization`, and the `embeddings_model_id`
    global parameter.
  - `SQLFilterOperator`: `features_to_drop` removal and mandatory-feature rejection.
  - `MergeOperator`: parent feature merge using `merge_type`, `column_option` and `input_links`.
  - `VectorDBOperator`: `produces_output_features = False`.
- `OperatorMetadata` exposes the operator class resolved by the same factory that supplies its metadata, so the
  propagator sees built-in, priority-resolved and custom operators consistently.
- Extract the pure merge algorithm (`disambiguate_features` and the `merge_features` helpers) into a leaf module under
  `feature_propagation/` so `MergeOperator`, `FeaturePropagator`, `FlowValidator` and `FlowEnrichmentService` share it
  without import cycles. `FeaturePropagator.merge_features()` and `disambiguate_features` remain importable from their
  current locations.
- Share one "drop features, reject mandatory ones" helper between the SQLFilter hook and the generic
  `output_features_to_drop` handling.
- Remove `_apply_special_case_logic`, the `_apply_*_special_case` helpers and `_propagate_global_params` from
  `FeaturePropagator`.
- Document the new hooks in the custom operators guide.

Backend-only. No REST route, DTO, storage adapter, frontend, BFF or Redux change. Propagation results for every
existing operator and flow are unchanged. No **BREAKING** changes: operators that do not override the hooks behave as
they do today.

## Capabilities

### New Capabilities
<!-- None. -->

### Modified Capabilities
- `backend/flow-execution-engine`: adds the requirement that feature propagation is driven by operator-declared hooks
  rather than operator-name checks in the engine, and pins the existing per-operator propagation outcomes as
  scenarios so the move cannot regress them.

## Non-goals

- Changing any propagation outcome, validation error code or message text (including `MANDATORY_FEATURES_DROPPED`).
- Moving `FlowValidator._merge_parent_input_features()` onto the operator. It is the same pattern but touches
  validator snapshot semantics, so it is deferred to a follow-up change.
- Changing operator metadata shape, `OPERATORS.md` parameters, or the operators REST API payloads.
- Changing how `output_features_to_drop` is applied generically to all operators.
- Redesigning `OperatorFactory` priority or custom-operator loading.
- Allowing untrusted operators to run propagation code in the API process.

## Impact

- Code: `src/docpipe/core/operators/abstract_operator.py`, `operator_metadata.py`, the Extract, Embeddings, SQLFilter,
  Merge and VectorDB operator modules, `src/docpipe/core/orchestration/feature_propagation/` (`features_propagator.py`,
  `models.py`, new merge module, `__init__.py`), and import sites in `flow_validator.py` and
  `flow_enrichment_service.py`.
- Tests: `tests/unit/core/orchestrator/test_features_propagator.py` stays as the regression net (only its `OperatorMetadata` mock fixtures change, to return real operator classes from `get_operator_class`); per-operator hook
  tests and an extensibility test (a dummy operator needing no propagator edit) are added.
- Docs: `docs/guides/CUSTOM_OPERATORS_GUIDE.md`.
- Risk: import cycles between `abstract_operator`, `operator_metadata`, `operator_factory` and `feature_propagation`
  (mitigated in design.md).
