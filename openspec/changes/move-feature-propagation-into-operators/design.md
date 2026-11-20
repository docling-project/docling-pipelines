# Design

## Context

See [proposal.md](proposal.md) for motivation and [specs](specs/backend/flow-execution-engine/spec.md) for the
behavior that must be preserved.

Current state, verified in the code:

- `FeaturePropagator.propagate_features()` builds a node's feature metadata from the input features plus the operator's
  declared `features` (read through `OperatorMetadata.get_features()`), then calls `_apply_special_case_logic()`,
  an `if/elif` on `operator_short_name` for `extract_operator`, `embeddings`, `sql_filter` and `merge`.
- Two more name checks sit in the same class: `== VECTORDB` (empty output features) and `_propagate_global_params()`
  (`== EMBEDDINGS`). `FlowValidator._merge_parent_input_features()` has a `== MERGE` branch.
- `OperatorMetadata` obtains operator classes from `OperatorFactoryProvider.get_operator_factory(...).operators` and
  only calls `@staticmethod`/class-level methods on them (`cls.get_metadata()`, `cls.get_required_features()`); it
  falls back to instantiation only for legacy non-static operators.
- Untrusted custom operators are registered as `UntrustedOperatorDescriptor` subclasses so the API process never
  imports uploaded code. Their `__new__` loads the real class (or an isolation proxy) when constructed for execution,
  so propagation must never construct an operator.
- `merge_features()` and `disambiguate_features()` are consumed by `FeaturePropagator`, `FlowValidator` and
  `FlowEnrichmentService` (three-strategy merge dict, via `FeaturePropagator()` without an orchestrator).
- Import chain today: `features_propagator -> operator_metadata -> operator_factory -> abstract_operator`.
  `feature_propagation/__init__.py` eagerly imports `features_propagator`. `abstract_operator` does not currently
  import anything from `feature_propagation`.

## Goals / Non-Goals

**Goals:**
- `FeaturePropagator` contains no operator short names and needs no edit when an operator is added.
- Each operator owns its propagation behavior next to its metadata and validation.
- Custom operators can opt in with the same hooks; untrusted descriptors keep the default.
- Zero change in propagation results, error codes and messages.

**Non-Goals:**
- Moving the validator's pre-propagation merge input snapshot (deferred, see Decision 7).
- Making propagation hooks instance methods or giving them access to operator instance state.
- New configuration, environment variables, REST or DTO changes.

## Decisions

### 1. Hooks are `@classmethod`s on `AbstractOperator` with no-op defaults

```python
class AbstractOperator(...):
    produces_output_features: ClassVar[bool] = True

    @classmethod
    def propagate_features(
        cls, *, operator_config: dict[str, Any], result: "FeaturePropagationResult",
        node_id: str, parent_results: list["FeaturePropagationResult"],
    ) -> None: ...

    @classmethod
    def get_global_params(cls, *, operator_config: dict[str, Any]) -> dict[str, Any]:
        return {}
```

Rationale: the propagator and `OperatorMetadata` work with classes, not instances, and construction of untrusted
descriptors must be avoided (see Context). A classmethod needs only the class, is inherited by
`UntrustedOperatorDescriptor` as a no-op, and follows the repo rule to prefer `@classmethod`/`@staticmethod` over
instance methods when no instance state is read. `FeaturePropagationResult` is imported under `TYPE_CHECKING` only.

The hook mutates `result` in place (matching today's `_apply_*` helpers) and returns `None`. The signature mirrors the
current private helpers so each body moves with minimal edits; this keeps the diff reviewable and the behavior
identical.

Alternatives considered:
- *Instance method.* Rejected: requires instantiation, which is unsafe for untrusted descriptors and costly for
  operators with heavy `__init__`.
- *Separate strategy registry keyed by short name* (`PROPAGATORS: dict[str, Callable]`). Rejected: still a central
  list to edit and a second place to keep in sync with `DOCPIPE_OPERATORS`; it does not give custom operators a
  natural extension point.
- *Declarative metadata only* (e.g. `get_metadata()["features"]` with conditions). Rejected: the Extract and Merge
  rules are conditional on config and across parents; encoding them declaratively adds an interpreter for little gain.

### 2. Terminal behavior is a class attribute, global params are a hook

`produces_output_features = False` on `VectorDBOperator` replaces the `== VECTORDB` check. Global parameters come from
`get_global_params()` returning a dict that the propagator merges into `result.global_params`; `EmbeddingsOperator`
returns `{embeddings_model_id: model_id}` when `model_id` is set (same condition as today).

Alternative: fold both into `propagate_features()`. Rejected: output-feature suppression happens after the
`output_features_to_drop` snapshot step in the propagator, and global params are written after the drop step, so a
single hook running before both would change ordering. Separate declarations keep today's ordering explicit.

### 3. Propagator resolves the class via `OperatorMetadata.get_operator_class()`

`OperatorMetadata.get_operator_metadata()` already holds the `operator_factory`. It records
`self._operator_classes = dict(operator_factory.operators)` alongside the metadata and exposes
`get_operator_class(*, short_name) -> type[AbstractOperator] | None`. The propagator calls it once per node.

Rationale: the class and the metadata then always come from the same factory, so priority/owner resolution and the
orchestrator's `enable_custom_operators` / `custom_operator_packages` settings apply identically to both (see the
existing "Explicit opt-in reaches feature propagation" scenario). Unknown short names return `None`, giving the
unchanged "no operator features, no special case" outcome.

Alternative: the propagator calls `OperatorFactoryProvider` directly. Rejected: it would duplicate the factory-key
logic and could disagree with the metadata source for orchestrator-configured factories.

### 4. Pure merge algorithm moves to a leaf module

New module `feature_propagation/feature_merge.py` holds `disambiguate_features`, `merge_features` (module function)
and its three pure helpers (`_merge_rows_features`, `_compute_column_output_feature_set`,
`_build_parent_disambiguation_items`). It imports only `models` and `OperatorConstants`.

- `MergeOperator.propagate_features()` parses `input_links` into `node_id_to_link_name` (moved from the propagator),
  calls `feature_merge.merge_features(...)` and assigns `result.feature_metadata`. It keeps today's guard: act only
  when `parent_results` is non-empty.
- `FeaturePropagator.merge_features()` stays as a one-line delegate so `FlowEnrichmentService` and any external caller
  are unaffected. `disambiguate_features` is re-exported from `features_propagator` and the package `__init__` for
  existing imports (`flow_validator`).

Alternative: leave the merge code in the propagator and have `MergeOperator` import it. Rejected: it makes an operator
depend on the propagator (the reverse of the intended direction) and creates a hard import cycle.

### 5. Shared "drop features" helper on `FeaturePropagationResult`

The block that rejects mandatory features, pops the features and records `OutputFeaturesToDrop` is duplicated in
`_apply_sql_filter_special_case` and the generic `output_features_to_drop` code. It becomes
`FeaturePropagationResult.drop_features(*, node_id, features, operator_label)` in `models.py`, raising the same
`FlowValidationException` (`ErrorCode.FLOW_VALIDATION_FAILED`, `message_code="MANDATORY_FEATURES_DROPPED"`).

The message text embeds the operator label today (`"... in SQLFilter operator"` vs `"... in <short_name> operator"`).
The helper takes the label as a parameter so both messages stay byte-identical. The generic path keeps its
`output_features_to_drop` serialization ordering (pre-drop snapshot first).

### 6. Import-cycle handling

Operators import only `feature_merge` and `models` from `feature_propagation`, and `abstract_operator` imports types
under `TYPE_CHECKING`. Importing any submodule still executes the package `__init__`, which imports
`features_propagator -> operator_metadata -> operator_factory -> abstract_operator`. Because every operator module
already imports `abstract_operator` before `feature_propagation`, `abstract_operator` is fully loaded by the time the
chain reaches it, but this ordering is fragile.

Mitigation: first task is a spike that imports each touched operator module in a fresh interpreter. If a cycle shows
up, make `feature_propagation/__init__.py` re-export lazily via module `__getattr__` (PEP 562), keeping
`from docpipe.core.orchestration.feature_propagation import FeaturePropagator` working. No public name changes.

### 7. Validator merge input snapshot stays in `FlowValidator` for now

`_merge_parent_input_features()` builds a pre-propagation snapshot with a `== MERGE` check. The same hook pattern
(`prepare_input_features`) would fit, but it changes validator input semantics and its tests, and is independent of
`_apply_special_case_logic()`. Deferred to a follow-up change to keep this one a pure move.

### DDD layer boundaries

`core/operators/*` (operator behavior) depends on `core/orchestration/feature_propagation/models.py` and
`feature_merge.py` (pure data/algorithm leaf modules). `feature_propagation/features_propagator.py` depends on
`OperatorMetadata` and the `AbstractOperator` hook contract, never on concrete operator classes. `core/assets` and
`core/job_management` are untouched. No new ports or adapters.

## Risks / Trade-offs

- [Import cycle between operators and `feature_propagation`] -> `TYPE_CHECKING` imports, leaf modules, spike task, and
  lazy package `__init__` fallback (Decision 6).
- [Subtle ordering change in propagation (drop snapshot, global params, terminal output)] -> keep the propagator's
  step order unchanged; only the body of step "special-case" and the two name checks become hook calls; existing
  `test_features_propagator.py` is the regression net. Its fixtures mock `OperatorMetadata`, so they are updated to
  return real operator classes from `get_operator_class`; test bodies and assertions are unchanged.
- [Error message drift for mandatory-drop errors] -> helper takes the operator label; add tests asserting exact
  message and `message_code` for SQLFilter and the generic path.
- [Custom operator accidentally overrides the hook with an instance method] -> classmethod call on the class would
  fail loudly in tests; documented in the custom operators guide.
- [Hook raising for a malformed config now surfaces from the operator module] -> same exceptions, same call site
  order; no new catch/translate layer.
- [`get_operator_class` stale after custom operator refresh] -> `OperatorMetadata` caches per instance and
  `get_operator_metadata()` is the refresh point, same as the metadata it already caches; no new staleness class.
- [Trade-off] Behavior is now spread across operator files instead of one `if/elif`; mitigated by per-operator hook
  tests and the spec scenarios, and is the intended encapsulation.

## Migration Plan

Single PR, no data or config migration. Ship the hooks and the moved logic together; `FeaturePropagator` public API
(`propagate_features`, `merge_features`, `feature_metadata_to_dict`) and the `disambiguate_features` import path are
unchanged. Rollback is a plain revert. External operator providers continue to work unmodified because the hooks
default to no-ops.
