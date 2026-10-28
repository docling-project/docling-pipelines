# Spec Delta

## Purpose

Defines how the `extract_operator` handles password-protected documents: the `document_passwords` configuration contract, in-memory decryption before extraction, the failure reasons and their incremental-run classification, secret handling, and the operator's table and metadata contract for these documents.

## ADDED Requirements

### Requirement: Document Passwords Configuration

The `extract_operator` SHALL accept an optional top-level `document_passwords` object with an optional ordered `rules` list and an optional `default` list. Each rule SHALL have a non-empty string `match` and a non-empty `passwords` list. Every password SHALL be a non-empty string. Unknown keys SHALL be rejected. When `document_passwords` is omitted, no passwords are configured.

#### Scenario: Valid configuration accepted
- **WHEN** a flow configures `extract_operator` with `document_passwords: {"rules": [{"match": "*.pdf", "passwords": ["vault://org/pdf-key"]}], "default": ["vault://org/shared-key"]}`
- **THEN** flow validation SHALL report no error for `document_passwords`

#### Scenario: Malformed configuration rejected
- **WHEN** `document_passwords` contains an unknown key, a rule without `match`, a rule with an empty `passwords` list, or a password that is not a non-empty string
- **THEN** flow validation SHALL report an error naming the offending location within `document_passwords`

#### Scenario: Validation errors do not echo passwords
- **WHEN** flow validation reports an error for a malformed `document_passwords` object
- **THEN** the error message SHALL NOT contain any password value from the configuration

### Requirement: Password Candidate Resolution

For each encrypted document the operator SHALL use the `passwords` of the first rule, in list order, whose `match` pattern matches the document's `name` or its `path`. If no rule matches, it SHALL use `default`. Patterns SHALL match the whole string, be case-sensitive, and support `*` (any characters, including `/`), `?` and `[...]`.

#### Scenario: First matching rule wins
- **WHEN** two rules both match a document and the first rule's `passwords` are `["a"]` and the second's are `["b"]`
- **THEN** the operator SHALL try only `"a"` for that document

#### Scenario: Rule matches on path
- **WHEN** a document has `name` `"report.pdf"` and `path` `"s3://finance/q1/report.pdf"`, and a rule has `match` `"*/finance/*"`
- **THEN** that rule SHALL apply to the document

#### Scenario: Rule matches on name
- **WHEN** a document has `name` `"budget_2024.xlsx"` and a rule has `match` `"budget_*.xlsx"`
- **THEN** that rule SHALL apply to the document regardless of its `path`

#### Scenario: Same file name in different folders
- **WHEN** two documents are both named `"report.pdf"` with paths `"/data/hr/report.pdf"` and `"/data/finance/report.pdf"`, and rules match `"*/hr/*"` and `"*/finance/*"` with different passwords
- **THEN** each document SHALL be decrypted with the passwords of its own rule

#### Scenario: Default used when no rule matches
- **WHEN** no rule matches an encrypted document and `default` is `["shared"]`
- **THEN** the operator SHALL try `"shared"` for that document

### Requirement: Encrypted Document Detection

The operator SHALL detect, after fetching document bytes and before extraction, whether a PDF or an OOXML document (`.docx`, `.pptx`, `.xlsx`) requires a password to open. Detection SHALL run whether or not `document_passwords` is configured. A PDF that opens without a password (for example one protected only by an owner password) SHALL NOT be treated as encrypted.

#### Scenario: Encrypted PDF detected without configuration
- **WHEN** `document_passwords` is omitted and a document is a PDF that requires a user password
- **THEN** the operator SHALL treat the document as encrypted and SHALL NOT pass it to the text extraction provider

#### Scenario: Owner-password-only PDF not treated as encrypted
- **WHEN** a PDF has an owner password but no user password
- **THEN** the operator SHALL pass the original bytes to the text extraction provider unchanged

### Requirement: In-Memory Decryption

For an encrypted document the operator SHALL try the resolved candidate passwords in order and use the first that opens it. The decrypted bytes SHALL be what the text extraction provider, and any entity extraction adapter that reads document bytes, receive for that document. Decrypted bytes SHALL be kept only in memory for the duration of the run.

#### Scenario: Encrypted PDF extracted with a configured password
- **WHEN** a PDF requires the password `"s3cret"` and its resolved candidates are `["wrong", "s3cret"]`
- **THEN** the operator SHALL extract the document's content as it would for an unencrypted copy, and SHALL count it as processed

#### Scenario: Encrypted Office document extracted with a configured password
- **WHEN** an encrypted `.docx`, `.pptx` or `.xlsx` document's resolved candidates include its password, and Office decryption is available
- **THEN** the operator SHALL extract the document's content as it would for an unencrypted copy

#### Scenario: Decryption applies to every text extraction provider
- **WHEN** the `extract_operator` uses `text_extraction.provider` `"docling_library"` or `"docling_serve"` on an encrypted document whose password is configured
- **THEN** the provider SHALL receive the decrypted document bytes

#### Scenario: Decryption applies when entity extraction runs
- **WHEN** entity extraction is enabled and the entity extraction adapter reads document bytes rather than extracted text
- **THEN** the adapter SHALL receive the decrypted document bytes for an encrypted document whose password is configured

#### Scenario: Nothing decrypted is written to disk
- **WHEN** the operator decrypts a document
- **THEN** the operator SHALL NOT write the decrypted bytes to any file

### Requirement: Unencrypted And Unsupported Documents Pass Through

The operator SHALL pass the original bytes, unchanged, to extraction for every document that is not an encrypted PDF or OOXML document, whether or not a `document_passwords` rule matches it.

#### Scenario: Unencrypted document matched by a rule
- **WHEN** an unencrypted PDF matches a rule in `document_passwords`
- **THEN** the operator SHALL pass the original bytes to the text extraction provider unchanged

#### Scenario: Unsupported format matched by a rule
- **WHEN** an image, audio, HTML or other non-PDF, non-OOXML document matches a rule in `document_passwords`
- **THEN** the operator SHALL pass the original bytes to extraction unchanged

### Requirement: Password Failure Reasons

When an encrypted document cannot be decrypted, the operator SHALL record it as a failed document whose failure reason begins with one of: `password_required` (no candidate passwords resolved), `password_incorrect` (every candidate was rejected) or `decryption_unavailable` (the Office decryption library is not installed, or cannot decrypt the document's encryption scheme). The document SHALL NOT be passed to extraction.

#### Scenario: No password configured
- **WHEN** a document is encrypted and no rule or `default` provides candidates for it
- **THEN** the document SHALL be recorded as failed with a reason beginning with `password_required`

#### Scenario: Every candidate rejected
- **WHEN** a document is encrypted and none of its resolved candidates opens it
- **THEN** the document SHALL be recorded as failed with a reason beginning with `password_incorrect`

#### Scenario: Office decryption library missing
- **WHEN** an OOXML document is encrypted and the Office decryption library is not installed
- **THEN** the document SHALL be recorded as failed with a reason beginning with `decryption_unavailable`, and other documents in the run SHALL be processed normally

### Requirement: Password Failures Are Recoverable

Documents that fail with `password_required`, `password_incorrect` or `decryption_unavailable` SHALL NOT be included in the operator's non-recoverable documents table, so the next incremental run processes them again. All other failure classification SHALL be unchanged.

#### Scenario: Password added after a failed run
- **WHEN** an incremental run fails a document with `password_required`, and a later run of the same flow, with the document unchanged and `force_ingest` not set, configures a working password for it
- **THEN** the later run SHALL extract the document

#### Scenario: Corrected password after a failed run
- **WHEN** an incremental run fails a document with `password_incorrect`, and a later run of the same flow, with the document unchanged, configures the correct password
- **THEN** the later run SHALL extract the document

#### Scenario: Other non-recoverable failures unchanged
- **WHEN** a document that is not encrypted fails extraction with an error that was classified as non-recoverable before this change
- **THEN** the document SHALL still be included in the non-recoverable documents table

### Requirement: Password Secrecy

Password values and decrypted bytes SHALL NOT appear in the output `pyarrow.Table`, row metadata, operator metrics, failed-document reasons, job stats or log messages.

#### Scenario: Passwords absent from outputs
- **WHEN** the operator runs with `document_passwords` configured and decrypts, or fails to decrypt, one or more documents
- **THEN** no configured password value SHALL appear in the output table, the returned metadata, the failed-document reasons or the operator's log output

### Requirement: Sensitive Attribute Metadata

The `extract_operator` metadata SHALL describe `document_passwords` as an optional attribute marked sensitive, so that clients treat its values as secrets.

#### Scenario: Attribute exposed as sensitive
- **WHEN** a client requests operator metadata for `extract_operator`
- **THEN** the `document_passwords` attribute SHALL be present, not required, and marked sensitive

### Requirement: Plain-Text Password Warning

Flow validation SHALL warn, without echoing the value, for each password in `document_passwords` that is a plain string rather than a `vault://` reference.

#### Scenario: Plain-text password warned
- **WHEN** a flow configures a password as a plain string in `document_passwords`
- **THEN** flow validation SHALL return a warning that identifies its location and recommends a `vault://` reference, without the password value

#### Scenario: Vault reference not warned
- **WHEN** every password in `document_passwords` is a `vault://` reference
- **THEN** flow validation SHALL NOT return a plain-text password warning

### Requirement: Output Table Contract For Encrypted Documents

The operator SHALL NOT add columns for decryption. A decrypted document SHALL produce the same output columns as any extracted document. A document that fails with a password failure reason SHALL be removed from the output table and counted in the failed documents count, like any other failed extraction.

#### Scenario: Mixed batch
- **WHEN** a run contains one unencrypted document, one encrypted document with a working password and one encrypted document with no password configured
- **THEN** the output table SHALL contain two rows with the usual extraction columns, the processed count SHALL be 2, and the failed count SHALL be 1

### Requirement: Office Decryption Packaging

The `docling-pipelines` package SHALL install the Office decryption library by default. The `docling-pipelines-slim` package SHALL install it only with the `extract` optional group.

#### Scenario: Full package
- **WHEN** `docling-pipelines` is installed without optional groups
- **THEN** encrypted OOXML documents with a configured password SHALL be decrypted

#### Scenario: Slim package with extract group
- **WHEN** `docling-pipelines-slim[extract]` is installed
- **THEN** encrypted OOXML documents with a configured password SHALL be decrypted

#### Scenario: Slim package default install
- **WHEN** `docling-pipelines-slim` is installed without optional groups
- **THEN** the Office decryption library SHALL NOT be installed
