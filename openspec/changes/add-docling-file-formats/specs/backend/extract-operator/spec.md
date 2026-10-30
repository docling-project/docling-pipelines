# backend/extract-operator Specification

## Purpose
The extract-operator capability validates incoming document formats, converts supported binary documents into text and structured representations via Docling local or remote adapters, and emits PyArrow tables with extracted content columns and execution metadata.

## ADDED Requirements

### Requirement: Tier 1 pure-Python format support in docling_library extraction
The extraction operator in `docling_library` mode SHALL accept all Tier 1 pure-Python Docling formats, covering tabular (`.csv`), publishing (`.epub`, `.tex`, `.latex`, `.adoc`, `.asciidoc`, `.asc`), email (`.eml`, `.msg`), subtitles (`.vtt`), web/markup (`.htm`, `.xhtml`, `.mhtml`, `.mht`, `.markdown`, `.text`, `.qmd`, `.rmd`), and OpenXML macro/template variants (`.dotx`, `.docm`, `.dotm`, `.potx`, `.ppsx`, `.pptm`, `.potm`, `.ppsm`, `.xlsm`, `.xltx`, `.xltm`).

#### Scenario: Tier 1 document passes pre-extraction extension validation
- **WHEN** an input `pa.Table` with columns `id`, `name`, and `path` (or `document_format`) contains rows with Tier 1 extensions such as `.csv`, `.epub`, `.eml`, `.tex`, `.adoc`, `.vtt`, `.mhtml`, or `.xlsm` in `docling_library` mode
- **THEN** the operator does not mark those rows as skipped in `skipped_docs` metadata and proceeds to extract them into the configured `doc_column` (default `content`) and `pages_processed` columns

#### Scenario: Tier 1 document without native page count receives estimated pages
- **WHEN** Docling returns a document with zero native pages for a Tier 1 format such as `.csv` or `.eml`
- **THEN** `pages_processed` is estimated from the extracted character count and is at least 1

#### Scenario: Unsupported extension is skipped and recorded in transform metadata
- **WHEN** an input `pa.Table` contains a document with an unsupported extension (e.g. `.xyz`)
- **THEN** the operator removes the skipped row from the output `pa.Table`, increments `skipped_docs_count`, appends an entry with `id`, `name`, and `reason` to `skipped_docs` in the returned transform metadata dictionary, and sets `node_status` accordingly

### Requirement: docling_serve mode keeps its original supported extension set
The extraction operator in `docling_serve` mode SHALL continue to accept only the original base extensions (`.pdf`, `.docx`, `.pptx`, `.xlsx`, `.md`, `.txt`, `.html`, `.png`, `.jpeg`, `.jpg`, `.tiff`, `.tif`, `.bmp`, `.webp`, `.gif`, `.jfif`), because remote Docling Serve support for Tier 1 formats is not verified.

#### Scenario: Tier 1 document is skipped in docling_serve mode
- **WHEN** the provider is `docling_serve` and the input `pa.Table` contains `data.csv` or `mail.eml`
- **THEN** the documents are skipped during extension validation and recorded in `skipped_docs` metadata

### Requirement: Tier 4 video container support with ASR availability gating
When ASR dependencies are installed, the extraction operator in `docling_library` mode SHALL support `.mkv` and `.webm` video containers in addition to `.mp4`, `.avi`, `.mov`, `.wav`, `.mp3`, `.m4a`, `.aac`, `.ogg`, and `.flac`.

#### Scenario: MKV and WebM accepted in docling_library mode when ASR is available
- **WHEN** ASR dependencies are available and an input `pa.Table` contains `video.mkv` and `clip.webm` in `docling_library` mode
- **THEN** both documents pass extension validation and are processed rather than recorded in `skipped_docs`

#### Scenario: MKV and WebM skipped when ASR is unavailable or in docling_serve mode
- **WHEN** ASR dependencies are unavailable or the provider is `docling_serve` and the input `pa.Table` contains `video.mkv` or `clip.webm`
- **THEN** the documents are skipped during extension validation and recorded in `skipped_docs` metadata

### Requirement: Isolated temporary file routing for audio and video formats
During `docling_library` extraction, all audio and video extensions from both `InputFormat.AUDIO` and `InputFormat.VIDEO` SHALL be written to a uniquely named temporary directory (never the process working directory) before invoking conversion, using only the base name of the document, and the directory SHALL be removed after conversion completes or fails.

#### Scenario: Video binary content is written to an isolated temporary file for conversion
- **WHEN** `extract_content` processes binary content for a video file (`.mp4`, `.avi`, `.mov`, `.mkv`, or `.webm`)
- **THEN** the binary payload is materialized to a file inside a newly created temporary directory for `DocumentConverter.convert()`, and that directory is removed after conversion completes

#### Scenario: Concurrent extraction of same-named media files does not collide
- **WHEN** two workers extract media documents that share the same `name` at the same time
- **THEN** each conversion reads its own payload from a distinct temporary directory and neither payload overwrites the other

#### Scenario: Path components in document name cannot escape the temporary directory
- **WHEN** a media document's `name` contains path separators or parent-directory segments (e.g. `../../clip.mp4`)
- **THEN** only the base name is used and the file is written inside the temporary directory

#### Scenario: Temporary directory is removed when conversion fails
- **WHEN** `DocumentConverter.convert()` raises while processing a media document
- **THEN** the temporary directory is removed and the failure is reported through the normal extraction error result

### Requirement: ASR pipeline configuration for video formats
Enabling `use_asr_pipeline` on `docling_library` SHALL configure `InputFormat.VIDEO` alongside `InputFormat.AUDIO`, in both the standard converter path and the GPU converter path, applying the selected ASR model to both.

#### Scenario: ASR model configuration applies to both audio and video format options
- **WHEN** `use_asr_pipeline` is enabled on `docling_library` with an `asr_model_name` (e.g. `whisper_turbo`)
- **THEN** the converter format options configure both `InputFormat.AUDIO` and `InputFormat.VIDEO` with the resolved ASR model specification and record `asr_model_name` in extraction metadata on success

#### Scenario: Video uses Docling defaults when no ASR model is named
- **WHEN** `use_asr_pipeline` is enabled without an `asr_model_name`
- **THEN** `InputFormat.VIDEO` is left on Docling's default video options and no error is raised

#### Scenario: Missing video format option support degrades gracefully
- **WHEN** the installed Docling does not expose `VideoFormatOption`
- **THEN** `InputFormat.AUDIO` is still configured and a warning is logged

### Requirement: Magic-byte fallback detection for extensionless binary streams
When a document's `name` and `path` lack a file suffix, the extraction utility SHALL inspect magic bytes to infer `.epub` (ZIP container with `application/epub+zip` mimetype header) and `.webp` (`RIFF....WEBP` header) in addition to PDF, OpenXML Office, PNG, JPEG, GIF, TIFF, HTML, and UTF-8 plain text. The EPUB check SHALL run before the OpenXML `word/`, `xl/`, and `ppt/` checks.

#### Scenario: Extensionless EPUB stream is identified from ZIP mimetype header
- **WHEN** an extensionless document stream begins with a `PK` ZIP header containing `mimetypeapplication/epub+zip`
- **THEN** magic-byte detection resolves the extension to `.epub`, even if the archive also contains `word/` paths

#### Scenario: Extensionless WebP stream is identified from RIFF WEBP header
- **WHEN** an extensionless document stream begins with `RIFF` at bytes `0..4` and `WEBP` at bytes `8..12`
- **THEN** magic-byte detection resolves the extension to `.webp`
