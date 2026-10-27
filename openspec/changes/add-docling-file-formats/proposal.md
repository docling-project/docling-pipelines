# Proposal

## Why

Docling `2.142.1` natively supports a much broader set of pure-Python document formats (CSV, EPUB, Email `.eml`/`.msg`, LaTeX `.tex`/`.latex`, AsciiDoc `.adoc`/`.asciidoc`/`.asc`, WebVTT `.vtt`, HTML/MHTML variants `.htm`/`.xhtml`/`.mhtml`/`.mht`, Markdown variants `.markdown`/`.text`/`.qmd`/`.rmd`, and OpenXML macro/template variants `.dotx`/`.docm`/`.dotm`/`.potx`/`.ppsx`/`.pptm`/`.potm`/`.ppsm`/`.xlsm`/`.xltx`/`.xltm`) as well as additional video containers (`.mkv`, `.webm`), but `docpipe` currently restricts `OperatorConstants.FileExtensions` to 16 base extensions and 9 audio/video extensions. In addition, `OperatorUtils.extract_content()` only checks `FormatToExtensions[InputFormat.AUDIO]` when routing media streams to temporary files (and writes them into the process working directory), and `DoclingAdapter` only binds `InputFormat.AUDIO` when `use_asr_pipeline` is enabled, leaving `InputFormat.VIDEO` unconfigured for custom ASR models.

## What Changes

- **Affected layers**: **Full-stack** (backend operator constants, ingestion/extraction/classification operators, and frontend `IngestSource` constants).
- **Tier 1 pure-Python format support**:
  - Expand `OperatorConstants.FileExtensions.BASE_EXTENSIONS` (propagating to `DOCLING_LIBRARY_BASE_EXTENSIONS`) with Docling's pure-Python supported extensions that require no extra Python packages or external `soffice` binaries:
    - Tabular/Data: `.csv`
    - E-book & Publishing: `.epub`, `.tex`, `.latex`, `.adoc`, `.asciidoc`, `.asc`
    - Email: `.eml`, `.msg`
    - Subtitles/Captions: `.vtt`
    - Web/Markup variants: `.htm`, `.xhtml`, `.mhtml`, `.mht`, `.markdown`, `.text`, `.qmd`, `.rmd`
    - OpenXML Word/PowerPoint/Excel macro & template variants: `.dotx`, `.docm`, `.dotm`, `.potx`, `.ppsx`, `.pptm`, `.potm`, `.ppsm`, `.xlsm`, `.xltx`, `.xltm`
  - **`docling_serve` mode is unchanged**: `DOCLING_SERVE_EXTENSIONS` becomes an explicit list of the original 16 base extensions instead of a copy of `BASE_EXTENSIONS`, because the remote server's format support is not verified. Tier 1 and Tier 4 formats are accepted in `docling_library` mode only.
  - **Default `include_filter` widens (intentional)**: `IngestSourceOperator` defaults `included_extensions` to `get_supported_file_extensions()`, so flows with no `include_filter` will ingest all Tier 1 formats (and Tier 4 when ASR is available) in addition to the previous 16.
  - Expand `CLASSIFICATION_FILE_EXTENSIONS` with the Tier 1 formats except the plain-markdown variants (`.markdown`, `.text`, `.qmd`, `.rmd`), consistent with `.md` and `.txt` already being excluded.
  - Fix `get_supported_file_extensions()` in `src/docpipe/core/operators/operator_utils.py` so it copies `BASE_EXTENSIONS` (`[*OperatorConstants.FileExtensions.BASE_EXTENSIONS]`) instead of mutating the class-level constant list in-place when ASR is available.
- **Tier 4 video format completion & `InputFormat.VIDEO` pipeline fix**:
  - Add `.mkv` (`EXT_MKV`) and `.webm` (`EXT_WEBM`) to `OperatorConstants.FileExtensions.AUDIO_VIDEO_EXTENSIONS` (and `DOCLING_LIBRARY_AUDIO_VIDEO_EXTENSIONS`).
  - Fix `OperatorUtils.extract_content()` so `audio_video_suffixes` unions both `FormatToExtensions[InputFormat.AUDIO]` and `FormatToExtensions[InputFormat.VIDEO]`, and write the payload to a uniquely named file inside a `tempfile.TemporaryDirectory` (not the process working directory) before invoking `converter.convert()`.
  - Update `DoclingAdapter` (`extract_single_document()` and `_build_gpu_converter()`) so that when `use_asr_pipeline` is enabled and ASR is available, `InputFormat.VIDEO` is also configured via `VideoFormatOption` / `VideoPipeline` / `VideoPipelineOptions` with `generate_frame_images=False` and, when `asr_model_name` is set, the selected ASR model spec.
- **Magic-byte & MIME-type detection**:
  - Extend `OperatorUtils.detect_extension_from_bytes()` to identify `.webp` (`RIFF....WEBP`) and `OperatorUtils.detect_extension_zip_based_office_formats()` to identify `.epub` (`application/epub+zip` mimetype entry, checked before the Office markers).
  - Add `CSV = "text/csv"` and `EML = "message/rfc822"` to `OperatorConstants.MimeTypes` and map them to `.csv` / `.eml` in `WebPageSourceAdapter`.
- **Docs**: update the extract and ingest operator READMEs, `docs/reference/OPERATORS.md`, and `USER_GUIDE_PIPELINE_SETUP.md` (ffmpeg format lists now include MKV and WebM).
- **Frontend `IngestSource` constants (`frontend/src/components/PropertiesPanel/CustomPanels/IngestSource/constants.ts`)**:
  - Update `SUPPORTED_FILE_EXTENSIONS` feeding the `include_filter` / `exclude_filter` `FilterableMultiSelect` controls to match the expanded backend `AUDIO_VIDEO_EXTENSIONS` and `BASE_EXTENSIONS`. No frontend spec delta.

## Non-goals

- Adding Tier 2 formats that require new third-party Python dependencies in `pyproject.toml` (OpenDocument `.odt`/`.ods`/`.odp` via `odfdo`, or `.xbrl` via `arelle`).
- Adding Tier 3 legacy Office formats (`.doc`, `.dot`, `.rtf`, `.ppt`, `.pot`, `.pps`, `.xls`, `.xlt`) or iWork chart rendering that require a system-level LibreOffice (`soffice`) binary on `PATH`.
- Adding Tier 5 compound-extension archive formats (`.tar.gz` for `METS_GBS`, `.dclg.xml`) or ambiguous raw extensions (`.xml`, `.json`) that require schema-specific disambiguation.
- Supporting Tier 1 / Tier 4 formats in `docling_serve` mode, or extending the `DoclingServeClient` MIME map.
- Ingesting binary `.epub` over HTTP: `WebPageSourceAdapter` stores decoded page text, so binary payloads are not preserved. `.epub` remains supported from filesystem and object-store providers.
- Google Drive adapter changes: regular-file extensions already come from the file name and only Workspace MIME types need mapping.
- Changing any FastAPI REST routes, BFF proxy routes, `/ui` routing, Redux state slices, or storage adapters (DuckDB/Postgres).

## Capabilities

### New Capabilities
- `backend/extract-operator`: Tier 1 / Tier 4 extension validation in `docling_library` mode (`docling_serve` unchanged), magic-byte extension detection, temporary-directory routing for `InputFormat.AUDIO` and `InputFormat.VIDEO`, and ASR pipeline format option binding for both audio and video inputs.
- `backend/ingest-source-operator`: Supported file extension discovery (`get_supported_file_extensions()` without mutating `BASE_EXTENSIONS`), widened default `include_filter`, `include_filter` / `exclude_filter` validation against Tier 1 and Tier 4 extensions, and `text/csv` / `message/rfc822` MIME mapping in `WebPageSourceAdapter`.
- `backend/document-classifier-operator`: Classification extension validation covering Tier 1 formats.

### Modified Capabilities
- None.

## Impact

- **Layer**: Full-stack (`backend` + `frontend`).
- **Backend operators & utilities affected**:
  - `src/docpipe/core/constants/operator_constants.py` (`OperatorConstants.FileExtensions`, `OperatorConstants.MimeTypes`)
  - `src/docpipe/core/operators/operator_utils.py` (`get_supported_file_extensions`, `OperatorUtils.extract_content`, `OperatorUtils.detect_extension_from_bytes`, `OperatorUtils.detect_extension_zip_based_office_formats`)
  - `src/docpipe/core/operators/extract/adapters/outbound/text_extraction/docling_adapter.py` (`_build_gpu_converter`, `extract_single_document`)
  - `src/docpipe/core/operators/ingest/adapters/outbound/sources/web/adapter.py`
  - **REST routes, BFF proxy, storage adapters, `DoclingServeAdapter`, Google Drive adapter**: None affected.
- **Frontend components affected**:
  - `frontend/src/components/PropertiesPanel/CustomPanels/IngestSource/constants.ts` (`SUPPORTED_FILE_EXTENSIONS`).
  - **Routing (`/ui`), BFF proxy routes, Redux slices**: None affected.
- **Behavior change**: flows that omit `include_filter` on `ingest_source` will now ingest the additional Tier 1 formats.
- **Dependencies**: No `pyproject.toml` or `package.json` dependency changes required (`mail-parser` and `python-oxmsg` already ship with `docling[standard]`). Slim installs without the email extras fail at extraction time for `.eml` / `.msg` only.
