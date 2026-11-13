# Design

## Table of contents

- [Context](#context)
- [Goals / Non-Goals](#goals--non-goals)
- [Decisions](#decisions)
- [Risks / Trade-offs](#risks--trade-offs)
- [Migration Plan](#migration-plan)

## Context

See [proposal](proposal.md) for motivation and the [operator contract](specs/backend/pii-and-hap-operator/spec.md) and
[evaluation contract](specs/backend/pii-detection-evaluation/spec.md) for behavior.

The audited path is `PIIAndHAPAnnotator -> PIIHAPService -> capability ports -> outbound adapter -> inference port`.
The annotator already supports independent PII/HAP providers, thread-pool execution, partial-ingest handling, and
metadata-backed configuration. Preserve those integration points rather than introducing a separate operator.

Audit evidence, independently checked with three Luna agents at high reasoning:

- Later-chunk email evidence at local `[8:26]` redacts early source characters rather than the actual occurrence.
- Eight of twenty few-shot detections disagree with their source substrings. All seven examples are English.
- Whitespace, `{}`, and an error object become empty detections; fabricated text and score `0.01` pass a `0.99` request.
- A custom `source_text` can remain unchanged while its redacted value overwrites `content`.
- Failure of one `dup` row removes its successful sibling but leaves two annotation values for one retained `ok` row.
- Existing adapter/service tests pass (31 tests), including assertions that blank replies yield no detections.
- The client discards finish reasons; the shared parser extracts embedded objects and repairs evidence escapes.

These are pipeline findings. Model recall, prompt-injection success rates, and hybrid superiority are not yet measured.
Presidio's existing English spaCy NER and locale recognizers supply the first local baseline; adding another model
library is not necessary to implement this architecture. Public benchmarks are supplemental, not production evidence.

The pending [HAP proposal](../add-huggingface-hap-provider/proposal.md) uses the same future capability namespace but
excludes chunk mapping. Its `partial_ingest=false` scenario says batch rows are removed, whereas the actual helper
removes matching document IDs. This change specifies observed document-group semantics and records the conflict for
review; implementation must not rewrite the other change or canonical specs.

## Goals / Non-Goals

**Goals:** independently test source fidelity, response validity, semantic detection, decision policy, and emitted text;
keep uncertainty distinct from absence; permit English-first improvements without assuming language equals jurisdiction.

**Non-Goals:** a new orchestration system, generic policy engine, arbitrary plugin composition language, automatic model
selection, or a claim that JSON schemas, checksums, or detector agreement prove PII completeness.

## Decisions

### D1. Separate candidate evidence, accepted occurrences, and document assessments

Add strict domain records under `pii_and_hap/domain/`: `SourceView`, `SourceSegment`, `CandidateEvidence`,
`GroundedOccurrence`, `AssessmentIssue`, `CoverageProfile`, and `DocumentAssessment`. Plain immutable dataclasses plus
explicit invariant constructors keep framework concerns outside domain behavior; wire schemas use strict Pydantic models
in adapters. Validate at the shared service boundary as well, so native adapters cannot bypass grounding.

`SourceView` owns an immutable column value/version and a representation map. A segment contains an opaque ID, exact
analysis substring, source locations, context bounds, and a core coverage interval. An occurrence contains canonical
type,
column/view reference, one or more source fragments, provider/model/prompt provenance, optional jurisdiction/subtype,
score kind, and policy disposition. Candidates never masquerade as accepted occurrences.

Use row position plus an invocation-local opaque row key for assembly. Keep document ID solely for group-removal policy.
Content fingerprints are internal association checks, not anonymization; never log per-document fingerprints by default.

Assessment states are `assessed`, `review_required`, `incomplete`, `unsupported`, and `failed`. The last four are
withheld.
A valid empty provider response can yield `assessed` only after all required coverage completes without unresolved
evidence. No state is named `safe` or `clean`.

Alternative: make the existing permissive `DetectionResult` dataclass stricter globally. Rejected as the sole solution:
it still conflates wire output with grounded evidence and risks changing HAP-only adapters unnecessarily. Keep a legacy
adapter bridge where necessary, but PII cannot reach redaction through that bridge without shared validation.

### D2. Layer ownership and dependency direction

| Layer | Ownership and intended paths |
| --- | --- |
| Domain | Invariants, source fragments, decisions, coverage profiles in `pii_and_hap/domain/` |
| Application | Assessment/window coordination, grounding and reconciliation in `pii_and_hap/services/` |
| Ports | PII candidate and structured completion contracts in operator ports and `core/ports/` |
| Adapters | Strict provider schemas, label/offset conversion, Presidio/LiteLLM/hybrid wiring under outbound adapters |
| Integration | LiteLLM transport response extraction, tokenizer/model capabilities and sanitized transport errors |
| Operator | PyArrow validation, context-preserving scheduling, retained-row assembly, metadata and source-column mutation |
| Evaluation | Corpus/prediction validation, scoring and profile gates in `src/docpipe/evaluation/pii/` |

Application services depend on ports, never concrete provider adapters. The adapter factory builds hybrid components and
injects them; the hybrid application coordinator receives two PII candidate ports. Session context remains thread-local.
No operator talks to storage directly. Pure private helpers remain static methods on their owning classes.
Candidate requests carry requested entity types and the source/profile reference. Adapters pass supported type filters
to native detectors where possible. A legacy bridge can filter known unrequested types before decisions; unknown labels
still fail conversion instead of being silently dropped as if they established absence.

### D3. Lossless, token-bounded views replace paragraph reconstruction only in this path

Add a PII/HAP segmenter in the assessment services; do not change generic `utils/core/strings.py` for unrelated callers.
Use exact source ranges, reserving actual prompt and output budgets. Prefer paragraph/sentence boundaries within the
budget, but hard-bound oversized paragraphs. Each window has a non-overlapping core interval plus left/right context.
Require union coverage of all source text values, including material at the final window.

Use the actual endpoint tokenizer/context capability or explicit operator configuration when a custom alias cannot be
resolved. Unknown budgets fail startup rather than using character count as a guessed token limit. A default overlap
of 128 model tokens supplies boundary context; it is versioned and evaluated, not a universal entity-length guarantee.
Evidence touching an unresolved window edge triggers a larger-context retry or review. Bound retries and never truncate.
Submission coverage proves only that text reached the detectors. It cannot detect an entity omitted by every window.
Include scripted dual-window omissions and entities longer than the default overlap in semantic scoring; those are gold
misses even when structural coverage passes. The profile records tested entity/context lengths and never asserts that
128 tokens guarantees discovery of arbitrary-length entities.
These tokenizer requirements apply to LLM paths. Native local/API adapters expose their own input-cap contract and use
source-preserving windows within that cap; a Presidio-only or native HAP-only flow does not require an LLM tokenizer.

Deduplicate on column, mapped source fragments, and canonical type after grounding. If contextual boundaries disagree,
resolve through source evidence or mark review; do not hide the conflict with fuzzy positional merging.

`min_chunk_size_kb` and `max_chunk_size_kb` remain deprecated legacy source-character hints, matching observed
historical
behavior despite their names. They never override token safety. New token settings are authoritative; warn without
document content when a legacy hint is supplied. Record the effective window policy in assessment provenance.

Alternative: add cumulative chunk lengths. Rejected because trimming and reconstructed separators break the mapping.

### D4. Representation and Unicode handling are explicit

Plain text and Markdown are assessed as exact original strings, including link destinations and markup values; masked
spans retain source punctuation outside the approved region. DocLang uses safe XML parsing with structural locators for
`.text`, `.tail`, and textual attribute values. Context can join adjacent inline fragments, while every analysis range
maps back to the individual source-node spans. A name split by inline markup can produce several redaction fragments.
Serialize through the safe tree and verify well-formedness and non-sensitive node values; byte-identical XML
serialization
is not required. Do not use a whole-XML string offset to cut through tags.

Use a format-version profile of exact tag/attribute roles, grounded in the installed Docling vocabulary. For example,
`location.value/resolution` describe geometry while `group.name` and `href.uri` can carry content. Treat known semantic
attributes (including `group.name` and `href/src.uri`) as independently mapped assessment values. Preserve namespace,
version, bounded layout/enum attributes, and document-local reference attributes only after their schema constraints and
reference integrity validate. Use positive document-local reference IDs consistent with the producer's allocation;
arbitrary free-form identifiers are not exempt just because the attribute is named `thread_id`.
Unrecognized tag/attribute roles cause `UNSUPPORTED_COVERAGE`, requiring a reviewed format-profile extension. Do not
blindly classify every `value` attribute as prose or let an arbitrary exclusion list exempt user text. A profile lists
validated structural roles separately from its textual protection boundary; masking never breaks structural references.
Unsupported additional representations fail when declared or detected as an unassessed content copy. Detect known copies
from extraction output constants plus available feature metadata, not a broad regex over every column name.

The initial analysis view preserves original Unicode. Optional NFC/case-fold comparison produces a separate mapped view;
it cannot rewrite the source or guess a match. Use explicit code-point/UTF-16/byte conversion, expand masking boundaries
to complete affected grapheme clusters, and evaluate the resulting extra masking. NFKC folding is not a default identity
rule. Translation, transliteration and ASCII-only name validation do not determine redaction coordinates.

Alternative: normalize the document in place before detection. Rejected because it changes evidence and source offsets.

### D5. Add a completion-aware inference port without changing string consumers

Add `StructuredLLMInferencePort.complete_structured()` and `LLMCompletionResult` alongside `LLMInferencePort`.
The result contains content, normalized termination (`complete`, `length`, `refusal`, `filtered`, `unknown`), provider
request ID, resolved model/revision if known, usage, and response-contract mode. Existing `chat()`/`generate()` continue
returning strings. The factory exposes a typed structured-inference construction path; unsupported adapters fail
clearly.

LiteLLM's structured path returns the real transport envelope, forces non-streaming initially, and validates endpoint
capabilities at execution startup using non-sensitive probes. Static flow validation validates configuration only.
Prefer native strict schemas. A JSON-only endpoint is permitted only with explicitly configured `response_contract=json`
and strict application validation; qualification identifies that mode. Never silently drop schema parameters.
Unknown termination is incomplete even when the content looks like valid JSON.

One assessment retry controller owns the total attempt budget (default two attempts per segment, counting transport,
schema and resized-window attempts). Disable nested integration retries for this path. Only transient errors, output
exhaustion with a smaller valid window, or a structural retry are retryable; permanent refusal does not trigger a loop.
No retries may drop prior coverage. Existing unrelated retry behavior remains unchanged.

### D6. Quote-grounded extraction removes dependence on LLM character counting

Use a new versioned PII prompt/strict wire schema, separate from HAP classification. Instructions live in a system
message; user data is an encoded document/segment object. Explicitly state that embedded instructions are data and
request only `pii_list`. No tools or document-selected endpoints are exposed to the extraction model.

The response contains `detections`, each with canonical `detection`, `detection_type=pii`, exact `text`, and a locator
with
one-based exact `occurrence` within the segment plus optional exact prefix/suffix anchors. An explicit `uncertain` value
supports abstention. Required finite self-reported `score` remains uncalibrated. Application code enumerates exact
occurrences,
checks every supplied anchor, derives offsets, and maps to the immutable source. Never case-insensitively replace all
quotations or silently correct contradictory locators. Require a separate item for each occurrence the model identifies.

Native providers can supply strict offsets instead, with documented units. Both paths converge on the same grounded
record. If an adapter supplies both offsets and text, both must agree. Unknown labels fail; known historical namespace
aliases use an explicit mapping table. Validate JSON duplicate keys, non-finite numbers, sizes, all fields, and no
trailing
prose. Do not call the forgiving generic JSON parser for PII or alter its behavior for other operators.

Generate prompt example coordinates/locators mechanically from source literals and assert every example's invariants.
Add negative/contextual examples and Latin-script names; do not use the release test set as few-shot material.

Alternative: ask the model to produce more accurate offsets and fix them with nearest-string searches. Rejected because
repeated entities, accented strings, and ambiguous matches can move an accepted detection to the wrong occurrence.

### D7. Hybrid is a measured, opt-in provider with independent coverage

Register `hybrid` as PII-only; retain `litellm`, `watsonx`, `presidio` and all existing selection precedence.
`pii_provider_config` for hybrid contains `local_provider_config` (existing Presidio schema), `llm_provider_config`
(hardened LiteLLM schema), and `policy_profile`. Both components are mandatory and inspect all required windows.
Presidio contributes its existing spaCy NER and maintained recognizers; the LLM independently supplies contextual PII
including DOB/address/medical identifiers absent from the default local mapping. A registry of candidate ports permits
a future span-native model without adding it to this change or reserving the pending HAP provider's `huggingface` name.

The local candidate path requests available candidates before final acceptance filtering, preserving lower-score
evidence. Existing standalone native adapters keep their threshold semantics. Maintain source evidence for each
candidate even when another detector is silent. Component failure means incomplete hybrid assessment, not fallback.

Reconciliation uses a versioned per-source/type decision table with `accept`, `review`, and `reject_not_pii`
dispositions.
Initial conservative policy: accept grounded native candidates meeting their source threshold; accept grounded LLM
positive candidates without an uncertainty marker that meet the configured LLM score floor; send uncertain,
contradictory, ungrounded, or below-threshold reported candidates to review. Silence alone is not a contradiction.
Different accepted types at the same location retain both type counts and one masking union. LLM disagreement cannot
veto accepted native evidence. A known checksum result is an evidence feature, not a stand-alone rejection rule.

When both PII and HAP use the same LiteLLM provider, use separate PII quote extraction and existing capability-scoped
HAP
inference rather than the old combined-call shortcut. Native dual-capability transports can retain an internal combined
request only when their results satisfy both contracts independently. Windows can differ by capability but carry maps
to the same immutable row source; PII completeness cannot be inferred from HAP success.

Preserve `pii_threshold` as the standalone provider score floor and the hybrid local floor. Hybrid can override floors
per source/type in its reviewed profile; never average scores. The LLM wire schema requires a score and applies the
configured floor deterministically; a missing score is invalid. Confidence numbers and structurally grounded evidence
are
not proofs of sensitivity; the evaluation gates test this permissive positive policy for over-redaction.

Alternative: use Presidio as an LLM prefilter or let an LLM approve every local finding. Rejected because either
detector's
misses/rejections would suppress the other's useful evidence. Hybrid becomes a recommendation only after ablation
results.

### D8. Language, jurisdiction, and qualification are different properties

New metadata-backed operator configuration:

| Key | Default and behavior |
| --- | --- |
| `pii_language` | `en`; declared BCP-47 language, English support in this release |
| `pii_language_column` | absent; optional supplied per-row language tags checked against the declared profile |
| `pii_jurisdictions` | `[]`; unspecified, not implicitly US; preserves unknown subtype/jurisdiction |
| `pii_content_columns` | `[doc_column]`; non-empty unique string list, all assessed before row release |
| `pii_content_formats` | primary inherits `doc_format`; remaining columns require explicit text/markdown/doclang formats |
| `pii_source_evidence_column` | absent; optional struct with `complete: bool|null` and sanitized failure codes |
| `pii_policy_profile` | `english-v1`; versioned entity policy, window policy, decisions, and qualification reference |
| `pii_max_input_tokens` / `pii_overlap_tokens` | effective endpoint budget / 128; validate bounds and budget reservations |
| `pii_max_output_tokens` / `pii_max_attempts` | 4096 / 2; bounded by actual endpoint context capability |

LiteLLM provider configuration adds `response_contract` (`schema` default or explicit `json`), optional `tokenizer_id`
and `context_window_tokens` for unresolved aliases, and a pinned model revision/deployment fingerprint for
qualification.
Model-specific options remain in provider config. Publish all schemas/defaults through existing metadata; no new UI
form.

Supplied non-English/unknown language tags or conflicting provider-language settings cause `UNSUPPORTED_COVERAGE`.
An omitted tag is recorded as declared English, not as measured language detection. Automatic language detection is not
introduced here: short names and identifiers cannot be reliably language-classified, and an English declaration is not
proof every passage is English. Mixed-language documents are a diagnostic stress slice; known unqualified segments fail.
Do not use a character-script whitelist to decide language or sensitivity.

Profiles distinguish supported execution from benchmark qualification. A user-configured English endpoint can run
with `qualification=unverified`, while its output status means only that assessment completed. Only an exact matching
passing report permits a qualified-accuracy claim. No language profile or arbitrary model is pre-certified by this work.
Adding a qualified Latin-script language requires a new in-language reviewed profile, not a code fork or prompt
translation.
Metadata has separate `coverage.language`, `coverage.language_basis` (`declared` or `supplied`), source-evidence state,
and `qualification.status` (`unverified` or `qualified`) with a matching report fingerprint. A foreign passage without
supplied language evidence is not claimed to be detected automatically or rejected by script heuristics.

### D9. Withhold unresolved rows before mutating or assembling output

Collect immutable per-row results, calculate a retained-index mask once, then build every output column and metric from
that same selection. With `partial_ingest=false`, an issue in any column/window withholds its document ID group. Track
withheld siblings separately so attempted/assessed/emitted counts do not imply that a removed sibling was emitted.

Only after all required column assessments succeed, compute masking unions and build replacement arrays. Validate a
single visible non-alphanumeric masking code point (default `*`); reject whitespace, combining/control/invisible values.
HAP and PII overlap masking uses the PII mask for shared fragments while retaining independent accepted detection
counts.
This precedence applies only when both masks are enabled. If PII masking is disabled, only the HAP mask changes text.
PII failure/review withholds the whole row, including successful HAP annotations; metadata can count HAP attempts but
emitted HAP totals and columns use retained rows only. This mixed-capability behavior is an explicit compatibility
change.
`redaction=false` leaves strings untouched. Preserve HAP-only schema and native scoring; shared mapping fixes still
apply.

PII output has existing `int64` count columns plus string `pii_assessment_status=assessed`. Counts deduplicate per
source
column; the same email in two declared representations counts twice, matching two emitted text occurrences. Nested
`metadata.pii_assessment` contains version, attempted/assessed/emitted/withheld row totals, review/incomplete/failure
counts,
reason-code histogram, declared coverage, effective provider/policy versions, and qualification state. Existing
lifecycle
keys remain, with `Failed` when no non-empty input row survives and completed-with-errors for mixed outcomes.

`display_pii=true` is rejected when PII redaction is enabled; explicit annotation-only debugging remains sensitive.
Default diagnostics use opaque row references. Sanitize exception details at the integration boundary before generic
client logging; sanitizing only after an exception has already been logged is insufficient. Do not retain raw responses
in default job metadata. Shared generic parsers and unrelated operators keep their existing behavior.
Disable raw-response logging in this operator's existing HAP parser branch too: a HAP response can echo PII from the
same document even when its scoring and parsing semantics remain unchanged. Native PII adapter errors must be sanitized
before their own logging, not just when the shared service catches them.

### D10. Reproducible evaluation with gates that cannot reward withholding everything

Implement a thin `scripts/evaluate_pii.py` entrypoint over `src/docpipe/evaluation/pii/` with `validate-corpus`, `run`,
`score`, and `qualify` subcommands. Scoring stored predictions and qualification are offline. `run` requires an explicit
`--allow-remote` for remote endpoints plus a corpus authorization manifest; no import-time model calls or downloads.
Use existing PII ports and the real operator for final-artifact tests, not a second implementation of
detection/redaction.

JSONL gold records identify opaque document/family IDs, text representations, language, jurisdiction, domain/stress
tags,
split and provenance, review state, and gold type/quotation/locator. A manifest locks files, split family membership,
annotation policy, and review records. Synthetic gold is generated from known inserted source positions; independently
review its semantics and negatives. A model cannot grade its own test annotations. Reviewed public records and
authorized
representative extraction samples supplement synthetic templates; record licenses and keep private data outside git.

Use exact matching for primary span/type scores, overlap only as diagnostics, original-source
sensitive-character/full-span
masking checks, and document-level residual exposure. For DocLang compare mapped node values, not string serialization
positions. Report whole-corpus detector recall with unresolved cases counted as misses, successful release coverage,
withholding, and emitted-artifact leakage separately. Include grouped bootstrap 95% intervals by document family and
support counts; do not pretend multiple identifiers in one template are independent samples.

Proposed `english-v1` engineering release bars, to review with this planning change and freeze before calibration/test:

| Gate | Initial value |
| --- | --- |
| Exact span/type precision and recall | at least 0.90 precision and 0.95 recall for each of all 13 requested types |
| High-sensitivity full-span masking recall | at least 0.99 for each bank/card/SSN/passport/license/national-ID/medical type |
| Sensitive-character recall | at least 0.995 overall and within each required high-sensitivity type |
| Residual leakage among emitted documents | at most 0.01 observed document fraction, with confidence interval reported |
| Non-sensitive-character masking | at most 0.02 overall and in each required document-domain slice |
| Assessment completion | at least 0.95 overall and per required ordinary-document domain; injected failure fixtures separate |
| High-sensitivity support | at least 200 positive occurrences across 100 document families per type |
| Other-type support | at least 100 positive occurrences across 50 document families per type |
| Hard-negative and stress support | at least 100 negative documents per type and 25 families per required stress slice |
| Structural and pipeline invariants | zero accepted invalid spans, false-success failures, or known mapping regressions |

These are proposed measured release criteria, not current accuracy claims or a statistical zero-risk guarantee.
Store the values in the reviewed `english-v1` gate artifact, never as universal code defaults. Confirm corpus support
feasibility and review the profile before freezing it; implementation of scoring does not itself qualify any
configuration.
Do not lower thresholds after inspecting the locked test set. If a configuration fails, keep it unqualified, change the
detector/policy using development data, and use a fresh locked split for another selection cycle. Missing domain samples
limit the claimed profile; generic synthetic results cannot qualify a customer's actual domain.

Benchmark hardened LLM-only, existing local-only, and hybrid with fixed source coverage; compare legacy behavior only as
a diagnostic baseline. Record mutable hosted aliases as non-reproducible unless deployment identity is attested.
No default-model replacement occurs without passing evidence. Default reports contain metrics and opaque references;
source/prediction evidence needs explicit sensitive-artifact output and is excluded from normal logs and source control.

### D11. Acceptance traceability and coordination

Regression fixtures cover every audited defect before changing acceptance assertions. Every new spec scenario maps to a
test or a named evaluation case in a manifest. Add integration coverage for concurrent micro-batches, multiple declared
columns, duplicate document IDs, source-format conversion, and PII/HAP independent provider selection.

The two new capability files contain disjoint requirement names from the pending HAP change. Before archive, re-read
the canonical inventory and the pending HAP delta; archive merges into the same namespace. Do not add a duplicate
`pii-operator` namespace, edit historical archives, or change unrelated engine contracts.

## Risks / Trade-offs

- **[Conservative review raises withholding]**: expose review reasons and completion rates; qualification gates cap
  withholding, so a detector cannot improve apparent privacy by rejecting every difficult document.
- **[Hybrid latency and cost]**: both paths inspect coverage; bounded windows, output budgets, shared immutable models,
  measured concurrency, and batching reduce cost without silently removing one path.
- **[Structured output is not semantic assurance]**: independent gold data, adversarial cases and final-artifact scoring
  remain mandatory. Prompt separation reduces ambiguity but is not a security proof.
- **[Unsupported endpoints]**: keep string APIs stable, explicitly fail missing completion/budget capability, and
  provide
  non-sensitive contract diagnostics for custom endpoints rather than guessing their behavior.
- **[Qualification data effort]**: annotation/review is real work. Separate the deterministic regression fixture set
  from
  the reviewed qualification corpus; do not mark a release qualified because unit tests or a small smoke run pass.
- **[Source representation complexity]**: structurally map DocLang and reject unsupported formats; never mask an
  arbitrary
  serialized offset through tags. Tests cover split nodes, entity references, attribute values and serializer round
  trips.
- **[Normalization overreach]**: preserve original strings; compare through explicit maps and measure grapheme expansion
  as over-redaction. No universal punctuation/ASCII regex gates for person names or addresses.
- **[Sensitive alternate fields]**: known content copies must be assessed; arbitrary metadata and upstream storage
  remain
  outside the stated boundary. Downstream users must not label the entire original document store sanitized.
- **[Changing observations invalidate evidence]**: model, prompt, tokenizer, policy, window, or corpus changes
  invalidate
  the exact qualification fingerprint; rerun the gate rather than reusing an old accuracy claim.

## Migration Plan

1. Land audited regression fixtures, corpus schemas and scoring first; capture an explicitly unqualified baseline.
2. Land source maps, structured completion and strict validation behind tests, then wire shared PII assessment and
   deterministic row assembly. Preserve string inference callers and HAP-only schemas throughout.
3. Add opt-in hybrid and metadata-backed configuration; document new failure behavior, profile scope, content copies,
   score semantics, required optional dependencies and model provisioning.
4. Run English calibration/ablation, freeze profiles and locked test manifest, and qualify only exact passing
configurations.
   Use synthetic or expressly authorized data for any remote run; this planning workflow performs none.
5. Smoke-test representative flows through CLI, library, REST execution and concurrent micro-batching. Verify withheld
   documents never reach downstream test sinks and logs contain no protected text.
6. Review compatibility notes and affected downstream readers before deployment. No data migration is required.
   Rolling back code removes these safety repairs and invalidates qualification; previously withheld inputs remain
   withheld until explicitly reassessed. Never auto-replay them through the old path or label old artifacts protected.
