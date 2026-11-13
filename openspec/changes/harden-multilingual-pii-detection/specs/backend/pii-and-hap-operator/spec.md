# Spec Delta

## Purpose

Assess personally identifiable information in declared document text, retain verifiable source evidence, and emit only
successfully assessed rows with optional deterministic masking. Coverage and assessment status describe the protection
boundary without promising that a model detects every sensitive entity.

## ADDED Requirements

### Requirement: PII input table contract

The operator SHALL accept a PyArrow table with a configured string or large-string content column, non-null string or
integer `id`, and string `name`. Missing required columns or invalid column types SHALL fail before inference.
Null, empty, or whitespace-only content SHALL be an explicit row assessment failure. Duplicate IDs SHALL remain valid
document groups and SHALL NOT substitute for row identity.

#### Scenario: Custom source column

- **WHEN** `doc_column` is `source_text` and the table has valid `source_text`, `id`, and `name` columns without
  `content`
- **THEN** validation succeeds and detection and masking use `source_text`

#### Scenario: Empty document content

- **WHEN** a row contains null, empty, or whitespace-only text
- **THEN** no provider is called for that value and the row is recorded with an input-assessment failure, not zero
  findings

### Requirement: Declared PII content boundary

PII assessment SHALL cover every column in `pii_content_columns`, defaulting to the configured `doc_column`.
Redaction SHALL reject an input containing a known alternate extracted-text column outside that declaration.
The operator SHALL NOT describe unassessed columns, upstream files, images, or previously stored artifacts as protected.

#### Scenario: Alternate text copy

- **WHEN** redaction receives primary Markdown plus an extracted plain-text copy that is not declared for assessment
- **THEN** the row is withheld with `UNASSESSED_CONTENT_COPY` rather than emitting the unredacted copy

#### Scenario: Two declared representations

- **WHEN** both textual representations are declared and each assessment completes
- **THEN** both are masked independently using their own source maps before the row is emitted

### Requirement: Source-preserving assessment coverage

Every assessed segment SHALL retain its exact source range or structural location. Successful assessment SHALL require
complete coverage of the declared text. Segment size SHALL respect provider context and output budgets; overlaps SHALL
preserve entity context without duplicate counts. Whitespace changes or normalization SHALL NOT invalidate source maps.

#### Scenario: Later window detection

- **WHEN** an email appears only in the second assessment window
- **THEN** its final coordinates address that email in the original column and masking leaves unrelated earlier text
  intact

#### Scenario: Oversized paragraph and boundary entity

- **WHEN** a paragraph exceeds the provider budget and an entity crosses a window boundary
- **THEN** bounded overlapping windows cover it and reconciliation reports each resolved source occurrence once

#### Scenario: Uncovered source range

- **WHEN** a required segment is missing, rejected, or cannot be mapped back to the source
- **THEN** the row assessment is incomplete and the row is withheld

### Requirement: Structured document text fidelity

DocLang assessment SHALL include textual nodes and profile-declared semantic attributes through a reversible source map.
Validated structural attributes SHALL remain intact. Unknown attribute roles, unsupported representations, or malformed
structures SHALL fail explicitly rather than claiming complete coverage or masking structural references as prose.

#### Scenario: Entity split across DocLang nodes

- **WHEN** a sensitive name spans adjacent inline text nodes
- **THEN** contextual assessment can identify the complete name and masking changes its mapped text fragments without
  tags

#### Scenario: Sensitive value in a declared attribute

- **WHEN** an assessed DocLang attribute contains a detected email
- **THEN** the email is masked in that attribute and the serialized document remains well formed

#### Scenario: Structural and unknown attributes

- **WHEN** a DocLang document contains validated layout/reference attributes plus an attribute absent from its format
  profile
- **THEN** structural attributes remain intact and the unknown attribute causes explicit unsupported coverage

### Requirement: Unicode coordinate integrity

PII spans SHALL use documented half-open Unicode code-point coordinates in the exact assessed view. Providers with other
offset units SHALL convert them explicitly. Any normalized comparison view SHALL preserve a mapping to the original.
Masking SHALL cover complete affected grapheme clusters and SHALL NOT silently transliterate or translate source text.

#### Scenario: Accented name in decomposed text

- **WHEN** a detected name uses combining marks and an equivalent composed spelling is used for comparison
- **THEN** the accepted evidence maps to the original spelling and masking leaves no sensitive combining-mark fragments

#### Scenario: Supplementary character before an entity

- **WHEN** a supplementary Unicode character precedes a detection from a provider using UTF-16 offsets
- **THEN** conversion selects the correct original substring or the candidate is rejected as ungrounded

### Requirement: Strict PII completion handling

LLM PII assessment SHALL retain completion, refusal, and truncation information and accept only a complete response
under
the declared response contract. Missing termination evidence, token exhaustion, refusals, blank output, or invalid
envelopes SHALL cause explicit assessment failure. Bounded retries SHALL NOT turn exhaustion into an empty result.

#### Scenario: Unrelated valid JSON

- **WHEN** a provider returns `{}` or an error object without the required detections envelope
- **THEN** the response is rejected as `INVALID_RESPONSE` rather than interpreted as no PII

#### Scenario: Valid JSON with length termination

- **WHEN** a response is syntactically valid but provider metadata reports output-token exhaustion
- **THEN** the assessment is incomplete and cannot yield successful zero counts

#### Scenario: Unrelated inference consumers

- **WHEN** an existing non-PII caller uses the string-returning inference interface
- **THEN** the additive PII completion contract does not change that interface's return type

### Requirement: Strict PII response schema

PII responses SHALL validate required fields, field types, requested capability, canonical labels, and finite in-range
scores where scores are supplied. Booleans SHALL NOT be accepted as offsets. Missing fields SHALL NOT acquire fabricated
zero offsets or confidence. Parsing SHALL NOT extract a convenient object from surrounding prose or repair evidence
text.

#### Scenario: Fabricated defaults

- **WHEN** a response supplies a name and text but omits its required evidence locator
- **THEN** it is rejected rather than converted to a detection at `0:0`

#### Scenario: Unsafe scalar or envelope

- **WHEN** a response contains string offsets, a boolean offset, NaN, unknown labels, duplicate JSON keys, or trailing
  prose
- **THEN** strict validation rejects it with a sanitized reason

### Requirement: Grounded PII evidence

Every accepted PII occurrence SHALL be tied to exact source evidence and a unique source location. Supplied offsets
SHALL
satisfy source bounds and substring equality. Quoted evidence without offsets SHALL be resolved using explicit
occurrence
or context anchors. Ambiguous matches, invented quotations, and invalid ranges SHALL require review or failure.

#### Scenario: Repeated name with one locator

- **WHEN** a quotation matches two source occurrences and its anchors do not identify which occurrence was intended
- **THEN** the operator does not guess the first match or globally replace every matching string

#### Scenario: Quote disagrees with offset

- **WHEN** the model reports text `FAKE` at a source span containing `John`
- **THEN** that evidence cannot be counted or used for redaction

### Requirement: Instruction and document separation

The LLM PII path SHALL separate trusted task instructions from untrusted document content, request only configured PII
types, and use a declared structured response contract. Embedded instructions SHALL be treated as document data.
Schema compliance SHALL NOT be represented as proof of semantic accuracy or prompt-injection immunity.

#### Scenario: Document contains an instruction to suppress findings

- **WHEN** a document includes instructions to return an empty detections array
- **THEN** the extraction task still requires assessment of the entire document and this case is included in
  qualification

### Requirement: Provider-specific PII score policy

Configured score thresholds SHALL be applied deterministically to provider scores, not delegated to prompt wording.
Score provenance and calibration status SHALL remain distinguishable. LLM self-reported confidence SHALL NOT be
presented
as a calibrated probability or averaged with unrelated detector scores. A below-threshold candidate SHALL NOT be
accepted.

#### Scenario: Low score returned despite high requested threshold

- **WHEN** a provider returns score `0.01` with configured threshold `0.99`
- **THEN** the candidate is not accepted and its policy disposition is recorded without falsely asserting no PII

### Requirement: Hybrid PII provider selection

The operator SHALL accept `hybrid` as a PII-only provider with explicitly configured local and LLM components.
Each required component SHALL assess the declared coverage independently. A missing dependency or component
configuration
SHALL fail before document inference; a component runtime failure SHALL NOT silently degrade to single-provider success.

#### Scenario: Local detector misses an entity

- **WHEN** the local detector returns no candidates but the LLM returns grounded evidence
- **THEN** reconciliation still evaluates the LLM evidence rather than restricting extraction to local candidates

#### Scenario: Required LLM component unavailable

- **WHEN** hybrid assessment's LLM component fails after its retry budget
- **THEN** the row is incomplete even if the local detector returned valid candidates

### Requirement: Provenance-aware PII reconciliation

Reconciliation SHALL retain candidate provenance, deduplicate the same type and occurrence across windows/providers, and
apply a versioned decision policy. Conflicting or insufficient evidence SHALL produce an explicit review disposition.
A failed format or checksum test, detector silence, or an LLM rejection alone SHALL NOT establish non-sensitivity.

#### Scenario: Detector disagreement on an identifier

- **WHEN** contextual evidence identifies an account number that fails a known format check
- **THEN** the occurrence is evaluated as uncertain or sensitive and is not silently discarded as safe

#### Scenario: Two types overlap

- **WHEN** two accepted types overlap at the same source location
- **THEN** each distinct type-occurrence is counted once and masking covers their interval union

### Requirement: English-first PII coverage profiles

Coverage profiles SHALL name language, entity types, jurisdiction scope, detector versions, and qualification evidence.
The initial qualified language SHALL be English; Latin-script Unicode support SHALL NOT imply qualification for all
Latin-script languages. Known language/profile mismatches and unsupported requested coverage SHALL prevent successful
assessment. Missing jurisdiction SHALL be recorded as unspecified, not inferred from English.

#### Scenario: English document with international identifiers

- **WHEN** an English assessment has no configured jurisdiction
- **THEN** the operator does not assume US-only identifiers and preserves unknown jurisdiction in the evidence

#### Scenario: Unsupported language profile

- **WHEN** a flow requests an unqualified French profile or supplied language metadata conflicts with the English
  profile
- **THEN** validation or assessment reports `UNSUPPORTED_COVERAGE` instead of claiming English qualification applies

### Requirement: Declared coverage and benchmark qualification remain distinct

Assessment metadata SHALL expose language value/basis separately from qualification status and report fingerprint.
An omitted language hint SHALL be recorded as declared English, not measured language detection. `assessed` SHALL mean
execution completed under that declaration; it SHALL NOT imply detected-English input, OCR completeness, or measured
model
accuracy. Only a matching passing report SHALL permit `qualified` benchmark status.

#### Scenario: Unverified custom English endpoint

- **WHEN** an English-declared assessment completes without an exact matching benchmark report
- **THEN** execution status is `assessed`, language basis is `declared`, and qualification status is `unverified`

### Requirement: Input extraction evidence limits

The operator SHALL respect supplied extraction-failure or incomplete-coverage evidence when validating declared text.
Absent extraction evidence SHALL be recorded as unknown in assessment provenance and SHALL NOT be described as verified
source-file completeness. Valid text or a successful PII response alone SHALL NOT attest OCR or page completeness.

#### Scenario: Extraction reports a missing page

- **WHEN** supplied extraction evidence marks the assessed representation incomplete
- **THEN** the row is withheld as `INCOMPLETE_SOURCE` before release of a redacted result

### Requirement: Atomic PII redaction

Redaction SHALL operate only on validated source locations after all required assessments complete. It SHALL mask
accepted
interval unions deterministically in each declared column and preserve other source text and supported structure.
`redaction=false` SHALL preserve input text. Empty or unsafe masking configuration SHALL fail validation.

#### Scenario: Custom column alongside default content

- **WHEN** `source_text` and `content` are both declared, with distinct source values and accepted evidence
- **THEN** masking updates each from its own source map and never copies `source_text` values into `content`

#### Scenario: One segment fails after earlier detections

- **WHEN** any required assessment segment fails
- **THEN** no partially redacted version of that row is emitted

### Requirement: PII output table and assessment metadata

Successful PII output SHALL retain existing selected count columns as int64 and add string `pii_assessment_status` with
value `assessed`. Counts SHALL cover distinct accepted type-occurrences across declared columns. Transform metadata
SHALL
retain existing lifecycle keys and include versioned PII assessment totals, failure/review reason counts, and coverage
provenance without raw PII. Status `assessed` SHALL NOT mean guaranteed absence of PII.

#### Scenario: Successful zero-finding assessment

- **WHEN** all required coverage completes with a valid empty result and no unresolved candidates
- **THEN** selected PII counts are zero and status is `assessed`, distinguishable from missing assessment

#### Scenario: Empty input table

- **WHEN** a valid typed input table has zero rows
- **THEN** output has zero rows with stable declared count/status types and zero assessment totals without inference

### Requirement: Unresolved PII rows do not enter successful output

Failed, unsupported, incomplete, and review-required assessments SHALL be withheld and recorded using sanitized reason
codes. With `partial_ingest=true`, removal SHALL apply to affected rows; with `false`, it SHALL apply to every row
sharing
an affected document ID. All annotation columns and metrics SHALL be assembled from the same retained row selection.
An entirely withheld non-empty input SHALL report failed node status.

#### Scenario: Shared ID with one failed row

- **WHEN** rows have IDs `dup`, `dup`, `ok`, the first fails, and `partial_ingest` is false
- **THEN** only `ok` is emitted with exactly one corresponding annotation value and no Arrow length mismatch

#### Scenario: Some rows need review

- **WHEN** one document requires review and another completes successfully
- **THEN** only the completed document is emitted and node metadata reports completed-with-errors and the withheld
  reason

### Requirement: PII content confidentiality

PII assessment SHALL NOT log document text, quotations, raw provider responses, credentials, or provider exception text
that can echo content. Redaction SHALL reject `display_pii=true`. Annotation-only debug display SHALL require explicit
opt-in and SHALL be documented as containing sensitive data. Default reports SHALL use opaque assessment references.

#### Scenario: Parser failure at debug level

- **WHEN** a provider returns malformed JSON containing a sensitive quotation
- **THEN** logs and failure details contain only sanitized diagnostic codes and non-content operational metadata

### Requirement: Existing provider and HAP compatibility

Existing provider names, selection precedence, configured PII labels, and native HAP threshold semantics SHALL remain.
Known legacy PII label aliases SHALL map explicitly, not by arbitrary substring matches. Shared window/redaction repairs
SHALL preserve HAP source positions. HAP-only runs SHALL NOT gain PII status columns or require a PII coverage profile.

#### Scenario: HAP-only native provider

- **WHEN** a flow requests only HAP through a native HAP provider
- **THEN** its selected provider, output columns, and scoring semantics remain unchanged

#### Scenario: Legacy namespace label

- **WHEN** an adapter reports the documented `NationalNumber.SocialSecurityNumber.US` alias
- **THEN** it maps to `SocialSecurityNumber`, while an unknown label merely containing that substring is rejected

### Requirement: Mixed PII and HAP row outcomes

When PII and HAP are requested together, each capability SHALL use its own assessment contract and coverage policy, even
when provider names match. Both results SHALL bind to the same row source. A PII failure/review outcome SHALL withhold
the
row and its HAP output. When both masks are enabled, PII masking SHALL take precedence in shared intervals while counts
retain each accepted capability occurrence. Native HAP scoring semantics SHALL remain unchanged.

#### Scenario: PII fails while HAP succeeds

- **WHEN** PII assessment is incomplete and HAP assessment completes for the same row
- **THEN** the row and its HAP annotations are withheld according to the document-group policy and the issue is reported

#### Scenario: Overlapping masks with distinct characters

- **WHEN** PII and HAP masks are enabled with different characters and accepted spans overlap
- **THEN** the shared interval uses the PII character, HAP-only intervals use the HAP character, and each count is
  preserved
