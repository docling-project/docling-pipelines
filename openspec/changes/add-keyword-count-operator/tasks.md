# Tasks

## 1. Constants and matching engines

- [ ] 1.1 Add `KEYWORD_COUNT` operator name, config keys (`keywords`, `match_mode`, `language`, `lemmatizer_model`, `case_sensitive`, `whole_word`, `unicode_normalization`, `allow_overlapping`), the `keyword_counts` column name, limit constants (20 / 50 / 1,000 / 1,000,000 / 100) and the `documents_with_matches`, `total_matches`, `match_mode` metric names to `operator_constants.py` / `constants.py`; verify `python -c "from docpipe.core.constants import OperatorConstants"` imports cleanly.
- [ ] 1.2 Create `keyword_normalization.py` with Unicode normalization, the whole-word boundary test (categories `L*`, `M*`, `N*`, `Pc`), and the shared token-sequence counter (first-token index, non-overlapping and overlapping advance); verify with `tests/unit/operators/keyword_count/test_keyword_normalization.py` covering boundary edge cases and `go go` / `go go go` overlap.
- [ ] 1.3 Implement `LiteralMatcher` using `re2.Options(literal=True, case_sensitive=...)`, `finditer` for the unfiltered case, a single-encode bytes `search` loop with `start + 1` advance after boundary rejection otherwise; verify tests for metacharacter literals, `a a` in `aa a a`, `banana`/`ana` overlap, `café`/`cafés`, `id_1 id2 id`, NFC vs NFKC, case-sensitive and case-insensitive counts, and phrase variants (`machine-learning`, newline, double space) returning 0.
- [ ] 1.4 Implement `StemMatcher` (`wordpunct_tokenize`, `casefold`, memoized `SnowballStemmer`, 15 languages excluding `porter`) and keyword canonicalization; verify tests for inflection matching (`running` over `He runs and ran while running` = 2), whitespace-insensitive and punctuation-significant phrases, `run`/`runs` collision, unsupported language `ja` and `porter`, and each supported language constructing without network access.
- [ ] 1.5 Implement `LemmaMatcher` with the identifier regex, `spacy_models` entry-point allowlist, `load_model_from_package`, `nlp.max_length`, and the usable-lemma self-check, importing spaCy lazily; verify with a fake in-memory pipeline for lemma sequences, same-pipeline keyword/document processing, path/URL/`blank:` rejection, uninstalled package, empty-lemma pipeline, and a test that no download function is called.

## 2. Operator implementation

- [ ] 2.1 Create `keyword_count.py` with `KeywordCountOperator` (`short_name="keyword_count"`, `Functional`, `OWNER_DOCPIPE`) and `__init__` validation in the order given by the design (option values, mode legality, list limits, keyword values, collisions, resources) with index-only error messages; verify parametrized tests for every rejection scenario in the spec, including the 24-keyword message, index-3 length message, padded keyword, non-string keyword, 1,000 combined code-point boundary, and ignored output-naming options.
- [ ] 2.2 Implement input-column validation (missing, ambiguous, non-string/large-string) and the row loop: null → skipped, empty string → zero counts, linguistic oversize → failed, other row exceptions → failed, no downgrade of configuration errors; verify tests for binary column rejection, large-string acceptance, empty table schema, null/empty/oversized rows with other rows unaffected, and lemma row failure versus model-load failure.
- [ ] 2.3 Implement map output construction and existing-column merge (type and duplicate/null-key preconditions, ordered merge, checked int64 addition, `set_column` in place, null truth table); verify tests for configuration-order zero counts, `Run` vs `run` as separate keys, two sequential nodes yielding one field, wrong existing types (`map<string,int32>`, `string`), duplicate existing keys, overflow failing only that row, and unchanged document column.
- [ ] 2.4 Implement execution metadata (`documents_with_matches`, `total_matches`, `match_mode`, node status downgrade on failed rows) using only current-invocation counts, and verify tests that accumulated existing values are excluded and no per-keyword totals appear.
- [ ] 2.5 Implement `validate()` (requires `self.doc_column`), static `get_required_features()` / `get_static_required_features()` returning `["content"]`, and static `get_metadata()` with all attributes, defaults, valid values and the single `keyword_counts` feature (`json`, tag `keyword_count`, not filterable, not vector-DB eligible); verify tests that metadata is obtainable without instantiation, contains no keyword values, and a `doc_column="body"` node reports a missing-column error.
- [ ] 2.6 Add a privacy test using `caplog` across all modes and error paths asserting no configured keyword or document text appears in logs, messages, or metadata; verify the test passes.

## 3. Registration, propagation and flow validation

- [ ] 3.1 Export the operator from `functional/__init__.py` and add it to `DOCPIPE_OPERATORS` in `operator_registry.py`; verify `docling-pipelines --list-operators --verbose` lists `keyword_count` under Functional with owner `docpipe`, and a flow validation test resolves `"type": "keyword_count"` without an unknown-operator error.
- [ ] 3.2 Add feature-propagation tests for chained `keyword_count` nodes (feature introduced by the first node only, available after both) and fix any propagation gap found; verify the tests pass.
- [ ] 3.3 Add `KEYWORD_COUNT_AGGREGATE_LIMIT_EXCEEDED` to `ValidationCodeMessages` and implement `_validate_keyword_count_budget` in `flow_validator.py`, called from `validate_dag`; verify tests that six nodes × 20 keywords produce one warning (validation otherwise succeeds), five nodes × 20 produce none, and malformed `keywords` values do not crash the check.
- [ ] 3.4 Add `SUM` entries for `documents_with_matches` and `total_matches` in `strategies.py`; verify an aggregator unit test over two batch metadata dicts returns summed values and the last `match_mode`.

## 4. Documentation and sample flow

- [ ] 4.1 Create `docs/operators/functional/keyword_count_readme.md` following the 8-section template, including the RE2 simple-case-folding limitation, lemma-model installation requirement and validation-time load cost, stem tokenization behavior, and limits; verify the documented flow JSON passes `docling-pipelines --flow-file ... --validate`.
- [ ] 4.2 Add a `KeywordCountOperator` section and table-of-contents entry to `docs/reference/OPERATORS.md` and the operator to the Functional row in `README.md`; verify links resolve and parameter names match `get_metadata()`.
- [ ] 4.3 Add `sample_flows/operators/keyword_count.json` (literal mode, no external services) and verify it validates and runs end to end against a small local fixture, producing the `keyword_counts` column.

## 5. Integration checks

- [ ] 5.1 Run `pytest tests/unit/operators/keyword_count tests/unit/core/orchestration -v` and the existing operator-registry/metadata tests; verify all pass and `clear_singleton_caches` conventions are respected.
- [ ] 5.2 Run `ruff check` and `pre-commit run --from-ref origin/main --to-ref HEAD` on changed files; verify no new findings, keyword-only `*` arguments on all multi-parameter functions, `%s` logging, and `@staticmethod` use per AGENTS.md rule 15.
- [ ] 5.3 Run the sample flow with `enable_micro_batching: true` and a small `micro_batch_size`; verify aggregated `total_matches` equals the single-batch run.

## Workflow follow-up

- Archive the change after review requirements are satisfied.
