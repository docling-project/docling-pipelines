# Tasks

## 1. Dependencies

- [x] 1.1 [backend] Add pinned `msoffcrypto-tool` to `[project].dependencies` in `pyproject.toml` and to `[project.optional-dependencies].extract` in `slim/pyproject.toml` (not slim's base dependencies); regenerate `uv.lock` and `slim/uv.lock` with `uv lock`, and note in `docs/guides/SLIM_VARIANT.md` that decrypting password-protected documents comes with the `extract` group; verify with `uv lock --check` in the repository root and in `slim/`, and `python -c "import msoffcrypto"` after `uv pip install -e ".[dev]"`.

## 2. Configuration, Validation and Metadata

- [x] 2.1 [backend] Add the `document_passwords` config key, the three failure-reason constants and a shared vault validation placeholder constant to `src/docpipe/core/constants/`; use the placeholder constant in `FlowValidator._sanitize_vault_refs_for_validation()`; verify existing flow validator tests still pass with `pytest tests/unit -k flow_validator`.
- [x] 2.2 [backend] Add Pydantic models for `document_passwords` (rules with `match` and `passwords`, optional `default`, `extra="forbid"`, passwords as `SecretStr`) and a parser that turns validation errors into messages built from location and message only; verify with unit tests covering valid input, each malformed case from the spec, and that no error message contains a password value.
- [x] 2.3 [backend] Parse `document_passwords` in `ExtractOperator.__init__` (raising `FlowExecutionFailedException` with the sanitised message), add the plain-text password warning and malformed-config errors to `ExtractOperator.validate()`, and add the sensitive `document_passwords` attribute to `ExtractOperator.get_metadata()`; verify with unit tests for the validation errors, the warning for plain strings, no warning for `vault://` references and the sensitive metadata attribute.
- [x] 2.4 [backend] Document `document_passwords` (schema, matching rules, vault references, supported formats, failure reasons and retry behaviour, `docling_serve` receiving decrypted bytes) in `docs/operators/extract/extract_operator_readme.md` and add the parameter to `docs/reference/OPERATORS.md`; verify the examples are valid by running them through `docling-pipelines --flow-file <example> --validate`.

## 3. Detection and Decryption

- [x] 3.1 [backend] Implement candidate resolution (first rule whose `match` fnmatches `name` or `path`, else `default`) and PDF detection and decryption (`/Encrypt` prefilter, `pypdfium2` under Docling's `pypdfium2_lock`, `FPDF_REMOVE_SECURITY` into memory); verify with unit tests using PDFs encrypted at test time: rule order, name and path matching, same name in different folders, default fallback, correct and wrong passwords, no candidates, owner-password-only and unencrypted passthrough.
- [x] 3.2 [backend] Implement OOXML detection and decryption with lazily imported `msoffcrypto` (OLE signature check, `is_encrypted()`, `verify_password=True`), the `EncryptedPackage` fallback that yields `decryption_unavailable` when the library is missing, and `decryption_unavailable` for unsupported schemes; verify with unit tests using `.docx`/`.xlsx` files encrypted at test time, plus a test that simulates the missing library.

## 4. Extraction Wiring and Classification

- [x] 4.1 [backend] Extend `is_non_recoverable_error()` with a keyword-only `failure_reason` that exempts the three password reasons, leaving the keyword list unchanged; verify with unit tests in `tests/unit/` for exempt reasons and unchanged classification of existing messages.
- [x] 4.2 [backend] Apply decryption after `prepare_document_content_fetch()` in `TextExtractionPort.transform()` and `ExtractOperator._run_streaming_pipeline()`, submit failed decryptions as completed futures carrying the failed result, and pass `failure_reason` to `is_non_recoverable_error()` at both call sites; verify with unit tests for both paths: decrypted bytes reach the adapter and a binary entity adapter, password failures remove the row and are absent from `NON_RECOVERABLE_DOCS_TABLE`, the mixed-batch counts from the spec, and that the input table and output metadata contain no password or decrypted bytes.

## 5. Integration Verification

- [x] 5.1 [both] Run `pytest tests/unit/`, `uv run ruff check` and `uv run mypy` on the changed files, and `pre-commit run --from-ref origin/main --to-ref HEAD`; verify all pass.
- [x] 5.2 [backend] Run a sample flow over a folder with an unencrypted PDF, an encrypted PDF and an encrypted `.docx` (passwords configured for one encrypted file only); verify two documents are extracted, one fails with `password_required`, and a second run with the missing password added extracts it without `force_ingest`.

## Workflow follow-up

- Archive the change with `openspec archive add-extract-encrypted-documents` after implementation, tests and code review are complete.
