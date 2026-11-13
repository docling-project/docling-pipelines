# Spec Delta

## Purpose

Validate PII gold data and compare detector configurations reproducibly, including source mapping and final redacted
artifacts. Qualification evidence establishes the measured language/entity/jurisdiction boundary of a release profile.

## ADDED Requirements

### Requirement: Versioned PII evaluation corpus

The evaluation workflow SHALL accept versioned records with opaque document IDs, original text/representation, language,
jurisdiction or explicit unknown, gold spans/types, document-family grouping, split, provenance, and annotation-review
state. Gold locators SHALL identify exact source evidence. Invalid or unreviewed gold SHALL NOT qualify a release
profile.

#### Scenario: Corrupt gold offset

- **WHEN** a gold span's quotation disagrees with its source coordinates
- **THEN** corpus validation fails with an opaque record reference before detector scoring

#### Scenario: Unreviewed generated annotations

- **WHEN** annotations were produced by a model and lack independent review
- **THEN** they can be used for development diagnostics but cannot contribute to release qualification

### Requirement: Locked and uncontaminated evaluation splits

The workflow SHALL distinguish development, calibration, and locked test splits and record their content fingerprints.
Document-family variants, near duplicates, and translated variants SHALL remain in the same split. Qualification SHALL
reject a missing, modified, or leaked locked split. Acceptance thresholds SHALL be fixed before the qualifying run.

#### Scenario: Template family crosses splits

- **WHEN** two variants from the same source family appear in calibration and locked test data
- **THEN** validation reports leakage and qualification cannot pass

### Requirement: English and Latin-script stress coverage

English qualification SHALL cover every requested entity type with positives, hard negatives, contextual ambiguities,
international identifiers, and Latin-script Unicode variants. It SHALL include OCR noise, structured text, repeated and
overlapping entities, long documents, window boundaries, embedded instructions, and incomplete provider responses.
Required absent slices SHALL fail qualification instead of disappearing from an aggregate score.

#### Scenario: Missing address coverage

- **WHEN** a profile requests `Address` but the test set contains no reviewed address positives
- **THEN** the release gate fails with an insufficient-coverage reason

#### Scenario: Mixed-language diagnostic records

- **WHEN** an English profile is tested against additional Latin-script languages or mixed-language passages
- **THEN** those results remain separately labeled diagnostics and do not imply qualification for those languages

#### Scenario: Boundary entity missed by both windows

- **WHEN** every source character was submitted but the detector omits a gold entity crossing a core-window boundary
- **THEN** scoring records a semantic detection miss despite structurally complete coverage and applies the stress-slice
  gate

### Requirement: Reproducible detector comparison

The workflow SHALL compare hardened LLM-only, local-only, and hybrid configurations on the same locked inputs and
policy.
Reports SHALL identify model/weight revisions, endpoint configuration fingerprints without secrets, prompts,
recognizers,
tokenizers, code revision, window policy, score calibration, corpus fingerprint, runtime settings, and run time.
Unavailable or mutable version evidence SHALL be explicit and SHALL prevent reproducible-profile qualification.

#### Scenario: Hybrid ablation

- **WHEN** a hybrid configuration improves aggregate recall but degrades a required entity slice
- **THEN** both the gain and regression are visible and the aggregate cannot override a failing slice gate

### Requirement: Detection and final-artifact metrics

Reports SHALL include exact span-and-type precision/recall/F1, overlap diagnostics, full sensitive-span masking recall,
sensitive-character recall, document residual-leakage rate, non-sensitive-character masking rate, invalid evidence,
assessment failure/review rates, and latency/cost where available. Metrics SHALL be broken down by language, type,
jurisdiction, domain, and stress slice with support counts and document-level confidence intervals.

#### Scenario: Only part of an account number is masked

- **WHEN** masking covers most digits but leaves any part of the gold sensitive occurrence exposed
- **THEN** full-span masking fails for that occurrence even if overlap metrics give partial credit

#### Scenario: Every difficult document is withheld

- **WHEN** a configuration withholds difficult cases and emits only easy documents
- **THEN** the report shows whole-corpus detection misses, withholding and release coverage separately from
  emitted-artifact safety

### Requirement: Machine-readable release gates

Qualification SHALL read a versioned gate profile containing required slices, minimum support, numeric accuracy and
over-redaction limits, assessment-completion limits, and deterministic invariants. Missing evidence or a failed gate
SHALL produce a non-zero exit code and explicit failed checks. Zero accepted invalid spans, false-success failures, and
known mapping regressions SHALL be mandatory invariants for every profile.

#### Scenario: Strong pooled result and weak entity

- **WHEN** pooled scores pass but a required entity's recall misses its gate
- **THEN** qualification fails and reports that entity's observed value, threshold, and sample count

#### Scenario: Missing gate thresholds

- **WHEN** a profile omits a required threshold or minimum-support value
- **THEN** qualification fails configuration validation rather than selecting a permissive default

### Requirement: Explicit evaluation network use

Corpus validation, scoring saved predictions, and evaluating release gates SHALL operate offline. Calling a remote
detector SHALL require an explicit run command with remote execution enabled and a declared synthetic or authorized-data
manifest. The workflow SHALL NOT automatically transmit a private corpus during tests, imports, scoring, or
qualification.

#### Scenario: Offline saved-prediction scoring

- **WHEN** corpus, prediction, and profile files are provided to the scoring workflow without network permission
- **THEN** metrics and release checks complete without contacting model services

### Requirement: Evaluation artifact confidentiality

Default evaluation reports SHALL contain opaque references, counts, sanitized failures, fingerprints, and metrics
without
raw PII, source text, quotations, or credentials. Detailed evidence artifacts SHALL require an explicit sensitive-output
option and be labeled accordingly. Report generation SHALL NOT place private fixtures or evidence into ordinary logs.

#### Scenario: Provider error echoes the document

- **WHEN** an evaluation response fails and its error contains source text
- **THEN** the default report records a sanitized failure class and opaque document ID without that text

### Requirement: Additional-language qualification

Adding a qualified language SHALL require a reviewed in-language corpus, locale-aware policy and recognizers, adequate
entity/jurisdiction support, and a passing gate report for the exact detector profile. English or Latin-script aggregate
results SHALL NOT substitute for those requirements. Failed or insufficient qualification SHALL leave that language
explicitly unqualified.

#### Scenario: French profile without French gold data

- **WHEN** a configuration can process French strings but has only English qualification evidence
- **THEN** qualification does not advertise French accuracy and the French profile remains unqualified
