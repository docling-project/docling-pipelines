# backend/ingest-source-operator Specification

## Purpose
The ingest-source-operator capability discovers, filters, and ingests documents from local filesystem, web, and cloud storage providers into a canonical PyArrow table (`id`, `name`, `document_format`, `metadata`, `source_id`, `path`, `modified_time`) with execution metadata (`total_docs_count`, `processed_docs_count`, `skipped_docs_count`, `skipped_docs`, `failed_docs_count`, `failed_docs`, `node_status`).

## ADDED Requirements

### Requirement: Immutable supported file extension discovery across Tier 1 and Tier 4 formats
The supported file extension discovery helper SHALL return a comma-separated list of all Tier 1 base extensions plus Tier 4 audio/video extensions (including `mkv` and `webm`) when ASR is available, without mutating the underlying `BASE_EXTENSIONS` constant list across repeated invocations.

#### Scenario: Supported extensions list includes Tier 1 formats without ASR
- **WHEN** `get_supported_file_extensions()` is called when ASR dependencies are unavailable
- **THEN** the returned comma-separated string includes Tier 1 extensions (`csv`, `epub`, `eml`, `msg`, `tex`, `latex`, `adoc`, `asciidoc`, `asc`, `vtt`, `htm`, `xhtml`, `mhtml`, `mht`, `markdown`, `text`, `qmd`, `rmd`, `dotx`, `docm`, `dotm`, `potx`, `ppsx`, `pptm`, `potm`, `ppsm`, `xlsm`, `xltx`, `xltm`) and excludes audio/video extensions

#### Scenario: Repeated calls with ASR available do not mutate BASE_EXTENSIONS
- **WHEN** `get_supported_file_extensions()` is called with ASR available followed by a call with ASR unavailable
- **THEN** `OperatorConstants.FileExtensions.BASE_EXTENSIONS` remains unmutated and the second call does not contain any audio or video extensions

### Requirement: Default include filter covers all supported extensions
When `include_filter` is not configured, `IngestSourceOperator` SHALL ingest every file whose extension is in the supported extension list, including all Tier 1 formats and, when ASR is available, Tier 4 audio/video formats. An explicit `include_filter` SHALL restrict ingestion to the listed extensions only.

#### Scenario: Tier 1 file is ingested when no include_filter is set
- **WHEN** a filesystem path contains `data.csv` and `report.pdf` and `IngestSourceOperator` runs without `include_filter`
- **THEN** both files are emitted into the output `pa.Table` with `document_format` set to `.csv` and `.pdf`

#### Scenario: Explicit include_filter restricts ingestion
- **WHEN** a filesystem path contains `data.csv` and `report.pdf` and `IngestSourceOperator` runs with `include_filter="pdf"`
- **THEN** only `report.pdf` is emitted and `data.csv` is recorded in `metadata["skipped_docs"]`

### Requirement: Include and exclude filter validation for Tier 1 and Tier 4 extensions
`IngestSourceOperator` SHALL accept any Tier 1 extension (and any Tier 4 audio/video extension when ASR is available) in `include_filter` and `exclude_filter`, emitting matching documents into the output `pa.Table` and recording filtered-out files in `skipped_docs` transform metadata.

#### Scenario: Ingest source accepts Tier 1 extensions in include_filter
- **WHEN** `IngestSourceOperator` is initialized with `include_filter="csv,epub,eml,tex,adoc,vtt"`
- **THEN** initialization succeeds without raising a `ValueError` and only documents matching those extensions are emitted into the output `pa.Table`

#### Scenario: Excluded Tier 1 or Tier 4 extension is recorded in skipped_docs metadata
- **WHEN** `IngestSourceOperator` runs with `exclude_filter="csv,eml"` and encounters `data.csv`
- **THEN** `data.csv` is omitted from the output `pa.Table` and recorded in `metadata["skipped_docs"]` with reason `"File extension in exclusion list"`

#### Scenario: Unsupported extension in include_filter is rejected
- **WHEN** `IngestSourceOperator` is initialized with `include_filter="xyz"`
- **THEN** initialization raises `ValueError` listing the unsupported extension

### Requirement: Web source MIME-to-extension resolution for text-based new formats
The web ingest adapter SHALL map `text/csv` to `.csv` and `message/rfc822` to `.eml` when resolving the document extension from the HTTP `Content-Type` header, and SHALL continue to fall back to `.html` for unrecognised content types. Binary container formats such as `.epub` are not resolved by the web adapter because it ingests decoded page text.

#### Scenario: Web adapter resolves Content-Type header for CSV
- **WHEN** the web ingest adapter fetches a URL returning `Content-Type: text/csv`
- **THEN** the ingested document's `extension` is `.csv` and `metadata["content_type"]` is `text/csv`

#### Scenario: Web adapter resolves Content-Type header for email
- **WHEN** the web ingest adapter fetches a URL returning `Content-Type: message/rfc822; charset=utf-8`
- **THEN** the ingested document's `extension` is `.eml`

#### Scenario: Unrecognised Content-Type falls back to HTML
- **WHEN** the web ingest adapter fetches a URL returning `Content-Type: application/epub+zip`
- **THEN** the ingested document's `extension` is `.html`
