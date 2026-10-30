# Design

## Context

See `proposal.md` for motivation and scope.

Currently, file format eligibility across ingestion, extraction, classification, and UI configuration is anchored by static lists in `OperatorConstants.FileExtensions` (`src/docpipe/core/constants/operator_constants.py`) and mirrored in `SUPPORTED_FILE_EXTENSIONS` (`frontend/src/components/PropertiesPanel/CustomPanels/IngestSource/constants.ts`):

1. **Extension registry (`OperatorConstants.FileExtensions`)**:
   - `BASE_EXTENSIONS` currently lists 16 extensions (`.pdf`, `.docx`, `.pptx`, `.xlsx`, `.md`, `.txt`, `.html`, `.png`, `.jpeg`, `.jpg`, `.tiff`, `.tif`, `.bmp`, `.webp`, `.gif`, `.jfif`).
   - `AUDIO_VIDEO_EXTENSIONS` currently lists 9 extensions (`.wav`, `.mp3`, `.m4a`, `.aac`, `.ogg`, `.flac`, `.mp4`, `.avi`, `.mov`), omitting `.mkv` and `.webm` from `docling.datamodel.base_models.FormatToExtensions[InputFormat.VIDEO]`.
   - `DOCLING_LIBRARY_BASE_EXTENSIONS` and `DOCLING_SERVE_EXTENSIONS` are both copies of `BASE_EXTENSIONS`.
   - `get_supported_file_extensions()` in `src/docpipe/core/operators/operator_utils.py` assigns `supported_extensions = OperatorConstants.FileExtensions.BASE_EXTENSIONS` by reference and calls `.extend(AUDIO_VIDEO_EXTENSIONS)` when `is_asr_available()` returns `True`, mutating `BASE_EXTENSIONS` in-place.
   - `IngestSourceOperator` defaults `included_extensions` to the result of `get_supported_file_extensions()` when no `include_filter` is given.
2. **Audio/Video extraction in `OperatorUtils.extract_content()` and `DoclingAdapter`**:
   - `OperatorUtils.extract_content()` constructs `audio_video_suffixes` solely from `FormatToExtensions[InputFormat.AUDIO]`, causing video files to fall through to `DocumentStream` instead of the file-path conversion path. The existing file path conversion writes to `Path.cwd() / doc_name`, which is shared across threads and trusts `doc_name`.
   - `DoclingAdapter` (`_build_gpu_converter()` and `extract_single_document()`) binds `format_options[InputFormat.AUDIO] = AudioFormatOption(...)` when `use_asr_pipeline` is enabled, but does not configure `InputFormat.VIDEO`.

## Goals / Non-Goals

**Goals:**
- Maintain a single, consistent set of Tier 1 pure-Python and Tier 4 audio/video extensions across `OperatorConstants.FileExtensions`, `IngestSourceOperator`, `ExtractOperator` (`docling_library`), `DocumentClassifierOperator`, and the `IngestSource` frontend constants.
- Ensure `get_supported_file_extensions()` is side-effect-free and never mutates `OperatorConstants.FileExtensions.BASE_EXTENSIONS`.
- Route both `InputFormat.AUDIO` and `InputFormat.VIDEO` extensions through a safe, per-call temporary-file path in `OperatorUtils.extract_content()` and bind `InputFormat.VIDEO` options in `DoclingAdapter` when `VideoFormatOption` is available.
- Preserve hexagonal / DDD boundaries across operators, ports, and outbound adapters.

**Non-Goals:**
- Introducing runtime probes for external binaries (`soffice` / LibreOffice) or adding optional Python packages (`odfdo`, `arelle`).
- Replacing the static `SUPPORTED_FILE_EXTENSIONS` frontend array with a new REST API endpoint.
- Extending `docling_serve` mode to the new formats.

## Architecture & DDD Layer Boundaries

### Backend DDD / Hexagonal Layering

```text
+-------------------------------------------------------------------------+
|Constants & Shared Utilities                                             |
|  OperatorConstants.FileExtensions / MimeTypes                           |
|  OperatorUtils (get_supported_file_extensions, extract_content,         |
|                 detect_extension_from_bytes)                            |
+--------------------+-----------------------------------+----------------+
                     |                                   |
                     v                                   v
+------------------------------------+  +---------------------------------+
|Ingest Hexagonal Boundary           |  |Extract Hexagonal Boundary       |
|  Operator: IngestSourceOperator    |  |  Operator: ExtractOperator      |
|  Port: DocumentSourcePort          |  |  Port: TextExtractionPort       |
|  Adapters:                         |  |  Adapters:                      |
|    - WebPageSourceAdapter          |  |    - DoclingAdapter             |
|    - Filesystem / S3 / Box / etc.  |  |    - DoclingServeAdapter        |
+------------------------------------+  +---------------------------------+
```

- **Domain / Constants (`src/docpipe/core/constants/operator_constants.py`)**:
  - Pure constant definitions (`OperatorConstants.FileExtensions` and `OperatorConstants.MimeTypes`); no framework or adapter imports.
- **Operator / Application Layer (`IngestSourceOperator`, `ExtractOperator`, `DocumentClassifierOperator`)**:
  - Validates document extensions against `OperatorConstants.FileExtensions` and `get_supported_file_extensions()`; orchestrates table filtering and `skipped_docs` metadata recording without directly invoking `docling` pipelines or external HTTP clients.
- **Ports (`TextExtractionPort`, `DocumentSourcePort`)**:
  - Unchanged contracts.
- **Outbound Adapters (`DoclingAdapter`, `WebPageSourceAdapter`)**:
  - `DoclingAdapter` translates operator config into Docling `FormatOption` instances (`PdfFormatOption`, `ImageFormatOption`, `AudioFormatOption`, `VideoFormatOption`).
  - `WebPageSourceAdapter` maps HTTP `Content-Type` headers to canonical `OperatorConstants.FileExtensions`.
  - `DoclingServeAdapter` is unchanged and continues to use the original 16 extensions.

### Frontend Component Hierarchy & Interaction Mapping

```text
CommonProperties (Elyra Canvas right-flyout container)
└── PropertiesPanel
    └── Tabs / TabList / Tab / TabPanels / TabPanel (@carbon/react)
        └── IngestSourcePanelBody (frontend/src/components/PropertiesPanel/CustomPanels/IngestSource/IngestSource.tsx)
            ├── RequiredParamTooltip + Dropdown (@carbon/react) [#provider]
            └── Accordion (@carbon/react)
                ├── AccordionItem ("Provider configuration")
                │   ├── ProviderFieldsForm
                │   └── JsonTextArea
                └── AccordionItem ("Ingestion settings")
                    ├── RequiredParamTooltip + NumberInput (@carbon/react) [#max_files]
                    ├── RequiredParamTooltip + FilterableMultiSelect (@carbon/react) [#include_filter]
                    ├── RequiredParamTooltip + FilterableMultiSelect (@carbon/react) [#exclude_filter]
                    └── RequiredParamTooltip + Toggle (@carbon/react) [#ignore_hidden_files]
```

- Only the `SUPPORTED_FILE_EXTENSIONS` array in `constants.ts` changes; `items={[...SUPPORTED_FILE_EXTENSIONS]}` in `IngestSource.tsx` picks it up with no component, state, or SCSS changes. The array is manually mirrored from the backend and has no automatic sync.

## Decisions

### Decision 1: Copy `BASE_EXTENSIONS` in `get_supported_file_extensions()`
- **Choice**: Construct `supported_extensions: list[str] = [*OperatorConstants.FileExtensions.BASE_EXTENSIONS]` before conditionally extending with `AUDIO_VIDEO_EXTENSIONS`.
- **Rationale**: Previously, `supported_extensions = OperatorConstants.FileExtensions.BASE_EXTENSIONS` bound a reference to the class attribute and `supported_extensions.extend(...)` mutated `BASE_EXTENSIONS` in-place whenever `is_asr_available()` returned `True`. Copying the list guarantees idempotence and prevents cross-test or cross-operator state leakage.
- **Alternatives considered**: Converting `BASE_EXTENSIONS` to a `tuple[str, ...]`. Rejected to maintain backward compatibility with any external caller or test asserting `isinstance(BASE_EXTENSIONS, list)`.

### Decision 2: Widen the default `include_filter` instead of pinning it
- **Choice**: Leave `IngestSourceOperator` defaulting `included_extensions` to `get_supported_file_extensions()`, so Tier 1 formats (and Tier 4 when ASR is available) are ingested by default.
- **Rationale**: Matches the existing behavior where audio/video are ingested by default when ASR is installed. Users who want the old behavior set `include_filter` explicitly.
- **Trade-off**: Existing flows without `include_filter` ingest more file types after upgrade. This is documented in the ingest README and the proposal.

### Decision 3: Keep `docling_serve` on the original 16 extensions
- **Choice**: Define `DOCLING_SERVE_EXTENSIONS` as an explicit list of the original 16 `EXT_*` constants rather than `[*BASE_EXTENSIONS]`. `DOCLING_LIBRARY_BASE_EXTENSIONS` continues to copy `BASE_EXTENSIONS`.
- **Rationale**: The deployed docling-serve version is not controlled by this repository, and `DoclingServeClient` sends unknown extensions as `application/octet-stream`. Documents with Tier 1 extensions routed to `docling_serve` are skipped by `ExtractOperator._validate_extensions` with a recorded reason instead of failing remotely.

### Decision 4: Union `InputFormat.AUDIO` and `InputFormat.VIDEO` suffixes and write to a temporary directory in `OperatorUtils.extract_content()`
- **Choice**:
  1. Build `audio_video_suffixes` from both `FormatToExtensions[InputFormat.AUDIO]` and `FormatToExtensions[InputFormat.VIDEO]` using `.lstrip(".")` normalization so entries normalize to `.mp4`, `.mkv`, etc.
  2. Replace `Path.cwd() / doc_name` with a file named `Path(doc_name).name` inside `tempfile.TemporaryDirectory()`. The directory is removed on exit, giving each call its own namespace and dropping any path components in `doc_name`.
- **Rationale**: The current working directory is shared by all worker threads, so identical names collide, and a crafted `doc_name` could write outside the intended directory. The spec requirement is "temporary file", which this satisfies. Docling's media backends select the demuxer from the suffix, so the filename suffix is preserved.

### Decision 5: Configure `VideoFormatOption` in `DoclingAdapter`
- **Choice**: In `_build_gpu_converter()` and `extract_single_document()`, when `self.use_asr_pipeline and _asr_available()` is true, additionally import `VideoFormatOption`, `VideoPipeline`, and `VideoPipelineOptions` and set `format_options[InputFormat.VIDEO] = VideoFormatOption(pipeline_cls=VideoPipeline, pipeline_options=VideoPipelineOptions(...))`, where:
  - `generate_frame_images=False`, because the extract operator emits text/markdown and sampled frame images would add image placeholders and memory cost.
  - `asr_options` is set from the resolved ASR model spec only when `asr_model_name` is set. `_configure_asr_engine()` returns `None` when it is not set, in which case the Docling default is kept.
  - The imports are guarded with `try / except (ImportError, AttributeError)` so unit tests that mock only `AudioFormatOption` on `docling.document_converter` continue to pass.
- **Rationale**: Docling `2.142.1` separates `InputFormat.VIDEO` (`VideoPipeline`) from `InputFormat.AUDIO` (`AsrPipeline`). Without this, user-configured `asr_model_name` applies to audio but not to video. The code comment in `extract_single_document()` claiming Docling has no separate VIDEO format is wrong for this version and is replaced.

### Decision 6: Extend `detect_extension_from_bytes()` and `detect_extension_zip_based_office_formats()` for `.webp` and `.epub`
- **Choice**:
  - In `detect_extension_from_bytes()`: check `binary_content[:4] == b"RIFF" and binary_content[8:12] == b"WEBP"` -> return `".webp"`.
  - In `detect_extension_zip_based_office_formats()`: check `b"application/epub+zip" in content_sample` **before** the `word/`, `xl/`, and `ppt/` checks -> return `".epub"`.
- **Rationale**: EPUB packages commonly contain paths that match the Office markers, so the EPUB check must run first. Both formats have deterministic signatures in the first 2048 bytes.

### Decision 7: Classification gets Tier 1 minus plain-markdown variants
- **Choice**: Add to `CLASSIFICATION_FILE_EXTENSIONS`: `.csv`, `.epub`, `.tex`, `.latex`, `.adoc`, `.asciidoc`, `.asc`, `.eml`, `.msg`, `.vtt`, `.htm`, `.xhtml`, `.mhtml`, `.mht`, `.dotx`, `.docm`, `.dotm`, `.potx`, `.ppsx`, `.pptm`, `.potm`, `.ppsm`, `.xlsm`, `.xltx`, `.xltm`. Do not add `.markdown`, `.text`, `.qmd`, `.rmd`.
- **Rationale**: `.md` and `.txt` are already excluded from the list, so the equivalent variants stay out for consistency.

### Decision 8: Web adapter MIME mapping limited to text-safe types
- **Choice**: Add `text/csv` -> `.csv` and `message/rfc822` -> `.eml` to `_CONTENT_TYPE_TO_EXTENSION` using new `OperatorConstants.MimeTypes.CSV` and `EML`.
- **Rationale**: `WebPageSourceAdapter` stores `lc_doc.page_content.encode("utf-8")`, which is decoded text. A binary `.epub` would be corrupted, so `application/epub+zip` is intentionally not mapped. Google Drive derives regular-file extensions from the file name, so no change is needed there.

## Risks / Trade-offs

- **[Risk] Plain `.txt` vs `.text` handling in `OperatorUtils.extract_content()`** -> **Mitigation**: Keep `.txt` on the fast `OperatorUtils.extract_text_file()` path (which existing unit tests expect) while `.text`, `.markdown`, `.qmd`, and `.rmd` flow through Docling's Markdown backend (verified to convert, including `.Rmd`, since suffixes are lower-cased).
- **[Risk] Existing unit tests mocking `docling.document_converter` with only `AudioFormatOption`** -> **Mitigation**: Guard the video imports as described in Decision 5.
- **[Risk] `VideoPipeline` requires `ffmpeg` on system `PATH` at runtime** -> **Mitigation**: Extension validation gates video on `is_asr_available()`, and Docling's `VideoPipeline` emits a structured conversion error if `ffmpeg` is absent. `USER_GUIDE_PIPELINE_SETUP.md` and `docs/reference/OPERATORS.md` list MKV and WebM among ffmpeg-dependent formats.
- **[Risk] `.eml` / `.msg` on slim installs** -> **Mitigation**: Docling raises an actionable import error for `mail-parser` / `python-oxmsg` only when such a file is parsed; the failure is recorded per document.
- **[Risk] More files ingested by default** -> **Mitigation**: Decision 2; documented behavior change.

## Migration Plan

1. Add the new `EXT_*` constants and update `BASE_EXTENSIONS`, `AUDIO_VIDEO_EXTENSIONS`, `DOCLING_SERVE_EXTENSIONS` (explicit list), and `CLASSIFICATION_FILE_EXTENSIONS` in `OperatorConstants.FileExtensions`, plus `CSV` and `EML` in `OperatorConstants.MimeTypes`.
2. Update `get_supported_file_extensions()`, `OperatorUtils.extract_content()`, `OperatorUtils.detect_extension_from_bytes()`, and `OperatorUtils.detect_extension_zip_based_office_formats()` in `src/docpipe/core/operators/operator_utils.py`.
3. Update `DoclingAdapter` (`_build_gpu_converter()` and `extract_single_document()`) to configure `InputFormat.VIDEO` when ASR is enabled, and update the `WebPageSourceAdapter` MIME mapping.
4. Update `SUPPORTED_FILE_EXTENSIONS` in `frontend/src/components/PropertiesPanel/CustomPanels/IngestSource/constants.ts`.
5. Update docs.
6. Run backend unit tests (`pytest`) and frontend verification (`npm run lint && npm run build`). Rollback is a clean revert of constant lists and helper methods with zero database migrations.
