# Design

## Context

See `proposal.md` for motivation and `specs/keyword-count-operator/spec.md` for requirements. Facts about the current
codebase that shape the approach:

- Operators subclass `AbstractOperator`. `quality/doc_quality.py` is the closest precedent on `main`: config parsed in
  `__init__`, static `get_required_features()`, and a static `get_metadata()` that declares `attributes` and `features`
  using `OperatorConstants` keys (`label`, `category`, `description`, per-feature `type`/`available_for_*`).
- `FlowValidator._validate_node` instantiates every operator with `VALIDATING_FLOW=True` and converts any exception
  raised from `__init__` into an `OPERATOR_VALIDATION_FAILED` error carrying `str(exc)`. Configuration validation in
  `__init__` is therefore the validation path for both flow validation and execution.
- `OperatorMetadata._extract_config_values` calls `cls.get_metadata()` and `cls.get_required_features()` on the **class**.
  An instance-method `get_required_features(self)` raises `TypeError`, and its fallback (`get_operator()` returns a class,
  not an instance) fails the same way. `get_required_features` must stay a `@staticmethod`.
- Feature propagation adds each operator's metadata `features` to the node's metadata and reports as "output features"
  only those absent from the node's input features. A second `keyword_count` node therefore automatically does not
  re-introduce `keyword_counts`.
- Batch metadata aggregation (`strategies.py`, `DEFAULT_STRATEGIES`) defaults unknown numeric fields to `LAST`, so new
  counters need explicit `SUM` entries or micro-batched runs under-report.
- `flow_validator.validate_dag` raises `FlowValidationException` for warnings; `FlowExecutor._validate_flow` proceeds on
  warnings-only exceptions.
- Installed: `google-re2` (`re2`, with `Options.literal`), `nltk` (`SnowballStemmer`, `wordpunct_tokenize`, no corpora
  needed), `spacy` 3.8. No spaCy pipeline package is installed.

## Goals / Non-Goals

**Goals:**
- A pure, deterministic `transform()` whose results depend only on configuration and document text.
- Matching engines isolated from Arrow/table handling so they are unit-testable without tables.
- Every limit and fail-closed rule in the spec enforced before any row is processed.

**Non-Goals:**
- Regex or wildcard keywords, per-keyword options, configurable output column, or cross-batch count accumulation.
- Caching or sharing spaCy pipelines across operator instances.
- Changing how other operators propagate or aggregate metadata beyond the three new counters.

## Decisions

### D1. Two modules, three matcher classes
`keyword_normalization.py` holds the matching engines; `keyword_count.py` holds the operator (config validation, row
loop, map building/merge, metadata). Engines are `LiteralMatcher`, `StemMatcher`, `LemmaMatcher` behind one small base
with `canonical_keyword(text) -> Hashable` and `count(text) -> list[int]` (counts in configured keyword order). Pure
helpers (normalization, boundary test, token-sequence scan) are `@staticmethod`s per AGENTS.md rule 15.
*Alternative:* one class with mode branches — rejected; each mode has distinct resources and failure modes.

### D2. Literal mode: normalize in Python, match and fold with RE2 (`literal=True`)
Pipeline per text: `unicodedata.normalize(form, text)` (skipped for `none`); the same pipeline runs on keywords. The
pattern is compiled with `re2.Options(literal=True, case_sensitive=<config>)`, so keyword text is never interpreted as
pattern syntax, case folding is done by RE2 itself, and there is no `re` fallback.
*Accepted limitation (confirmed decision):* RE2 applies simple Unicode case folding only. Verified: `straße` does not
match `STRASSE`, and `ΣΑΣ` matches `σας` only via simple folds. Full `str.casefold()` semantics (multi-character
foldings) are not provided in literal mode; the README must state this. Stem and lemma modes use `str.casefold()`
on tokens because they do not go through RE2.
*Alternative:* pre-fold with `str.casefold()` and use RE2 case-sensitively — broader equivalence for one extra linear
pass; rejected in favour of the user's decision to keep RE2 as the folding engine.

### D3. Literal search loop: `finditer` only when no boundary filtering is needed
- `whole_word=false` and `allow_overlapping=false`: `pattern.finditer(text)` (str input, linear; verified 900k chars /
  300k matches in 0.44 s).
- Every other combination: encode the normalized text to UTF-8 **once** and loop `pattern.search(bytes, pos)`. Passing
  `str` with `pos` re-encodes per call and is quadratic (verified: 20k matches on 60k chars took 1.5 s); bytes input
  took 0.37 s for 300k matches.
- Non-overlapping advances `pos = match.end()` after a *counted* match; overlapping advances `pos = match.start() + 1`
  (a byte step is safe because the pattern begins with a UTF-8 lead byte and cannot match mid-character).
- A match rejected by the whole-word check advances `pos = match.start() + 1`, **not** `match.end()`. Using `finditer`
  here would be wrong: with keyword `a a` and text `aa a a`, the rejected match at (1, 4) hides the valid match at
  (3, 6). This is why `finditer` is restricted to the unfiltered case.
- Boundary test decodes the code point before the match start (step back over `0x80–0xBF` continuation bytes, at most 3)
  and the code point at the match end, and tests `unicodedata.category` in `L*`, `M*`, `N*`, or `Pc`. Document edges
  satisfy the boundary.
*Alternative:* `str.find` loop — fastest (0.03 s) but drops RE2, which the proposal and the earlier decision keep.

### D4. Stem and lemma share one token-sequence counter
Both modes reduce a text to a list of comparable tokens (non-space tokens, punctuation retained, case-folded) and
count contiguous keyword sequences. The counter indexes document positions by first token, compares slices, and
tracks `next_allowed` for the non-overlapping case; overlap advances one token.
- Stem tokenizer: `nltk.tokenize.wordpunct_tokenize` (`\w+|[^\w\s]+`, no corpora). `machine-learning` yields three
  tokens, so punctuation stays significant. Word tokens are case-folded then stemmed with `SnowballStemmer(language)`;
  punctuation tokens are not stemmed. A per-instance dict memoizes stems.
- Supported languages are `SnowballStemmer.languages` minus `porter` (15 languages, matching the spec).
- Collision detection compares keyword token tuples, so `run` / `runs` collide in English stem mode.
- Expected spec outcome to encode in tests: `He runs and ran while running` with keyword `running` counts 2 (`runs`,
  `running`), because `ran` stems to `ran`.

### D5. Lemma mode loads only registered spaCy model packages
- `lemmatizer_model` must match `^[A-Za-z_][A-Za-z0-9_]*$` (rejects paths, URLs, `blank:` shortcuts, import
  expressions) **and** be listed in the `spacy_models` entry-point group (`importlib.metadata.entry_points`). This is
  stricter than `spacy.util.is_package`, which accepts any installed distribution and would let `load_model_from_package`
  `import_module` an arbitrary installed package.
- Load with `spacy.util.load_model_from_package(name, disable=["ner", "parser"])` and set `nlp.max_length = 1_000_000`,
  matching the document limit. Never call `spacy.load` with user strings and never touch `spacy.cli.download`.
- Self-check at load: run the pipeline on the first keyword; fail when it has no non-space tokens or any lemma is empty
  ("model does not provide usable lemmas"). Keywords with zero lemma tokens fail validation.
- Loading is eager in `__init__` (spec requires validation-time failure). A pipeline is loaded per operator instance and
  never shared, because spaCy `Language` objects are not documented as thread-safe and batches may run concurrently.
  Cost: each flow validation of a lemma node loads the model.
- `import spacy` is deferred into lemma mode so literal/stem flows do not pay its import time.

### D6. Configuration validation lives in `__init__`
`__init__` validates in a fixed order: option types/values, mode-specific option legality, keyword list limits, keyword
value rules, canonicalization (using the selected matcher), collision check, then lemma/stem resource checks. All error
messages reference keyword **indices** and counts only. Because `FlowValidator` surfaces constructor exceptions as
validation errors, no separate `validate()` logic is needed for configuration; `validate()` is overridden only to require
`self.doc_column` from upstream via `OperatorUtils.validate_columns`.
Resolution of the spec's "instantiated node SHALL require its configured document column": `get_required_features()` and
`get_static_required_features()` both stay static and return `["content"]` (discovery cannot call an instance method —
see Context); custom `doc_column` values are enforced by the `validate()` override.

### D7. Output construction and merge
- Counts per row are computed as an ordered list aligned to configured keyword order.
- Absent column: build `pa.MapArray.from_arrays(offsets, keys, items)` with `pa.map_(pa.string(), pa.int64())`;
  skipped/null rows use a null offset (verified to yield a null map entry) and append the column.
- Existing column: precondition checks run once on the whole column (single field of that name; key type `string`, item
  type `int64`; no duplicate/null keys per row), then each row merges in Python: existing pairs in order, add counts for
  equal keys, append new keys in configuration order, using Python ints with an explicit `> 2**63 - 1` overflow check.
  The result replaces the column at its original position via `set_column`, so no second field exists.
- Merge truth table (spec): current null/failed keeps the existing map; existing null takes the current map; both null
  stays null. An overflow fails that row and keeps the existing map unchanged.
- The Arrow `MapArray` ignores key-name conventions, so the type check compares `key_type` and `item_type`, not field
  names (Parquet round trips rename `key`/`value`).

### D8. Row loop, failure classification, metadata
- Per row: null → skipped (`record_skipped_document`); empty string → zero counts, processed; linguistic mode and
  `len(text) > 1_000_000` → `record_failed_document`; any other exception inside a row (tokenization, model, encode
  errors such as lone surrogates) → failed row. Configuration/schema/model-load/pattern-compile errors are raised before
  or outside the row loop and are never downgraded.
- Failure and skip records use the table's `id`/`name` columns when present, else `row_<index>`; reasons are fixed
  strings or exception class names, never document text or keywords.
- Node status becomes `COMPLETED_WITH_ERRORS` when any row failed, via `OperatorUtils.merge_status`.
- `documents_with_matches` and `total_matches` accumulate only from this invocation's per-row counts of rows that
  succeeded; `match_mode` is a string. Logs report counts only.
- `strategies.py` gets `SUM` entries for `documents_with_matches` and `total_matches`; `match_mode` keeps the default
  `LAST`.

### D9. Static metadata and feature declaration
`get_metadata()` is a `@staticmethod` returning attributes (type, default, `valid_values` for `match_mode`, `language`,
`unicode_normalization`) and one feature `keyword_counts`: `type: json`, `tags: ["keyword_count"]`,
`available_for_filter: false`, `available_for_vector_db: false`, with a description that contains no keywords. The
operator is added to `DOCPIPE_OPERATORS` and exported from `functional/__init__.py`.

### D10. Aggregate keyword warning in the flow validator
A new `_validate_keyword_count_budget(dag, validate_results)` runs in `validate_dag` next to the other flow-level checks.
It sums `len(config["keywords"])` over `keyword_count` nodes whose `keywords` is a list (malformed values are reported by
the node's own validation and ignored here). When the total exceeds 100, one warning is appended against the node at
which the running total first crosses the threshold, using a new `ValidationCodeMessages` entry
(`KEYWORD_COUNT_AGGREGATE_LIMIT_EXCEEDED`) with the total and threshold in the message. It is a warning, so execution
proceeds. Unmapped message codes default to `FLOW_LEVEL` scope in the API DTO, which is acceptable.

## Risks / Trade-offs

- [Python-side normalization of large literal-mode documents allocates a copy] → one transient copy per document;
  bounded by document size; no mitigation beyond processing rows sequentially.
- [RE2 simple case folding is narrower than the spec's "Unicode case folding" wording (e.g. `straße` vs `STRASSE`)] →
  confirmed trade-off; spec requirement "Literal matching semantics" should be reworded to "simple Unicode case folding"
  before apply, and the README must list the limitation.
- [Bytes search loop is slower than `finditer`] → only used when boundary filtering or overlap is required; measured
  0.37 s per 300k matches.
- [Lemma model loaded on every flow validation] → accepted for spec fidelity; document the cost in the README.
- [spaCy pipelines with different component sets may not lemmatize with `ner`/`parser` disabled] → load self-check
  fails closed with the "no usable lemmas" error rather than producing wrong counts.
- [Entry-point allowlist excludes pipelines installed as directories on disk] → intentional; the spec forbids paths.
- [Stem tokenization splits on every non-word character, so URLs and hyphenated terms need multi-token keywords] →
  documented in the README; matches the spec's "punctuation remains significant".
- [Constructor-time validation means malformed configs surface as `OPERATOR_VALIDATION_FAILED` with a generic code] →
  acceptable and consistent with other operators.

## Migration Plan

Additive. No stored data or existing flow changes. Rollback is removing the operator from `DOCPIPE_OPERATORS`, the
validator warning, and the two aggregation entries; flows that do not reference `keyword_count` are unaffected.
Downstream consumers may see a new `map<string, int64>` column and must not rely on it being filterable or storable in
a vector database.
