# Spec Delta

## Purpose

Counts configured keywords and phrases in each document and records the per-document counts in one fixed map column,
using literal, stemmed, or lemmatized matching with bounded, fail-closed, privacy-preserving behavior.

## ADDED Requirements

### Requirement: Operator identity and registration
The system SHALL provide a built-in Functional operator with short name `keyword_count` and owner `docpipe` that is registered with the built-in operator set and discoverable through operator listing.

#### Scenario: Operator is listed
- **WHEN** a user lists available operators
- **THEN** `keyword_count` appears in the Functional category with owner `docpipe`

#### Scenario: Flow references the operator
- **WHEN** a flow node declares `"type": "keyword_count"` with a valid configuration
- **THEN** flow validation resolves the node to the keyword count operator without an unknown-operator error

### Requirement: Configuration fields and defaults
The operator SHALL accept `keywords` (required list of strings), `match_mode` (default `literal`), `language` (default `english`, stem mode only), `lemmatizer_model` (no default, lemma mode only), `case_sensitive` (default false), `whole_word` (default true), `unicode_normalization` (default `NFC`), `allow_overlapping` (default false), and inherited `doc_column` (default `content`).

#### Scenario: Defaults applied
- **WHEN** a node is configured with only `keywords`
- **THEN** the operator runs in literal, case-insensitive, whole-word, NFC, non-overlapping mode against the `content` column

#### Scenario: No output naming options
- **WHEN** a node configures `output_format`, `output_prefix`, `column_names`, `include_total`, or `total_column`
- **THEN** none of these options changes the output, which is always the single `keyword_counts` column

### Requirement: Keyword list limits
The operator MUST reject, before any document is processed, a `keywords` value that is missing, not a list, empty, or longer than 20 entries; any keyword longer than 50 Unicode code points before or after canonicalization; and keyword lists whose combined length exceeds 1,000 code points before or after canonicalization.

#### Scenario: Too many keywords
- **WHEN** a node is configured with 24 keywords
- **THEN** validation fails with a message stating that between 1 and 20 keywords are required and 24 were received

#### Scenario: Boundary values accepted
- **WHEN** a node is configured with exactly 20 keywords, each at most 50 code points, totaling at most 1,000 code points
- **THEN** validation succeeds

#### Scenario: Keyword too long
- **WHEN** the keyword at index 3 exceeds 50 code points
- **THEN** validation fails with a message that identifies index 3 and the 50-character limit

### Requirement: Keyword value validation
The operator MUST reject keywords that are not strings, are empty, are whitespace-only, or have leading or trailing whitespace, and MUST NOT silently trim, deduplicate, truncate, or rename user input.

#### Scenario: Padded keyword rejected
- **WHEN** a keyword is configured as `" contract"`
- **THEN** validation fails instead of trimming the keyword

#### Scenario: Non-string keyword rejected
- **WHEN** a keyword entry is the integer `5`
- **THEN** validation fails before document processing

### Requirement: Keyword collision rejection
The operator MUST reject keyword lists containing two keywords that are equal as configured or that become equal after the selected mode's normalization pipeline, and the error MUST identify the colliding indices.

#### Scenario: Exact duplicate
- **WHEN** the keywords are `["contract", "contract"]`
- **THEN** validation fails

#### Scenario: Stem collision
- **WHEN** stem mode is configured with keywords `["run", "runs"]` that reduce to the same stem
- **THEN** validation fails with a message that keywords at indices 0 and 1 are equivalent after stem normalization

### Requirement: Mode option validation
The operator MUST reject an unknown `match_mode`, an `unicode_normalization` other than `NFC`, `NFKC`, or `none`, `case_sensitive=true` or `whole_word=false` in stem or lemma mode, and `lemmatizer_model` supplied outside lemma mode.

#### Scenario: Case-sensitive stem mode rejected
- **WHEN** stem mode is configured with `case_sensitive=true`
- **THEN** validation fails stating that case_sensitive must be false for stem and lemma modes

#### Scenario: Partial-word lemma mode rejected
- **WHEN** lemma mode is configured with `whole_word=false`
- **THEN** validation fails stating that whole_word must be true for stem and lemma modes

#### Scenario: Model outside lemma mode rejected
- **WHEN** literal mode is configured with `lemmatizer_model`
- **THEN** validation fails

### Requirement: Stem language validation
Stem mode SHALL support exactly the Snowball languages arabic, danish, dutch, english, finnish, french, german, hungarian, italian, norwegian, portuguese, romanian, russian, spanish, and swedish, and MUST reject any other value including `porter`.

#### Scenario: Unsupported language
- **WHEN** stem mode is configured with `language` `ja`
- **THEN** validation fails stating that stem mode does not support language 'ja'

#### Scenario: Every supported language initializes
- **WHEN** stem mode is configured with each supported language in turn
- **THEN** each configuration validates and initializes without downloading data

### Requirement: Lemma model validation
Lemma mode MUST require `lemmatizer_model`, MUST accept only a valid installed package name, and MUST reject paths, URLs, import expressions, uninstalled packages, and pipelines that lack a usable lemmatizer or produce empty lemmas.

#### Scenario: Missing model name
- **WHEN** lemma mode is configured without `lemmatizer_model`
- **THEN** validation fails stating that lemma mode requires lemmatizer_model

#### Scenario: Path-like model rejected
- **WHEN** `lemmatizer_model` is `./models/en` or a URL
- **THEN** validation fails without loading anything from that location

#### Scenario: Uninstalled model
- **WHEN** `lemmatizer_model` names a package that is not installed
- **THEN** validation fails stating that the package is not installed and no download is attempted

#### Scenario: Pipeline without lemmas
- **WHEN** the installed pipeline produces no usable lemmas
- **THEN** validation fails stating that the model does not provide usable lemmas

### Requirement: Input column validation
The operator MUST fail before row processing when the configured document column is missing, ambiguous, or not string or large-string data, and MUST NOT coerce other types.

#### Scenario: Binary column rejected
- **WHEN** the `content` column has binary type
- **THEN** the operator fails stating that it requires a string column 'content' and received binary

#### Scenario: Large-string accepted
- **WHEN** the document column has large-string type
- **THEN** documents are processed normally

### Requirement: Shared Unicode processing
For every mode the operator SHALL apply the configured Unicode normalization to matching copies of keywords and document text, apply the same pipeline to both, use the original configured keyword as the output key, and leave the document column unchanged.

#### Scenario: Composed and decomposed forms match under NFC
- **WHEN** the keyword uses a precomposed accented character and the document uses the decomposed equivalent with NFC normalization
- **THEN** the occurrence is counted

#### Scenario: NFKC compatibility matching
- **WHEN** `unicode_normalization` is `NFKC` and the document contains full-width Latin text equivalent to the keyword
- **THEN** the occurrence is counted, whereas it is not counted under NFC

#### Scenario: Document unchanged
- **WHEN** a document is processed
- **THEN** the document column value in the output is identical to the input

### Requirement: Literal matching semantics
Literal mode SHALL treat keyword text as literal characters, never as pattern syntax, SHALL apply simple Unicode case folding (as provided by the RE2 engine, without multi-character folds such as `ß` to `ss`) when `case_sensitive` is false, and SHALL preserve internal phrase characters so a phrase only matches the same character sequence.

#### Scenario: Metacharacters are literal
- **WHEN** the keyword is `a.b` and the document contains `axb` and `a.b`
- **THEN** the count is 1

#### Scenario: Case-insensitive default
- **WHEN** the keyword is `Contract` and the document contains `CONTRACT` and `contract`
- **THEN** the count is 2

#### Scenario: Case-sensitive literal
- **WHEN** `case_sensitive` is true, the keyword is `Contract`, and the document contains `contract`
- **THEN** the count is 0

#### Scenario: Phrase does not cross punctuation or whitespace variants
- **WHEN** the keyword is `machine learning` and the document contains `machine-learning`, `machine\nlearning`, and `machine  learning`
- **THEN** the count is 0

### Requirement: Literal whole-word boundaries
When `whole_word` is true, a literal match SHALL count only if the characters immediately before and after it are not word characters, where a word character has Unicode category letter, combining mark, number, or connector punctuation; document start and end satisfy the boundary.

#### Scenario: Embedded match excluded
- **WHEN** the keyword is `art` and the document is `party art`
- **THEN** the count is 1

#### Scenario: Non-ASCII boundary
- **WHEN** the keyword is `café` and the document is `cafés café`
- **THEN** the count is 1

#### Scenario: Underscore and digit are word characters
- **WHEN** the keyword is `id` and the document is `id_1 id2 id`
- **THEN** the count is 1

#### Scenario: Partial matching allowed
- **WHEN** `whole_word` is false, the keyword is `art`, and the document is `party art`
- **THEN** the count is 2

### Requirement: Stem matching semantics
Stem mode SHALL tokenize keywords and documents with the same corpus-free tokenizer, case-fold and stem word tokens with the configured language, retain punctuation tokens, exclude whitespace, and count contiguous keyword token sequences in the document token sequence.

#### Scenario: Inflections match
- **WHEN** stem mode with `english` uses keyword `running` and the document is `He runs and ran while running`
- **THEN** every token whose stem equals the stem of `running` is counted

#### Scenario: Whitespace insensitive phrases
- **WHEN** the stem keyword is `machine learning` and the document contains `machine   learning`
- **THEN** the occurrence is counted

#### Scenario: Punctuation remains significant
- **WHEN** the stem keyword is `machine learning` and the document contains `machine-learning`
- **THEN** the occurrence is not counted

### Requirement: Lemma matching semantics
Lemma mode SHALL process keywords and documents with the same configured installed pipeline, use lemmas of non-space tokens, case-fold the lemmas, retain punctuation tokens, and count contiguous keyword lemma sequences in the document lemma sequence.

#### Scenario: Lemma sequence counted
- **WHEN** the configured pipeline lemmatizes `ran` and `running` to `run` and the keyword is `run`
- **THEN** each such document token is counted

#### Scenario: Same pipeline for keywords and documents
- **WHEN** lemma mode is used
- **THEN** keyword lemmas and document lemmas are produced by the same configured pipeline

### Requirement: Occurrence counting
The operator SHALL count each keyword independently, allowing different keywords to count the same span; non-overlapping matching SHALL resume after the matched span, while `allow_overlapping` SHALL advance one code point (literal) or one token (stem, lemma) after each match start.

#### Scenario: Non-overlapping literal
- **WHEN** the keyword is `ana`, `whole_word` is false, and the document is `banana`
- **THEN** the count is 1

#### Scenario: Overlapping literal
- **WHEN** the keyword is `ana`, `whole_word` is false, `allow_overlapping` is true, and the document is `banana`
- **THEN** the count is 2

#### Scenario: Overlapping token sequence
- **WHEN** stem mode with `allow_overlapping` true uses keyword `go go` on document `go go go`
- **THEN** the count is 2

#### Scenario: Shared span across keywords
- **WHEN** the keywords are `machine` and `machine learning` and the document is `machine learning`
- **THEN** both keywords have count 1

### Requirement: Row-level behavior
The operator SHALL emit all configured keywords with counts for non-empty strings, all keywords with zero counts for empty strings, and a null map with a skipped record for null content; an empty table SHALL return the output schema with zero rows.

#### Scenario: Empty string
- **WHEN** a document's content is the empty string
- **THEN** its map contains every configured keyword with count 0 and the document is counted as processed

#### Scenario: Null content
- **WHEN** a document's content is null
- **THEN** its map is null and the document is recorded as skipped

#### Scenario: Empty table
- **WHEN** the input table has zero rows
- **THEN** the output has zero rows, includes `keyword_counts` of type `map<string, int64>`, and metadata is valid

### Requirement: Linguistic document size limit
In stem and lemma modes the operator MUST record a document longer than 1,000,000 characters as failed with a null result and MUST NOT truncate it; literal mode is not subject to this limit.

#### Scenario: Oversized linguistic document
- **WHEN** stem mode receives a 1,000,001-character document
- **THEN** that row is recorded as failed, its current result is null, and other rows are processed

### Requirement: Failure classification
Recoverable row errors, including linguistic tokenization or model failures on a row, SHALL produce a null current result and a failed-document record; configuration, schema, model-loading, and pattern-compilation failures MUST fail the operator and MUST NOT become zero counts.

#### Scenario: Row model failure
- **WHEN** the lemma pipeline raises an error for one document
- **THEN** that row is recorded as failed and other rows still receive counts

#### Scenario: Model load failure
- **WHEN** the configured lemma model cannot be loaded
- **THEN** the operator fails instead of emitting zero counts

### Requirement: Fixed map output column
The operator SHALL write results to exactly one column named `keyword_counts` of type `map<string, int64>`, whose name is not configurable; when the column is absent, each processed row SHALL contain every configured keyword in configuration order with no duplicate keys.

#### Scenario: Single output column
- **WHEN** a table without `keyword_counts` is processed
- **THEN** exactly one new column `keyword_counts` of type `map<string, int64>` is added and all other columns are unchanged

#### Scenario: Configuration order and zero counts
- **WHEN** keywords are `["b", "a"]` and only `a` occurs once
- **THEN** the row map is `[("b", 0), ("a", 1)]`

### Requirement: Existing map merge
When `keyword_counts` exists, the operator SHALL update it in place without adding a second field, preserve existing key order, append absent keys in configuration order, and add counts for exactly equal keys using checked 64-bit addition.

#### Scenario: Merge with repeated and new keys
- **WHEN** the existing row map is `[("run", 2)]` and the operator computes `[("run", 1), ("walk", 3)]`
- **THEN** the output row map is `[("run", 3), ("walk", 3)]`

#### Scenario: Keys compared exactly
- **WHEN** the existing map has key `Run` and the operator keyword is `run`
- **THEN** both keys remain separate in the output map

#### Scenario: No duplicate field
- **WHEN** two sequential `keyword_count` nodes run
- **THEN** the final table has exactly one field named `keyword_counts`

### Requirement: Merge null handling
The merge SHALL follow this truth table: absent or null existing plus a valid current map yields the current map; a valid existing map plus a null current result yields the existing map; null existing plus null current yields null.

#### Scenario: Null existing map
- **WHEN** the existing row map is null and the current row is processed
- **THEN** the output is the current map

#### Scenario: Current row skipped or failed
- **WHEN** the existing row map is valid and the current row is null content or fails recoverably
- **THEN** the existing map is preserved and the skip or failure is recorded

#### Scenario: Both null
- **WHEN** the existing row map is null and the current row is skipped
- **THEN** the output row map is null

### Requirement: Existing map integrity
The operator MUST fail before merging when an existing `keyword_counts` column is not exactly `map<string, int64>` or any existing row contains duplicate or null keys, and MUST fail the affected row on count addition overflow rather than wrapping.

#### Scenario: Wrong existing type
- **WHEN** an existing `keyword_counts` column has type `map<string, int32>` or `string`
- **THEN** the operator fails stating that the existing column must have type map<string, int64>

#### Scenario: Duplicate existing keys
- **WHEN** an existing row map contains the key `run` twice
- **THEN** the operator fails stating that the existing column contains duplicate map keys

#### Scenario: Overflow
- **WHEN** an existing count is the maximum int64 value and the new count is positive
- **THEN** that row fails with an overflow message identifying the row and no wrapped value is written

### Requirement: Discovery metadata
Static operator metadata SHALL be obtainable without instantiation and SHALL describe every configuration attribute with its type, default, and valid values, and SHALL declare the fixed `keyword_counts` feature as type `json`, tagged `keyword_count`, not filterable, not vector-database eligible, and free of configured keyword values.

#### Scenario: Static metadata contents
- **WHEN** operator metadata is requested for `keyword_count`
- **THEN** it lists all configuration attributes with defaults and valid values and exactly one feature `keyword_counts` with `available_for_filter` and `available_for_vector_db` false

### Requirement: Required features
The operator SHALL statically advertise `content` as its required feature, and an instantiated node SHALL require its configured document column.

#### Scenario: Custom document column
- **WHEN** a node is configured with `doc_column` `body`
- **THEN** flow validation requires `body` from upstream and reports an error if it is unavailable

### Requirement: Feature propagation
Flow validation SHALL expose `keyword_counts` in the available features downstream of any `keyword_count` node; it SHALL appear in output features only for the node that first introduces it, and later instances SHALL NOT create an additional feature.

#### Scenario: First and second instance
- **WHEN** a flow chains two `keyword_count` nodes
- **THEN** `keyword_counts` is an output feature of the first node only and is available after both

### Requirement: Execution metadata
Execution metadata SHALL include base counters plus `documents_with_matches`, `total_matches`, and `match_mode`, computed only from the current invocation's counts, excluding null and failed rows, and MUST NOT include per-keyword totals.

#### Scenario: Aggregates exclude accumulated values
- **WHEN** an existing map has `run` 5 and the current invocation finds `run` once in one document
- **THEN** `total_matches` is 1 and `documents_with_matches` is 1

#### Scenario: Mode reported
- **WHEN** the operator runs in stem mode
- **THEN** `match_mode` is `stem`

### Requirement: Aggregate keyword warning
Flow validation SHALL emit a warning, not an error, when all `keyword_count` nodes in a flow together configure more than 100 keyword entries.

#### Scenario: Warning threshold exceeded
- **WHEN** six `keyword_count` nodes each configure 20 keywords
- **THEN** validation succeeds with a warning about the aggregate keyword count

#### Scenario: Below threshold
- **WHEN** five `keyword_count` nodes each configure 20 keywords
- **THEN** no aggregate keyword warning is emitted

### Requirement: No downloads or fallbacks
The operator MUST NOT download, install, or fetch models, corpora, or packages, MUST NOT perform network access, and MUST NOT fall back from lemma to stem, stem to literal, or safe literal matching to another pattern engine.

#### Scenario: Missing resource without network
- **WHEN** lemma mode is configured with a missing model and network access is blocked
- **THEN** validation fails with the missing-model error and no network call is attempted

#### Scenario: No mode fallback
- **WHEN** the selected mode's resources are unavailable
- **THEN** the operator fails rather than producing counts with a different mode

### Requirement: Sensitive data handling
The operator MUST NOT write document text or the configured keyword list to logs, telemetry attributes, or metric labels, and error messages MUST identify keywords by index rather than including document text or the complete keyword list.

#### Scenario: Logs exclude keywords and text
- **WHEN** the operator processes documents and logs are captured
- **THEN** no configured keyword or document text appears in the captured logs

#### Scenario: Index-based errors
- **WHEN** a keyword at index 2 is invalid
- **THEN** the error message references index 2 and does not list all configured keywords
