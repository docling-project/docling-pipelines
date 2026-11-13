# Proposal

## Table of contents

- [Why](#why)
- [What Changes](#what-changes)
- [Non-goals](#non-goals)
- [Capabilities](#capabilities)
- [Impact](#impact)

## Why

Tracking enhancement: [#609](https://github.com/docling-project/docling-pipelines/issues/609).
This change captures the planning artifacts; implementation remains tracked by the enhancement issue.

PII detection can accept incomplete or ungrounded LLM output as a successful assessment, and valid detections can redact
the wrong source positions. English-first accuracy needs reproducible evaluation and layered detection in addition to
correct source mapping, explicit uncertainty, and safe failure handling.

## What Changes

- Establish a shared PII assessment contract for every provider: typed input, exact source coordinates, coverage,
  canonical labels, provenance, validated detections, and explicit failure/review reasons.
- Replace PII/HAP document chunk reconstruction with bounded, overlapping source slices and verified global offsets.
  Correct the configurable source-column mutation and row/annotation alignment defects.
- Add structured completion support for the LiteLLM PII path, retaining completion/truncation/refusal metadata while
  preserving existing string-returning inference methods for unrelated callers. Separate document data from
  instructions.
- Require strict PII response parsing and source grounding; remove silent defaults and response repair from this path.
  Resolve quoted evidence to source positions in application code and handle repeated occurrences explicitly.
- Add an opt-in `hybrid` PII provider composing the existing local Presidio NER/recognizer adapter and LiteLLM
  extraction.
  Both examine complete source coverage; provenance-aware reconciliation handles conflicts and uncertainty.
- Keep `pii_threshold` deterministic and provider-specific; do not present LLM self-reported scores as calibrated
  probabilities or let a failed format/checksum test establish that an identifier is non-sensitive.
- Add an English coverage profile, separate jurisdiction configuration, and tested Latin-script Unicode handling.
  Further language profiles require their own gold corpus and release evidence.
- Add an offline evaluation/scoring workflow with human-reviewed English gold data, adversarial and pipeline fixtures,
  per-entity/jurisdiction metrics, model/prompt/configuration fingerprints, and a machine-readable release gate.
- **BREAKING**: blank, malformed, truncated, ambiguous, unsupported, or insufficiently grounded PII assessments no
  longer
  produce successful zero counts. Affected rows/document groups are withheld using the existing failure mechanism.
- **BREAKING**: PII redaction rejects unsafe content-copy configurations and production PII display output; successful
  PII output gains an assessment-status column. Existing provider selection keys, count columns, and HAP-only schemas
  remain.
- **BREAKING**: mixed PII/HAP runs use separate capability assessments; PII masking takes precedence on overlapping
  accepted spans, and an unresolved PII result withholds that row's HAP annotations as well.

## Non-goals

- Universal language support, automatic certification of an arbitrary LLM endpoint, or a claim of zero false negatives.
- Training a new foundation model, choosing a winning detector without benchmark evidence, or adding ad hoc name
  regexes.
- A human review UI, a new quarantine database, or changes to `/ui` routing, BFF proxying, or Redux state.
- Scrubbing upstream source files, historical stored artifacts, arbitrary metadata, embeddings, or images in this
  change.
  The protection boundary is the explicitly assessed textual columns; documentation must state it.
- Improving OCR itself or proving missing-page completeness when the extraction source supplies no such evidence.
- Replacing HAP classification/models or changing thresholds for native HAP providers.

## Capabilities

### New Capabilities

- `backend/pii-and-hap-operator`: source-preserving PII assessment, strict LLM evidence handling, hybrid detection,
  English coverage, deterministic redaction, output/metadata contracts, and safe failures.
  The same capability is introduced by the pending `add-huggingface-hap-provider` change; requirements here are disjoint
  additions and must be merged into that exact namespace, whichever change archives first.
- `backend/pii-detection-evaluation`: versioned gold-data validation, reproducible detector comparison, privacy-aware
  reports, slice metrics, and release-profile qualification.

### Modified Capabilities

None. Existing operator metadata and flow-validation API contracts already cover the added configuration schemas.
No engine-wide publication mechanism is introduced; unresolved documents do not leave this operator's successful output.

## Impact

- **Layer**: backend only, plus documentation, sample flows, and evaluation tooling. The existing properties panel reads
  configuration from operator metadata; no frontend implementation changes are planned.
- **Operators**: `pii_and_hap`; shared PII/HAP window mapping and row assembly also correct HAP source positions.
- **Code**: `core/operators/quality/pii_and_hap/` domain models, ports, services, adapters, annotator and helper;
  additive structured inference contracts under `core/ports/` and `core/adapters/litellm/`; LiteLLM integration client.
  The generic text splitter and forgiving JSON parser retain their behavior for unrelated consumers.
- **REST routes**: existing `GET /api/v1/operators/metadata` and `POST /api/v1/validation/validate_flow` expose new
  configuration and errors. No new routes or DTO shapes are required.
- **Storage**: no new storage adapter or schema. Failure details use existing job metadata with sanitized reason codes.
- **Dependencies**: hybrid selection requires the existing optional Presidio extra and provisioned spaCy weights.
  No additional runtime library is assumed; any necessary dependency change requires lockfile regeneration and venv
  sync.
- **Coordination**: preserve the HAP-only provider and single-chunk behavior in `add-huggingface-hap-provider`.
  Reconcile its description of `partial_ingest=false` with observed removal by document ID, rather than silently
  adopting
  the pending scenario's broader wording about removing batch rows. Do not edit that change as part of this proposal.
