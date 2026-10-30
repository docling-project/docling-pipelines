# Spec Delta

## Purpose

The PII and HAP operator (`pii_and_hap`) detects personally identifiable information and hate, abuse and profanity (HAP) in document content through independently selectable detection providers, records per-document detection counts, and can mask detected spans. This capability defines the observable behavior of those providers, starting with the local `huggingface` HAP provider.

## ADDED Requirements

### Requirement: HAP-only huggingface provider selection
The operator SHALL accept `huggingface` as `hap_provider`. It SHALL reject `huggingface` as `pii_provider`, and as the legacy `provider` when PII is in `expected_redactions`, with an error that says the provider does not support PII detection and lists the providers that do. This error SHALL be reported by flow validation and SHALL stop execution before any document is processed.

#### Scenario: Local PII and HAP pipeline
- **WHEN** a flow configures `pii_and_hap` with `pii_provider: "presidio"`, `hap_provider: "huggingface"` and `expected_redactions: ["pii", "hap"]`
- **THEN** flow validation succeeds and PII is detected by `presidio` and HAP by `huggingface`

#### Scenario: Selected as PII provider
- **WHEN** a flow sets `pii_provider: "huggingface"` with PII in `expected_redactions`
- **THEN** flow validation fails with an error naming `huggingface`, stating that it does not support PII detection, and listing the PII-capable providers

#### Scenario: Legacy provider key with HAP only
- **WHEN** a flow sets `provider: "huggingface"` and `expected_redactions: ["hap"]`
- **THEN** HAP detection uses `huggingface` and no PII provider is required

### Requirement: Default HAP model
When `hap_provider_config` is absent or empty, the `huggingface` provider SHALL use the `ibm-granite/granite-guardian-hap-38m` model, treat the `LABEL_1` class as toxic, and score with softmax. No `model_id` or other provider setting SHALL be required.

#### Scenario: No provider config
- **WHEN** a flow sets `hap_provider: "huggingface"` without `hap_provider_config`
- **THEN** flow validation succeeds and HAP detection runs with `ibm-granite/granite-guardian-hap-38m`

### Requirement: Configurable classifier
The `huggingface` provider SHALL read these optional `hap_provider_config` keys: `model_id`, `revision`, `toxic_labels`, `activation` (`softmax`, `sigmoid` or `auto`), `max_length`, `batch_size`, `device` and `local_files_only`. Any Hugging Face sequence-classification model that has a fast tokenizer and needs no custom code SHALL work through these keys alone. Unknown keys SHALL be ignored.

#### Scenario: Multi-label model through config
- **WHEN** `hap_provider_config` is `{"model_id": "unitary/unbiased-toxic-roberta", "toxic_labels": ["toxicity", "severe_toxicity", "insult"], "activation": "sigmoid"}`
- **THEN** that model scores each span and the span score is the highest sigmoid probability among the three labels

#### Scenario: Auto activation
- **WHEN** `activation` is `auto` or omitted for a non-default model
- **THEN** sigmoid is used if the model declares multi-label classification and softmax is used otherwise

#### Scenario: Pinned revision
- **WHEN** `revision` names a model commit, tag or branch
- **THEN** the model and tokenizer are loaded at that revision

### Requirement: Explicit toxic labels for non-default models
When `model_id` names a model other than the default, `toxic_labels` SHALL be a non-empty list of that model's class label names. Omitting it SHALL be a configuration error, because generic labels such as `LABEL_1` do not mean "toxic" for every model.

#### Scenario: Missing toxic labels
- **WHEN** `hap_provider_config` sets `model_id` to a non-default model and omits `toxic_labels`
- **THEN** flow validation fails with an error stating that `toxic_labels` is required for that model

#### Scenario: Unknown toxic label
- **WHEN** `toxic_labels` contains a name that is not one of the loaded model's class labels
- **THEN** the operator fails at startup with an error listing the unknown names and the model's available labels

### Requirement: Sentence-span detections with original-text offsets
The provider SHALL split the text it receives into spans at line breaks and sentence boundaries, excluding surrounding whitespace, and score each span separately. Each reported `start`/`end` SHALL be character offsets into that text such that `text[start:end]` is the scored span. A span longer than `max_length` model tokens SHALL be scored as consecutive windows, each reported as its own span.

#### Scenario: One toxic sentence among clean ones
- **WHEN** the text is "Thanks for the report.\nYou are a worthless idiot. See you tomorrow." and only the second sentence scores at or above `hap_threshold`
- **THEN** exactly one detection is returned and its `start`/`end` cover "You are a worthless idiot." in the received text

#### Scenario: Redaction masks only the flagged span
- **WHEN** `hap_redaction` is `true` and a document is processed as a single chunk with one flagged sentence
- **THEN** the characters of that sentence are replaced with `hap_redaction_character` and all other characters, including line breaks, are unchanged

#### Scenario: Whitespace-only text
- **WHEN** the text contains no non-whitespace characters
- **THEN** no span is scored and no detection is returned

#### Scenario: Overlong sentence
- **WHEN** a single sentence exceeds `max_length` tokens and only its last part is toxic
- **THEN** the window that contains the toxic part is reported and its offsets lie inside that sentence

### Requirement: HAP score and threshold
A span's score SHALL be the highest probability among the configured `toxic_labels`, between 0.0 and 1.0. A span SHALL be reported only when its score is greater than or equal to `hap_threshold`. Scores SHALL be deterministic for a given model, revision, device and text.

#### Scenario: Threshold boundary
- **WHEN** `hap_threshold` is 0.8 and two spans score 0.8 and 0.79
- **THEN** the span scoring 0.8 is reported and the span scoring 0.79 is not

### Requirement: HAP detection record
Each reported span SHALL be a detection with `detection` `has_HAP`, `detection_type` `hap`, the span `score`, `start`, `end` and `text` equal to the span, and evidence naming the source `huggingface`, the model and the highest-scoring toxic label.

#### Scenario: Detection fields
- **WHEN** a span is reported
- **THEN** its detection has `detection: "has_HAP"`, `detection_type: "hap"`, a score at or above `hap_threshold`, offsets of the span, and evidence with the model id and label

### Requirement: Output table and metadata contract unchanged
Selecting `huggingface` SHALL NOT change the operator's pyarrow output schema or metadata keys. With HAP in `expected_redactions`, the output table SHALL keep every input column and add the integer `hap` column holding each document's count of HAP detections. The content column changes only when `hap_redaction` is `true`. Transform metadata SHALL count HAP detections under the existing `HAP` key.

#### Scenario: HAP count column
- **WHEN** a batch of three documents yields 2, 0 and 1 HAP detections
- **THEN** the output table has the input columns plus a `hap` column with values 2, 0 and 1, and the metadata `HAP` count is 3

#### Scenario: Detection without redaction
- **WHEN** `hap_redaction` is `false` and HAP is detected
- **THEN** the content column is identical to the input

### Requirement: Fail fast on misconfiguration
Invalid option values (wrong types, `batch_size` or `max_length` not a positive integer, unknown `activation`) SHALL be reported by flow validation without loading a model. At operator startup the provider SHALL load the model and tokenizer and check `toxic_labels`. Any failure SHALL stop execution with an error naming the model, before any document is processed.

#### Scenario: Invalid option value
- **WHEN** `hap_provider_config.batch_size` is 0 or `activation` is `"relu"`
- **THEN** flow validation fails with an error naming the key and the accepted values

#### Scenario: Model cannot be loaded
- **WHEN** `model_id` does not exist or cannot be downloaded
- **THEN** the operator fails at startup with an error naming the model id and no document is processed

### Requirement: No remote code execution
The provider SHALL NOT execute code shipped with a model repository. A model that requires custom code SHALL be rejected at startup with an error naming the model.

#### Scenario: Model requiring custom code
- **WHEN** `model_id` names a model that can only be loaded with custom repository code
- **THEN** the operator fails at startup and no code from that repository runs

### Requirement: Offline operation
Importing the operator or provider SHALL NOT access the network. With `local_files_only: true`, or the Hugging Face offline environment setting, the provider SHALL load weights only from the local cache. If they are missing, startup SHALL fail with an error naming the model and stating that offline mode is on.

#### Scenario: Cached weights offline
- **WHEN** the model weights are in the local cache, `local_files_only` is `true` and there is no network access
- **THEN** startup succeeds and documents are scored without any network request

#### Scenario: Missing weights offline
- **WHEN** `local_files_only` is `true` and the weights are not cached
- **THEN** the operator fails at startup with an error naming the model and stating that offline mode is enabled

### Requirement: No document content in logs or errors
The provider SHALL NOT write document text, span text or token values to logs at any level, nor include them in error messages. Logs MAY contain the model id, revision, device, counts and timings.

#### Scenario: Debug logging enabled
- **WHEN** `DS_LOG_LEVEL` is `DEBUG` and documents containing HAP are processed
- **THEN** no log record contains any document or span text

### Requirement: Per-process model sharing
Within one process the provider SHALL load each `(model_id, revision, device)` at most once and share it across operator instances, batches and threads. Concurrent detection on a shared model SHALL return the same results as sequential detection.

#### Scenario: Concurrent micro-batches
- **WHEN** a flow with micro-batching runs several `pii_and_hap` batches concurrently with the same `huggingface` config
- **THEN** the model is loaded once in that process and every batch returns the same detections it would return if run alone

#### Scenario: Different revisions
- **WHEN** two nodes in one process use the same `model_id` with different `revision` values
- **THEN** each revision is loaded once and used only by its own node

### Requirement: Scoring failure is a per-document failure
If scoring fails for a document at run time, the provider SHALL NOT crash the operator. That document SHALL be recorded as failed in the transform metadata, with a reason that names the provider and contains no document text, and the node status SHALL become completed-with-errors. Whether the other rows are kept follows the existing `partial_ingest` behavior.

#### Scenario: Runtime inference error with partial ingest
- **WHEN** `partial_ingest` is `true` and the model raises an error while scoring one document in a batch of three
- **THEN** that document is recorded as failed and removed, and the other two are returned with their detections

#### Scenario: Runtime inference error without partial ingest
- **WHEN** `partial_ingest` is `false` and scoring fails for one document in a batch
- **THEN** that document is recorded as failed and the batch rows are removed, as for any other provider failure
