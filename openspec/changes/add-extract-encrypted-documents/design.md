# Design

## Context

See `proposal.md` for motivation. `ExtractOperator` (`src/docpipe/core/operators/extract/extract_operator.py`) is a built-in `Extract` operator. It works purely in the operator execution layer: it receives and returns `pyarrow.Table` instances and does not touch the DDD layers in `core/assets/` or `core/job_management/`.

Document bytes reach extraction along two paths, and both start with `OperatorUtils.prepare_document_content_fetch()`, which returns one task dict per row (`idx`, `doc_id`, `doc_name`, `binary_content`, or `error`):

1. **Sequential path** (no entity extraction): `TextExtractionPort.transform()` (`ports/outbound/text_extraction.py`) submits each task to a thread or process pool via `_submit_extraction_task()`, which calls the adapter's `extract_single_document()`.
2. **Streaming path** (entity extraction enabled): `ExtractOperator._run_streaming_pipeline()` submits text tasks directly to `text_adapter.extract_single_document()`, then passes either the extracted text or, for adapters with `requires_binary_content`, the task's `binary_content` to the entity adapter.

Both paths classify a failed result with `is_non_recoverable_error()` (`utils/operators/non_recoverable_utils.py`). Non-recoverable rows are passed to the orchestrator as `NON_RECOVERABLE_DOCS_TABLE`, and `IncrementalUpdateService._process_non_recoverable_docs()` saves them as processed, so later runs skip them until the file changes.

Vault references in operator config are resolved by `PythonOperatorExecutor._resolve_operator_params()` before the operator is constructed, for both the local engine and Prefect batches (`batch_subflow` runs a `PythonOrchestrator`). During flow validation, `FlowValidator._sanitize_vault_refs_for_validation()` replaces them with a placeholder string instead.

Docling serialises its own PDFium calls with `docling.utils.locks.pypdfium2_lock`. Micro-batches run concurrently in one process, so any PDFium call made outside Docling must take the same lock.

## Goals / Non-Goals

**Goals:**
- Decrypt encrypted PDF and OOXML documents in memory, once per document, before any provider or binary entity adapter sees them.
- Keep one shared pooled Docling converter per configuration, whatever the passwords.
- Make password failures explicit and recoverable across incremental runs.
- Keep passwords out of tables, metadata, metrics, failure reasons and logs.

**Non-Goals:**
- Changing the text extraction providers or entity extraction adapters.
- Decryption for `document_classifier` or for runs that reuse its pre-fetched content.
- Reclassifying any other kind of failure.

## Decisions

### 1. Decrypt after fetch, before extraction, instead of using Docling backend options
- **Decision**: Add one step right after `prepare_document_content_fetch()` in both paths. For each task with `binary_content`, it detects encryption and, if needed, replaces `binary_content` with decrypted bytes. The input `pyarrow.Table` is never modified, so decrypted bytes cannot reach the `binary_content` column or any persisted output.
- **Alternatives considered**:
  - *`PdfFormatOption(backend_options=PdfBackendOptions(password=...))` in `DoclingAdapter`*: rejected. It cannot handle Office formats, it only helps `docling_library`, and the converter pool keys instances on option values including a hash of every secret, so each distinct password would build a new `DocumentConverter` and load models again.
  - *Decrypting inside the worker before `extract_single_document()`*: rejected. In the streaming path a binary entity adapter reads `task["binary_content"]` in the main thread, so it would still receive encrypted bytes.

### 2. Failed decryption reuses the existing result handling
- **Decision**: When decryption fails, the step stores a failed extraction result on the task (`success: False`, an `error` message beginning with the reason code, and a `failure_reason` field). Both paths submit such tasks as an already-completed `concurrent.futures.Future` carrying that result instead of calling the adapter, so the existing `as_completed` handling records the failure, removes the row and updates progress with no duplicated branches.
- **Alternatives considered**: *Marking the task with `error`, like a fetch failure*: rejected, because both paths keep rows whose task has `error` in the output table with empty content, while a password failure must remove the row like any other failed extraction.

### 3. Explicit reasons bypass keyword classification
- **Decision**: `is_non_recoverable_error(error_message, *, failure_reason=None)` returns `False` when `failure_reason` is `password_required`, `password_incorrect` or `decryption_unavailable`. Both call sites pass `result.get("failure_reason")`. The keyword list is not changed.
- **Alternatives considered**: *Removing the bare `password` and `encrypted` keywords*: rejected for this change. It would also reclassify unrelated failures that are genuinely permanent, such as Docling's error for password-protected iWork documents, which no configuration can fix.

### 4. Detection and decryption
- **PDF** (`.pdf` extension or `%PDF-` header): a cheap prefilter skips any PDF whose bytes do not contain `/Encrypt`. Otherwise the step opens it with `pypdfium2` and no password while holding `pypdfium2_lock`. If it opens, it is passed through unchanged (owner-password-only or a false positive). If PDFium reports an incorrect password, it is encrypted; each candidate is tried in turn, and the first that opens it is saved with `FPDF_REMOVE_SECURITY` into an in-memory buffer. Any other PDFium error passes the bytes through unchanged, so Docling reports the problem as it does today. PDFium returns the same error for a missing and a wrong password, which is why "no password" is tried first.
- **OOXML** (`.docx`, `.pptx`, `.xlsx`): only files starting with the OLE compound-file signature are considered (an unencrypted OOXML file is a zip). With `msoffcrypto-tool` installed, `OfficeFile.is_encrypted()` confirms encryption and each candidate is tried with `load_key(password=..., verify_password=True)` and `decrypt()` into an in-memory buffer. Without it, the presence of the UTF-16LE `EncryptedPackage` stream name identifies an encrypted package, which fails with `decryption_unavailable`. An encryption scheme the library cannot decrypt also fails with `decryption_unavailable`.
- `msoffcrypto` and `pypdfium2` are imported lazily inside their branches, so a default slim install imports cleanly.

### 5. Configuration model and secrecy
- **Decision**: `document_passwords` is a top-level `extract_operator` parameter, parsed into Pydantic models (`extra="forbid"`) whose password fields are `SecretStr`, so an accidental `repr` or log of the model shows `**********`. Validation errors are rebuilt from each Pydantic error's location and message only, never its input value. The parsed rules live on a decryptor object held by `ExtractOperator` and attached to the text adapter as an attribute. They are not copied into the adapter's `global_config`, which is passed to content fetchers.
- **Matching**: `fnmatch.fnmatchcase` against the row's `name` and, when present, its `path`; the first rule that matches either one wins.
- **Plain-text warning**: raised in `ExtractOperator.validate()`, which only runs during flow validation, where vault references have been replaced by the placeholder. A value that is neither a `vault://` reference nor the placeholder is plain text. The placeholder string becomes a shared constant used by both `FlowValidator` and `ExtractOperator`. At runtime every value is already resolved, so no plain-text check is possible or attempted there.
- **Metadata**: `ExtractOperator.get_metadata()` adds `document_passwords` as an optional JSON attribute with the sensitive flag set.

### 6. Packaging
- **Decision**: add `msoffcrypto-tool` (pinned, like the other entries) to `[project].dependencies` in `pyproject.toml` and to `[project.optional-dependencies].extract` in `slim/pyproject.toml`, then regenerate `uv.lock` and `slim/uv.lock`.

## Risks / Trade-offs

- **Serial decryption on the main thread**: detection and decryption run where content is fetched, before tasks are submitted. PDF work is fast. OOXML agile encryption derives each key with 100,000 hash iterations (tens of milliseconds per candidate), so many encrypted Office files with long candidate lists slow the run. Mitigation: only encrypted documents pay this cost, and candidate lists are expected to be short. Content fetching is already serial in the same place.
- **Re-saved PDFs differ from the original bytes**: removing security rewrites the file, which invalidates digital signatures and flattens incremental updates. Extracted content is unaffected, and the original file is never changed.
- **Memory**: an encrypted document's original and decrypted bytes coexist briefly. The original is released when the task's bytes are replaced.
- **Retries on every run**: documents with password failures are retried by each incremental run until a working password is configured. Detection fails before any model work, so each retry is cheap.
- **Batch with only password failures**: if every document in a batch fails, the existing rule raises and fails the node. The documents are not saved as processed, so they are retried; this matches today's behaviour for any all-failed batch.
- **Detection gaps**: a PDF whose `/Encrypt` key is inside a compressed object stream would bypass the prefilter and fail in Docling as today (still classified by the existing `pdfium: incorrect password` keyword). The PDF specification requires the encryption dictionary reference in the trailer or the cross-reference stream dictionary, which are not compressed, so this is not expected in valid files.
