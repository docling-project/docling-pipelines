# Tasks

## Table of contents

- [1. Regression evidence and evaluation foundation](#1-regression-evidence-and-evaluation-foundation)
- [2. Domain contracts and source mapping](#2-domain-contracts-and-source-mapping)
- [3. Structured inference transport](#3-structured-inference-transport)
- [4. Grounding and decision policy](#4-grounding-and-decision-policy)
- [5. Hybrid provider](#5-hybrid-provider)
- [6. Operator integration and configuration](#6-operator-integration-and-configuration)
- [7. Reviewed English corpus](#7-reviewed-english-corpus)
- [8. Qualification and integration checks](#8-qualification-and-integration-checks)
- [Workflow follow-up](#workflow-follow-up)

Each task is capped at two hours, including its local checks. Corpus reviews use bounded batches of independent source
families; seeded variants increase occurrence counts, never independent-family support. If a batch cannot finish in its
cap, record the completed IDs and split the remaining IDs into another bounded checklist item before continuing.
All boxes describe future implementation work; no implementation occurs during proposal creation.

## 1. Regression evidence and evaluation foundation

- [ ] 1.1 [backend] (2h) Add synthetic failing fixtures for later-chunk offsets, stripped whitespace, oversized
  paragraphs,
  wrong source-column mutation, and duplicate-ID alignment; verify each reproduces the audited behavior in the current
  production path and document expected corrected output in the fixture manifest.
- [ ] 1.2 [backend] (2h) Add fixture cases for whitespace/error-object responses, fabricated spans, reversed/bool
  offsets,
  ignored thresholds, length termination, embedded JSON/prose and repaired escapes; verify current behavior is captured
  without network calls or private input and map every audit case to a spec scenario.
- [ ] 1.3 [backend] (2h) Implement strict corpus, prediction and authorization-manifest schemas under
  `src/docpipe/evaluation/pii/`; verify offset/text, duplicate-ID, review-state and field-type rejection tests.
- [ ] 1.4 [backend] (2h) Implement family-group split validation and content fingerprints; verify template/translated
  variants and modified locked manifests cannot cross or silently replace development/calibration/test splits.
- [ ] 1.5 [backend] (2h) Implement exact span/type and overlap diagnostic scoring; verify known TP/FP/FN examples,
  duplicate predictions, per-type support, empty predictions and missing required slices against hand-calculated values.
- [ ] 1.6 [backend] (2h) Implement full-span/character masking, emitted-document leakage, over-redaction and withholding
  metrics; verify a partially masked identifier fails full-span masking and withholding all rows cannot pass completion.
- [ ] 1.7 [backend] (2h) Implement document-family bootstrap intervals and slice reports; verify seeded reproducibility,
  correlated variant grouping and explicit insufficient support with a small fixed corpus.
- [ ] 1.8 [backend] (2h) Add offline `validate-corpus`, `score`, and `qualify` entrypoints in `scripts/evaluate_pii.py`
  and
  gate-profile validation; verify non-zero failures for missing thresholds, weak slices and deterministic violations.
- [ ] 1.9 [backend] (2h) Add explicit detector `run` mode, authorization checks and sensitive-output opt-in; verify
  network
  is blocked in scoring/import tests and remote runs require both the flag and appropriate manifest.
- [ ] 1.10 [backend] (1h) Document annotation policy, evaluation commands and denominator definitions in
  `docs/guides/PII_EVALUATION_GUIDE.md`, linked from the existing operator guide; verify relative links and offline
  examples.

## 2. Domain contracts and source mapping

- [ ] 2.1 [backend] (2h) Add immutable source, candidate, occurrence, assessment and issue records with explicit domain
  invariants (D1/D2); verify type/bounds/source-association tests and no domain imports from adapters.
- [ ] 2.2 [backend] (2h) Add plain-text/Markdown source views and exact source-fragment mappings; verify whitespace,
  CRLF, link destinations and non-ASCII literals preserve correct source coordinates.
- [ ] 2.3 [backend] (2h) Implement context/output token-budget validation and exact-slice window cores/overlap (D3);
  verify oversized paragraphs, final-tail coverage and unknown-tokenizer failures using deterministic fake tokenizers.
- [ ] 2.4 [backend] (2h) Implement window-edge handling, coverage union and source-occurrence deduplication; verify an
  entity crossing a window edge maps once, an unresolved edge requires review, and missing windows fail coverage; score
  scripted omissions by both windows and entities longer than overlap as semantic misses despite full submission
  coverage.
- [ ] 2.5 [backend] (2h) Add DocLang safe parsing and structural locators for text, tails and attributes; verify
  malformed
  XML rejection, entity-reference decoding, tag/attribute role profiles, validated structural references, unknown-role
  rejection and no external entity resolution.
- [ ] 2.6 [backend] (2h) Add DocLang context projection across adjacent inline fragments; verify split-node names map to
  all source fragments, block/attribute separators do not invent contiguous source characters, and every text value is
  covered.
- [ ] 2.7 [backend] (2h) Add structured masking serialization and original-node validation; verify tags, attributes,
  non-sensitive values and well-formedness survive while all accepted sensitive fragments are masked.
- [ ] 2.8 [backend] (2h) Add explicit offset-unit conversions and mapped optional comparison views; verify UTF-8/UTF-16,
  supplementary characters, NFC/NFD, case-fold expansion, and ambiguous normalized evidence fail or map without
  guessing.
- [ ] 2.9 [backend] (2h) Add grapheme-complete masking boundaries and mask validation; verify combining marks,
  apostrophes,
  accented names and invisible/control mask rejection, including measured extra masking.
- [ ] 2.10 [backend] (1h) Document source representation support, offset units and deprecated chunk hints in the
  existing
  operator guide; verify examples match the implemented view/window contract and unsupported formats are explicit.

## 3. Structured inference transport

- [ ] 3.1 [backend] (2h) Add the additive structured-inference port/result and factory construction path (D5); verify
  typed result fields, unsupported-provider errors and unchanged string `chat`/`generate` return types.
- [ ] 3.2 [backend] (2h) Implement LiteLLM non-streaming envelope extraction for content, finish reason, refusal, usage,
  request/model identity and unknown termination; verify object and dictionary transport fixtures, including `length`.
- [ ] 3.3 [backend] (2h) Implement strict-schema/explicit-JSON capability validation and custom tokenizer/context
  overrides;
  verify no schema option is silently dropped, static flow validation does not probe endpoints, and startup errors are
  actionable.
- [ ] 3.4 [backend] (2h) Implement one bounded assessment retry controller and disable nested retries in this path;
  verify
  total request counts for transient failure, permanent refusal, invalid schema and smaller-window recovery with full
  coverage.
- [ ] 3.5 [backend] (2h) Sanitize structured-client exception logging and diagnostics at their earliest boundary; verify
  echoed source text, raw responses and credentials never appear in captured DEBUG logs or returned failure details.
- [ ] 3.6 [backend] (1h) Document the additive port and endpoint contract in
  `docs/guides/UNIFIED_LLM_ARCHITECTURE_GUIDE.md`; verify existing inference examples and new completion metadata tests.

## 4. Grounding and decision policy

- [ ] 4.1 [backend] (2h) Add the strict PII quote/occurrence wire schema and parser (D6); verify required finite scores,
  duplicate keys, extra/trailing text, unknown labels, wrong types, oversized envelopes and zero-default rejection.
- [ ] 4.2 [backend] (2h) Add a separate versioned PII prompt with trusted instructions and encoded document data; verify
  requested types reach inference, embedded delimiters remain data, and generated example locators match exact source
  text.
- [ ] 4.3 [backend] (2h) Implement quote/occurrence/anchor resolution and native-offset grounding; verify repeated
  names,
  missing/invented quotes, contradictory anchors, negative/reversed spans and source-version mismatches cannot be
  accepted.
- [ ] 4.4 [backend] (2h) Add explicit canonical label/legacy alias conversion and provenance records at the PII
  boundary;
  verify known namespace aliases map while arbitrary containing strings fail and native adapters cannot bypass
  grounding.
- [ ] 4.5 [backend] (2h) Implement score floors and the initial source/type accept-review policy; verify score `0.01` at
  floor `0.99` is not accepted, no cross-provider score averaging occurs, and below-floor reported candidates require
  review.
- [ ] 4.6 [backend] (2h) Add occurrence deduplication, overlap union and conflict dispositions; verify independent
  detector
  silence cannot veto findings, checksum failures alone do not reject identifiers, and conflicting boundary evidence is
  explicit.
- [ ] 4.7 [backend] (1h) Document quotation grounding, threshold semantics and uncertainty in the existing PII guide;
  verify the new parser is used only by PII and unrelated forgiving-parser tests retain their behavior.

## 5. Hybrid provider

- [ ] 5.1 [backend] (2h) Add a PII candidate port and Presidio candidate adapter preserving pre-acceptance evidence;
  verify recognizer provenance, lower-score candidates, explicit offset units and unchanged standalone native
  thresholds.
- [ ] 5.2 [backend] (2h) Add the hardened LiteLLM PII candidate adapter using the structured port and strict quote path;
  verify complete coverage, response failure propagation and requested-entity scope without touching HAP-only inference.
- [ ] 5.3 [backend] (2h) Add the hybrid application coordinator injected with local and LLM ports; verify both inspect
  all windows, local misses do not prefilter LLM findings, and component failure never becomes degraded success.
- [ ] 5.4 [backend] (2h) Register `hybrid` as PII-only with nested component schemas and validated policy references;
  verify capability mismatches, recursive/unknown components, missing models/dependencies and existing selection
  precedence.
- [ ] 5.5 [backend] (2h) Verify model reuse and concurrent assessment with existing Presidio locking and thread-context
  propagation; assert deterministic mapping/assembly across repeated concurrent synthetic batches without network.
- [ ] 5.6 [backend] (1h) Add a hybrid example and provisioned-model instructions to the existing operator guide and
  operator reference; verify the sample validates with mocked dependencies and labels hybrid as unqualified until
  measured.

## 6. Operator integration and configuration

- [ ] 6.1 [backend] (2h) Add the D8 operator/provider configuration schemas and static metadata defaults; verify source
  columns/formats, language/profile mismatches, jurisdictions, budgets and evidence-column types through validation
  tests.
- [ ] 6.2 [backend] (2h) Replace hardcoded default-column checks with declared-column validation and immutable per-row
  requests; verify custom-only columns, null/blank input, invalid schema and duplicate IDs against real PyArrow tables.
- [ ] 6.3 [backend] (2h) Integrate all selected PII providers through shared assessment/grounding and source views;
  verify native WatsonX/Presidio records, standalone LiteLLM and hybrid obey the same source and failure contract.
- [ ] 6.4 [backend] (2h) Add declared content-copy and extraction-evidence handling; verify known unassessed copies and
  supplied incomplete-source evidence are withheld, while missing evidence is recorded as unknown rather than certified
  complete.
- [ ] 6.5 [backend] (2h) Implement retained-index row/group removal and atomic source-array assembly; verify both
  `partial_ingest` modes, duplicate-ID siblings, custom columns and no partially redacted output after a later-window
  failure.
- [ ] 6.6 [backend] (2h) Add typed count/status output and versioned assessment metadata; verify zero-row schemas,
  deduplicated per-column counts, withheld-sibling accounting, separate language-basis/qualification fields and failed
  status when all non-empty input is withheld.
- [ ] 6.7 [backend] (2h) Integrate PII/HAP shared mapping and deterministic overlap masking; verify independent
  providers,
  same-provider separate LLM calls, PII-failed/HAP-success row withholding, explicit mask precedence, unchanged HAP-only
  schemas and unchanged native HAP thresholds.
- [ ] 6.8 [backend] (2h) Reject PII display during redaction and replace sensitive per-document diagnostics with opaque
  references; suppress raw HAP-parser and native-adapter error logging at their origin. Verify full operator DEBUG logs,
  metadata and error routes contain no protected text, including PII echoed by a mixed run's HAP response.
- [ ] 6.9 [backend] (2h) Update `docs/reference/OPERATORS.md`, the existing PII operator guide and a new English sample
  flow with all effective defaults, breaking behavior, content boundary and score meanings; verify flow validation and
  links.
- [ ] 6.10 [backend] (2h) Test the existing operator metadata/flow-validation API surfaces with new schemas and invalid
  selections; verify HTTP/DTO contracts and generic properties-panel schema compatibility without adding frontend
  controls.

## 7. Reviewed English corpus

- [ ] 7.1 [backend] (2h) Create the versioned annotation-policy and corpus-family manifest with all 13 label
  definitions,
  jurisdiction-unknown handling and required stress/domain slices; verify support planning covers D10 gates without
  split leakage.
- [ ] 7.2 [backend] (2h) Add seeded insertion-based generators and exact gold locators, including negatives, for
  reviewed
  template families; verify generated evidence invariants and that variants retain the same family ID and split.
- [ ] 7.3 [backend] (2h) Independently review up to 50 bank-account positive families and their gold semantics; verify
  recorded review provenance, valid/invalid-format contexts and source-span tests for the completed batch.
- [ ] 7.4 [backend] (2h) Independently review the next up to 50 bank-account positive families; verify the combined
  slice
  meets 100 reviewed positive families and 200 positive occurrences without treating variants as independent families.
- [ ] 7.5 [backend] (2h) Independently review up to 50 credit-card positive families; verify review provenance and
  exact locators, including contextual identifiers that fail a known checksum.
- [ ] 7.6 [backend] (2h) Independently review the next up to 50 credit-card positive families; verify the combined
  100-family/200-occurrence minimum and reviewed-negative separation.
- [ ] 7.7 [backend] (2h) Independently review up to 50 SSN positive families; verify contextual meaning and exact spans
  alongside superficially similar non-SSN numbers in the annotation policy.
- [ ] 7.8 [backend] (2h) Independently review the next up to 50 SSN positive families; verify the combined
  100-family/200-occurrence minimum and family-disjoint split membership.
- [ ] 7.9 [backend] (2h) Independently review up to 50 passport positive families; verify contextual labels,
  international-format diversity and explicit unknown jurisdiction.
- [ ] 7.10 [backend] (2h) Independently review the next up to 50 passport positive families; verify the combined
  100-family/200-occurrence minimum and no unsupported country-wide coverage claim.
- [ ] 7.11 [backend] (2h) Independently review up to 50 driver-license positive families; verify source locators,
  subtype context and jurisdiction evidence independent of document language.
- [ ] 7.12 [backend] (2h) Independently review the next up to 50 driver-license positive families; verify the combined
  100-family/200-occurrence minimum and recorded annotation disagreements.
- [ ] 7.13 [backend] (2h) Independently review up to 50 national-ID positive families; verify distinction from
  SSN/passport
  labels and source evidence without relying on a universal identifier regex.
- [ ] 7.14 [backend] (2h) Independently review the next up to 50 national-ID positive families; verify the combined
  100-family/200-occurrence minimum and explicit annotation-policy resolution of ambiguous types.
- [ ] 7.15 [backend] (2h) Independently review up to 50 medical-record positive families; verify context-sensitive
  labels
  and separation from ordinary appointment dates or unrelated reference numbers.
- [ ] 7.16 [backend] (2h) Independently review the next up to 50 medical-record positive families; verify the combined
  100-family/200-occurrence minimum and representative record-format diversity.
- [ ] 7.17 [backend] (2h) Independently review up to 50 person-name positive families and seeded variants; verify the
  50-family/100-occurrence minimum, accented/compound names and ambiguity policy.
- [ ] 7.18 [backend] (2h) Independently review up to 50 address positive families and seeded variants; verify the
  50-family/100-occurrence minimum, multiline addresses and city-name hard-negative distinctions.
- [ ] 7.19 [backend] (2h) Independently review up to 50 birth-date positive families and seeded variants; verify the
  50-family/100-occurrence minimum and separation from ordinary dates across international date formats.
- [ ] 7.20 [backend] (2h) Independently review up to 50 email positive families and seeded variants; verify the
  50-family/100-occurrence minimum, repeated occurrences, link destinations and exact punctuation boundaries.
- [ ] 7.21 [backend] (2h) Independently review up to 50 phone positive families and seeded variants; verify the
  50-family/100-occurrence minimum, international prefixes and non-phone numeric negatives.
- [ ] 7.22 [backend] (2h) Independently review up to 50 IP-address positive families and seeded variants; verify the
  50-family/100-occurrence minimum and contextual version-number/non-address negatives.
- [ ] 7.23 [backend] (2h) Review a bounded batch of up to 25 multi-label hard-negative families with seeded variants;
  verify the negative support report identifies any remaining per-type gaps instead of silently qualifying them.
- [ ] 7.24 [backend] (2h) Review a second bounded batch of up to 25 hard-negative families targeting the reported gaps;
  verify at least 100 reviewed negative documents per requested type or add explicit bounded gap-review tasks.
- [ ] 7.25 [backend] (2h) Review up to 25 cross-cutting Unicode/OCR/structure stress families and their tagged variants;
  verify NFC/NFD, apostrophes, hyphens, DocLang split nodes, attributes and noisy extraction locators.
- [ ] 7.26 [backend] (2h) Review up to 25 boundary/repetition/injection/failure stress families and tagged variants;
  verify every required stress slice has 25 independent reviewed families, adding bounded gap batches when necessary.
- [ ] 7.27 [backend] (2h) Assemble development/calibration/locked manifests from reviewed families, reserving enough
  independent locked support for D10; verify locked minima specifically, not merely full-corpus counts. Add bounded
  review
  batches for any split-support deficit before freezing; do not reuse a family across splits. Review and freeze the
  profile-versioned numeric gates after support feasibility is verified and before calibration or locked inference.
- [ ] 7.28 [backend] (1h) Record corpus review/usage provenance, licenses and scope in the evaluation guide; verify no
  private documents, sensitive predictions or unreviewed model-generated labels are committed as qualifying gold data.

## 8. Qualification and integration checks

- [ ] 8.1 [backend] (2h) Capture hardened LLM-only, local-only and hybrid development predictions with exact
  configuration
  fingerprints on synthetic or authorized inputs; verify all three use the same corpus and report failures/costs
  honestly.
- [ ] 8.2 [backend] (2h) Calibrate source/type policies using calibration data only against the already frozen D10
  gates;
  verify reviewed policy fingerprints, no cross-source score averaging and locked test data was not used for tuning.
- [ ] 8.3 [backend] (2h) Run locked evaluation and ablation reports, splitting long runs into resumable bounded batches;
  verify slice gates, bootstrap intervals, full-artifact exposure and completion rates. A failing run remains
  unqualified.
- [ ] 8.4 [backend] (2h) Integrate a qualification report only for an exact passing configuration; verify changed model,
  prompt, window, tokenizer or policy invalidates it and no English result advertises additional-language qualification.
- [ ] 8.5 [backend] (2h) Run CLI, library and REST job-run smoke tests with deterministic adapters and downstream test
  sinks;
  verify unresolved documents are withheld and selected output counts/statuses remain correct end to end.
- [ ] 8.6 [backend] (2h) Run concurrent micro-batch tests with duplicate IDs, multiple text columns and mixed provider
  outcomes; verify request/source association, thread-local context and retained-row alignment against sequential
  results.
- [ ] 8.7 [backend] (2h) Complete the spec-scenario traceability manifest and run targeted PII, inference and evaluation
  suites, then the backend unit suite; verify every scenario has a passing test or a recorded qualifying evaluation
  case.
- [ ] 8.8 [backend] (2h) Run `uv run ruff check --fix .` and `uv run mypy .` and verify packaging/imports;
  if dependencies changed, run `uv lock`
  and `uv pip install -e ".[dev]"`, then confirm `pyproject.toml`/`uv.lock` are paired and the intended extras work
  offline.
- [ ] 8.9 [backend] (1h) Validate all changed documentation links, sample flows and
  `openspec validate harden-multilingual-pii-detection --strict`; verify no canonical/archived specs, changelog,
  frontend
  routing, BFF or Redux files changed, and recheck the pending HAP namespace/partial-ingest conflict for the reviewer.

## Workflow follow-up

- Review proposal, spec deltas, design and proposed numeric release bars before implementation is approved.
- After implementation and review, commit with `git commit -s`; run
  `pre-commit run --from-ref origin/main --to-ref HEAD` before pushing, using the actual PR base for stacked branches.
- Before archive, reconcile the pending HAP change's shared capability and failure wording through the appropriate
  review workflow. Never edit the other change or live specs as a side effect of implementing this one.
- Archive with `openspec archive harden-multilingual-pii-detection` only after implementation checks and review pass;
  verify both capability namespaces contain the intended requirements afterward.
