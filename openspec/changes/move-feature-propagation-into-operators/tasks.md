# Tasks

## 1. Foundations: hooks, class lookup, shared merge module

- [x] 1.1 [backend] Spike the import graph: in a fresh interpreter run `python -c "import docpipe.core.operators.functional.merge"` (and the extract, embeddings, sql_filter, vectordb modules) after adding a `from docpipe.core.orchestration.feature_propagation.models import FeaturePropagationResult` under `TYPE_CHECKING`; record whether a cycle appears. Verify: command exits 0 for all five modules.
- [x] 1.2 [backend] Add `produces_output_features: ClassVar[bool] = True` and the no-op `propagate_features()` / `get_global_params()` classmethods (keyword-only args, docstrings) to `AbstractOperator`. Verify: `uv run mypy src/docpipe/core/operators/abstract_operator.py` is clean and a test shows a subclass with no override returns `{}` / leaves `result` untouched.
- [x] 1.3 [backend] Add `_operator_classes` capture and `get_operator_class(*, short_name)` to `OperatorMetadata.get_operator_metadata()`. Verify: unit test in `tests/unit/core/operators/test_operator_metadata.py` covers a built-in name, an unknown name (returns `None`) and a custom-operator factory built from an orchestrator.
- [x] 1.4 [backend] Create `feature_propagation/feature_merge.py` containing `disambiguate_features`, a module-level `merge_features` and the three pure helpers moved verbatim from `FeaturePropagator`; keep `FeaturePropagator.merge_features()` as a delegate and re-export `disambiguate_features` from `features_propagator.py` and `__init__.py`. Verify: `tests/unit/core/orchestrator/test_features_propagator.py` and `tests/unit/core/flows/application/services/test_flow_enrichment_service.py` pass. The propagator fixtures that mock `OperatorMetadata` are updated in task 3.1 so `get_operator_class` returns the real operator classes.
- [x] 1.5 [backend] Add `FeaturePropagationResult.drop_features(*, node_id, features, operator_label)` in `models.py` reproducing the current mandatory check, pop, `OutputFeaturesToDrop` record and exact `MANDATORY_FEATURES_DROPPED` message. Verify: new unit tests assert message text and `message_code` for labels `SQLFilter` and a generic short name.

## 2. Migrate operators onto the hooks (one operator at a time)

- [x] 2.1 [backend] `SQLFilterOperator`: implement `propagate_features()` using `drop_features()` (label `SQLFilter`), moving logic from `_apply_sql_filter_special_case`. Verify: new per-operator hook test (drop, mandatory rejection, no list) plus `TestSQLFilterSpecialCase` still pass.
- [x] 2.2 [backend] `EmbeddingsOperator`: implement `propagate_features()` (quantization typing and descriptions) and `get_global_params()` (`embeddings_model_id`). Verify: new hook tests for binary/ubinary/none/uppercase quantization and model id present/absent; `TestEmbeddingsQuantizationSpecialCase` and `TestGlobalParameterPropagation` still pass.
- [x] 2.3 [backend] `ExtractOperator`: implement `propagate_features()` for `entities` and `document_type` add/remove from `entity_extraction.provider`. Verify: new hook tests for missing key, none mode, real provider; `TestExtractOperatorSpecialCase` and `TestExtractOperatorEntityMode` still pass.
- [x] 2.4 [backend] `MergeOperator`: implement `propagate_features()` (parse `input_links`, call `feature_merge.merge_features`, no-op when `parent_results` is empty). Verify: new hook tests for rows, inner join, full outer join with and without link names; `TestMergeOperatorSpecialCase` and `TestMergeFeaturesMethod` still pass.
- [x] 2.5 [backend] `VectorDBOperator`: set `produces_output_features = False`. Verify: `test_propagate_features_vectordb_produces_no_output` still passes and a unit test asserts the attribute on `VectorDBOperator` and `True` on a default operator.

## 3. Make the propagator operator-agnostic

- [x] 3.1 [backend] In `FeaturePropagator.propagate_features()`, resolve the operator class via `get_operator_class()` and call its `propagate_features()` hook where `_apply_special_case_logic()` was called; replace the `== VECTORDB` check with `produces_output_features`; replace `_propagate_global_params()` with `get_global_params()`. Keep step order unchanged. Because the `test_features_propagator.py` fixtures bypass `__init__` and mock `OperatorMetadata`, update each fixture to set `operator_metadata.get_operator_class` to resolve real classes from the operator factory; otherwise the hooks and `produces_output_features` would read from a `Mock` and the regression net would not exercise them. Verify: full `tests/unit/core/orchestrator/test_features_propagator.py` and `test_flow_validator.py` pass with only that fixture change.
- [x] 3.2 [backend] Delete `_apply_special_case_logic`, the three `_apply_*_special_case` helpers, `_propagate_global_params`, and the merge helper bodies now living in `feature_merge.py`; use `drop_features()` for the generic `output_features_to_drop` block. Verify: `grep -n "OperatorConstants.Operators" src/docpipe/core/orchestration/feature_propagation/features_propagator.py` returns no matches, and the regression suite still passes.
- [x] 3.3 [backend] Update the module and method docstrings in `features_propagator.py` that mention "Extract, SQLFilter, Merge" special cases and the `See Also` references. Verify: `grep -n "special case\|special_case" src/docpipe/core/orchestration/feature_propagation/features_propagator.py` shows no stale references.
- [x] 3.4 [backend] Add an extensibility test registering a dummy operator that overrides `propagate_features()` and `get_global_params()`, and a descriptor test with a `UntrustedOperatorDescriptor` subclass proving the class is never instantiated and its source file never imported during propagation. Verify: both tests pass without any edit to `features_propagator.py`.
- [x] 3.5 [backend] If task 1.1 or a full test run shows an import cycle, make `feature_propagation/__init__.py` lazy via module `__getattr__` with the same public names. Verify: `python -c "from docpipe.core.orchestration.feature_propagation import FeaturePropagator, disambiguate_features"` exits 0 and all operator modules import in a fresh interpreter. Skipped: no import cycle exists (verified by task 1.1 and a full test run).

## 4. Documentation

- [x] 4.1 [backend] Document `propagate_features()`, `get_global_params()` and `produces_output_features` in `docs/guides/CUSTOM_OPERATORS_GUIDE.md` (contract, classmethod requirement, example, link from the table of contents and the methods table). Verify: links resolve relatively and code fences use a language tag.

## 5. Integration and validation

- [x] 5.1 [backend] Run `uv run ruff check --fix .` and `uv run mypy .`. Verify: no new findings in touched files.
- [x] 5.2 [backend] Run `uv run pytest tests/unit/core -q` then `uv run pytest -q`. Verify: all pass, including the regression suites listed above (`test_features_propagator.py` with its fixture hookup only).
- [x] 5.3 [backend] Validate the sample flows end to end: `docling-pipelines --flow-file <sample> --validate` for at least a full pipeline, a branch/merge flow and an embeddings-with-binary-quantization flow from `sample_flows/`. Verify: results match the pre-change run (same exit status and no new validation errors). (Result: the branching flow validates; the milvus and OpenSearch flows fail only on missing credentials or services, with no feature-propagation errors.)
- [x] 5.4 [backend] Run `openspec validate move-feature-propagation-into-operators --strict` and the pre-commit check `pre-commit run --from-ref origin/main --to-ref HEAD`. Verify: both exit 0.

## Workflow follow-up

- Follow-up change: move `FlowValidator._merge_parent_input_features()` onto a `prepare_input_features` hook (design Decision 7).
- Archive the change with `openspec archive move-feature-propagation-into-operators` after review and tests pass.
