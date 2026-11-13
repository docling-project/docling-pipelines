# Proposal

## Why

`sanitize_exception` (`docpipe.utils.infrastructure.exception_sanitizer`, added by #582) already renders a Pydantic `ValidationError` without `input`, `ctx` and `url` and is called at the main secret-bearing catch sites: ingest, storage output and destinations, vectordb, the entity store, the abstract orchestrator, the flow event handler and the job tracker. What remains is smaller than the original issue described:

- **Several private copies of the same renderer.** `VectorDBOperator.validate()`, `WeaviateConfig.format_config_errors()`, and `HuggingFaceHAPAdapter._value_errors()` each loop over `exc.errors()` with their own wording. The sanitizer has a fourth. The wording differs (`Field required` against `<path> is not provided`).
- **Demonstrated leaks that no sanitizer change can fix:**
  - `WebPageSourceConfig.validate_urls` interpolates the raw URL into `ValueError`, so credentials in a URL reach every message, including the sanitizer's output.
  - `PresidioPIIAdapter` and `WatsonxPIIAndHAPAdapter` interpolate `{exc}`, which includes `input_value=` and the pydantic docs URL.
  - `FlowValidator` renders operator-constructor failures as `f"...{exc!s}"`.
  - `AclOperator._initialize_acl_adapter` catches `ValueError` (a superclass of `ValidationError`) and stringifies it, and its generic handler logs with `exc_info=True`. The rejected value of the failing `SharePointACLConfig` field is echoed. `client_secret` is coerced with `str()` and cannot be rejected today, so this is defense in depth rather than a demonstrated credential leak.
- **Local logging sinks that swallow the exception.** These emit the raw text before any downstream sanitizer runs, and return `None` or fall back to defaults, so the exception never reaches `sanitize_exception`. Probed with a sentinel: Google Drive lazy fetch (`logger.exception` with the `ValidationError` and its traceback), Docling OCR option construction (`logger.warning` with the `ValidationError`, then default options), and Box lazy fetch (`except ValueError` logs `%s` raw, then returns `None`).
- **No regression test** asserts that a rejected input never appears at a public boundary.

## What Changes

- Add `format_pydantic_errors(*, exc, prefix="") -> list[str]` in `exception_sanitizer.py`. It owns extraction (`include_input/context/url=False`), location formatting, missing-field wording and message-prefix normalization. `sanitize_exception` uses it; its category, config-path and cause-chain behavior are unchanged.
- Replace the private copies in `VectorDBOperator.validate()`, `WeaviateConfig.format_config_errors()` and `HuggingFaceHAPAdapter._value_errors()` with the shared formatter. Adapter-owned selection policy (for example Hugging Face suppressing `extra_forbidden` during flow validation) stays in the adapter.
- Fix leaks at the source:
  - `WebPageSourceConfig.validate_urls` stops interpolating the input.
  - Presidio and Watsonx adapters render through the shared formatter.
  - `FlowValidator` and `AclOperator._initialize_acl_adapter` render through `sanitize_exception` in their existing handlers.
- Render the three swallowing sinks above through `sanitize_exception` and stop emitting raw tracebacks there. The ACL generic handler gets the same treatment (message and `exc_info`), with exception chaining preserved for propagation.
- Add sentinel regression tests at representative public boundaries: REST flow validation, `DocpipeFlowManager.validate()`, and the CLI.

## Non-goals

- Adding `except ValidationError` to every configuration constructor. Where a handler already calls `sanitize_exception`, the shared formatter is enough; no new catch is added.
- Changing `PythonOperatorExecutor`, ingest `process_documents` / `process_document`, storage output, or `VectorDBOperator` runtime paths. These propagate or already call `sanitize_exception` through #582 and the orchestrator's failure path. The Dropbox lazy fetch builds its config outside its `try`, so a `ValidationError` propagates to the caller and is not a local sink.
- Changing lazy-fetch or extraction code beyond the specific logging sinks named above.
- A new class, registry, or constants layer. `ErrorFormatter` (CLI presentation) is not reused.
- Changing `RequestValidationError` handling, `api/main.py` startup logging, response DTO schemas, or validation constraints.
- Making arbitrary validator-authored text safe. The formatter cannot do this; validators must not embed credentials (Decision 5).

## Capabilities

### Modified Capabilities
- `backend/operators-api`: Pydantic configuration errors are rendered uniformly and without rejected input across validation and execution boundaries.

## Impact

- **Code**: `utils/infrastructure/exception_sanitizer.py`, `core/operators/ingest/adapters/outbound/sources/{box,google_drive}/adapter.py`, `core/operators/extract/adapters/outbound/text_extraction/docling_adapter.py`, `core/operators/vectordb/` (`vectordb_operator.py`, `weaviate/config.py`, `weaviate/adapter.py`), `core/operators/quality/pii_and_hap/adapters/outbound/` (huggingface, presidio, watsonx), `core/operators/ingest/adapters/outbound/sources/web/config.py`, `core/orchestration/flow_validator.py`, `core/operators/acl/acl_operator.py`.
- **Message text**: sanitizer output changes from `<key>.<field>: Field required` to `<key>.<field> is not provided`; `Value error, ` becomes `Value error: `. A search of `tests/`, `src/` and `docs/` found no consumer of the old text beyond the sanitizer's own tests.
- **APIs and DTOs**: no schema change.
- **Dependencies**: none.
- **Coordination**: #590 and #617 (open) edit `ingest_source.py`, `vectordb_operator.py`, `flow_validator.py` and the ACL adapter. Their overlap affects the order of the call-site changes only; see `tasks.md`.
