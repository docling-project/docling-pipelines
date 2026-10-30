# backend/document-classifier-operator Specification

## Purpose
The document-classifier-operator capability classifies documents by fetching or reusing extracted content, validating file extensions up front, and recording unsupported documents as skipped in transform metadata.

## ADDED Requirements

### Requirement: Classification accepts Tier 1 document formats
`DocumentClassifierOperator` SHALL accept the Tier 1 formats `.csv`, `.epub`, `.tex`, `.latex`, `.adoc`, `.asciidoc`, `.asc`, `.eml`, `.msg`, `.vtt`, `.htm`, `.xhtml`, `.mhtml`, `.mht`, `.dotx`, `.docm`, `.dotm`, `.potx`, `.ppsx`, `.pptm`, `.potm`, `.ppsm`, `.xlsm`, `.xltx`, and `.xltm` in addition to its existing supported extensions. The plain-markdown variants `.markdown`, `.text`, `.qmd`, and `.rmd` SHALL remain unsupported, consistent with `.md` and `.txt`.

#### Scenario: Tier 1 document is classified rather than skipped
- **WHEN** an input `pa.Table` contains `data.csv` or `mail.eml` and the operator fetches content for classification
- **THEN** the documents are not recorded in `skipped_docs` and proceed to classification

#### Scenario: Plain-markdown variant is skipped with unsupported-extension reason
- **WHEN** an input `pa.Table` contains `notes.markdown` or `notes.qmd`
- **THEN** the document is recorded in `skipped_docs` with reason `"Unsupported file extension: .markdown"` (or `.qmd`) and is excluded from classification

#### Scenario: Unsupported extension is still skipped
- **WHEN** an input `pa.Table` contains `file.xyz`
- **THEN** the document is recorded in `skipped_docs` with reason `"Unsupported file extension: .xyz"`
