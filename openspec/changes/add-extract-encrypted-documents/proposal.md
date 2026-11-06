# Proposal

## Why

`ExtractOperator` (`extract_operator`) cannot process password-protected documents. An encrypted PDF fails inside Docling with `PDFium: Incorrect password error`, and an encrypted `.docx`, `.pptx` or `.xlsx` is an OLE container rather than a zip package, so Docling cannot open it. `is_non_recoverable_error()` matches these failures, so the document is saved to incremental metadata as processed and is skipped on every later run until the file changes or `force_ingest` is set. There is no configuration key for supplying a password, so these documents can never be extracted.

Passing a password through Docling's PDF backend options would not solve this: Docling has no password support for Office formats, every distinct password would create a separate pooled `DocumentConverter` (each loading its models again), and only the `docling_library` provider would benefit. Tracked in issue #149.

## What Changes

- **New `document_passwords` operator parameter on `extract_operator`**: an optional, sensitive object with ordered `rules` (each a `match` pattern and a list of candidate `passwords`) and an optional `default` candidate list. Values may be `vault://` references, which existing executor-level resolution turns into plain strings before the operator runs.
- **In-memory decryption before extraction**: after document bytes are fetched and before any text extraction provider or binary entity extraction adapter sees them, encrypted PDF and OOXML (`.docx`, `.pptx`, `.xlsx`) documents are detected and decrypted with the first candidate password that works. Decrypted bytes exist only in memory for that run; unencrypted documents and other formats pass through unchanged. This applies to both the sequential text-extraction path and the concurrent text-plus-entity path, and to every text extraction provider (`docling_library`, `docling_serve`).
- **Encryption detection runs whether or not `document_passwords` is set**, so an encrypted document in a flow with no passwords configured fails with an explicit reason instead of a Docling error.
- **Explicit, recoverable failure reasons**: `password_required` (encrypted, no candidate configured), `password_incorrect` (every candidate rejected) and `decryption_unavailable` (Office decryption library not installed). These documents are recorded as failed for the run and removed from the output table, but are **not** added to the non-recoverable documents table, so the next incremental run retries them. Adding or fixing a password therefore takes effect without `force_ingest`.
- **Validation**: `extract_operator` validation rejects a malformed `document_passwords` object without echoing password values, and warns when a password is a plain string rather than a `vault://` reference.
- **Packaging**: `msoffcrypto-tool` is added to the base dependencies of `docling-pipelines` and to the `extract` optional group of `docling-pipelines-slim`. A default slim install does not include it. PDF decryption uses `pypdfium2`, which Docling already depends on.

## Non-goals

- Passing passwords to Docling through format or backend options.
- Storing passwords or decrypted bytes in the `pyarrow.Table`, row metadata, operator metrics, job stats, parquet or DuckDB.
- Password-protected archives (tracked in #150), iWork documents, legacy binary Office formats (`.doc`, `.xls`, `.ppt`), images and audio.
- Decrypting documents for `document_classifier`, or for `extract_operator` runs that reuse content pre-fetched by `document_classifier`.
- Per-document passwords supplied by an ingest source (for example a connector-provided column).
- Changing the classification of other non-recoverable errors (corrupted, empty or otherwise unreadable files).
- Frontend changes: the new parameter is rendered by the existing schema-driven properties panel.

## Capabilities

### New Capabilities
- `backend/extract-operator`: Password-protected document handling in the `extract_operator`: the `document_passwords` configuration contract, in-memory decryption, failure reasons and their incremental-run classification, secret handling, and the operator's table and metadata contract for these documents.

### Modified Capabilities
<!-- None -->

## Impact

- **Affected layers**: backend-only. No REST route signatures, BFF proxy routes, `/ui` routes, Redux slices or storage adapters change.
- **Affected operator**: `extract_operator` (`src/docpipe/core/operators/extract/`), including the text extraction port and the concurrent text-plus-entity pipeline. All text extraction providers and binary entity extraction adapters receive decrypted bytes.
- **Affected utilities**: `src/docpipe/utils/operators/non_recoverable_utils.py` gains a way to exempt the new recoverable failure reasons.
- **REST / metadata surfaces**: `GET /api/v1/operators/metadata` exposes `document_passwords` as a sensitive attribute; `POST /api/v1/validation/validate_flow` reports the new validation errors and warnings.
- **Behaviour change**: encrypted documents that previously failed as non-recoverable now fail as recoverable and are retried on each incremental run until a working password is configured. Detection fails before any model work, so a retry is cheap.
- **Dependencies**: `msoffcrypto-tool` (MIT; depends on `cryptography` and `olefile`) in `pyproject.toml` base dependencies and in the `extract` group of `slim/pyproject.toml`; both lockfiles regenerated.
- **Documentation and tests**: `docs/operators/extract/extract_operator_readme.md`, `docs/reference/OPERATORS.md`, `docs/guides/SLIM_VARIANT.md`, and unit tests under `tests/unit/`.
