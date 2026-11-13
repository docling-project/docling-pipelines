# Design

## Context

Operator and adapter configurations in `docpipe` are modeled with Pydantic v2 `BaseModel` classes. When validating configurations during flow validation (`validate_flow`), flow execution, or adapter initialization, Pydantic raises `ValidationError`.

Currently, different parts of the codebase handle `ValidationError` in disparate ways:
- `VectorDBOperator.validate()` and `WeaviateConfig.format_config_errors()` previously implemented custom loops over `exc.errors()`.
- `IngestSourceOperator.validate()` and runtime execution in `_process_documents_from_adapter()` use broad `except Exception as e:` blocks and append `str(e)` directly, outputting multi-line raw Python exception traces and raw input values when building adapter configs during validation or runtime processing.
- Downstream lazy binary fetching in source adapters (Google Drive, Box, Dropbox) independently rebuilds configuration models and logs or wraps unformatted `ValidationError` objects.
- `StorageOutputOperator.transform()` and `SharePointACLAdapter` catch configuration errors and stringify exception objects directly into logs, output rows, and document failure metadata.
- `DoclingAdapter.__init__()` and extraction pipeline options (e.g. `VlmPipelineOptionsProvider`) validate Pydantic option models without formatting `ValidationError`, which is then caught and stringified as a generic error.
- Operator constructor exceptions during flow validation can fall back to generic string formatting in `FlowValidator`, exposing unformatted exception representations in validation alerts.
- Standard Pydantic v2 `ValueError` exceptions from validators render with a `"Value error, "` comma prefix, whereas other error messages and docpipe validation errors use colon formatting (`"Value error: "`).
- Some validators interpolate raw user input (e.g. `WebPageSourceConfig.validate_urls` interpolating invalid URLs into `ValueError` messages), which can expose user credentials embedded in connection strings or URLs during validation or in runtime failure metadata.

## Goals / Non-Goals

**Goals:**
- Provide a single, centralized helper `format_pydantic_errors(exc: ValidationError) -> list[str]` in `docpipe.utils.operators.config_validation`.
- Omit `input`, `context`, and `url` fields from error detail extraction using `exc.errors(include_input=False, include_context=False, include_url=False)`.
- Format nested locations into location labels using standard dot and bracket index syntax (`_format_loc`, e.g. `connection_params.paths`, `items[0].val`).
- Format `missing` error types consistently as `"<field_path> is not provided"`.
- Normalize standard `value_error` message bodies starting with `"Value error, "` to `"Value error: "`.
- Distinguish the location label from the message body, attaching `<field_path>: ` to non-missing field errors when the message body does not already start with `<field_path>`, while leaving model-level errors with empty locations unprefixed.
- Preserve custom rendered error messages (such as from `PydanticCustomError`) as the single source of truth without inspecting or exposing `ctx["error"]` diagnostics.
- Update operator validation, orchestration, and adapter configuration parse sites to use `format_pydantic_errors`, including Ingest (validation, runtime execution, and lazy binary fetch), Storage destination, ACL adapters, Extraction/OCR/VLM, VectorDB, and Quality/PII adapters.
- Preserve adapter-specific error selection policies (e.g., HuggingFace adapter suppressing `extra_forbidden` during flow validation while reporting on direct construction).
- Audit and sanitize validator-authored error messages that interpolate raw user inputs (such as `WebPageSourceConfig.validate_urls`).
- Handle constructor-time `ValidationError` in `FlowValidator` and `PythonOperatorExecutor` to prevent unformatted exception strings in validation alerts and execution failures.
- Ensure boundary-level test coverage across REST API validation routes, Python library (`DocpipeFlowManager`), CLI, orchestration suites (`tests/unit/core/orchestration/` and `tests/unit/core/orchestrator/`), and runtime failure metadata.

**Non-Goals:**
- Modifying FastAPI REST request validation middleware (`RequestValidationError` handler in `src/docpipe/api/middleware/error_handler.py`).
- Changing startup application settings error logging in `api/main.py`.
- Changing the schema or fields of existing operator Pydantic models.
- Building an i18n/localization translation framework.

## Decisions

### Decision 1: Centralized Formatter in `docpipe.utils.operators.config_validation`
- **Choice**: Implement `format_pydantic_errors(exc: ValidationError) -> list[str]` in `src/docpipe/utils/operators/config_validation.py`.
- **Rationale**: `config_validation.py` already houses metadata-driven and configuration validation helpers (`validate_config_from_metadata`, `validate_provider_config_keys`). Placing it here makes it reusable across core operators, orchestration, and provider adapters without circular dependencies.
- **Alternatives Considered**:
  - *Helper on each operator/adapter*: Leads to duplicated formatting logic and inconsistent drift over time.
  - *Subclassing `ValidationError`*: Pydantic v2 raises C/Rust-backed `pydantic_core.ValidationError` which cannot be customized via subclassing.

### Decision 2: Rendered Message Body as Single Source of Truth
- **Choice**: Process `error.get("msg", "")` as the authoritative message body for all error types, applying targeted prefix normalization to the message body when `error_type == "value_error"` and `msg.startswith("Value error, ")`.
- **Rationale**: Inspecting `ctx["error"]` leaks internal diagnostic exceptions and breaks `PydanticCustomError` structures where context holds auxiliary debugging details.
- **Alternatives Considered**:
  - *Extracting `str(ctx["error"])`*: Leaks internal diagnostic context when `PydanticCustomError` is used with a diagnostic `{"error": ...}` payload.
  - *Leaving `"Value error, "` unchanged*: Retains inconsistent comma punctuation across UI and API validation alerts.

### Decision 3: Requesting Only Consumed Detail Fields
- **Choice**: Call `exc.errors(include_input=False, include_context=False, include_url=False)`.
- **Rationale**: Avoids constructing and serializing unused input payloads, documentation URLs (`https://errors.pydantic.dev/...`), and context objects, reducing overhead and preventing raw input disclosure from Pydantic's separate diagnostic dictionary fields. Note that this strips Pydantic's diagnostic fields; custom validator messages that interpolate raw user inputs must still be sanitized at authoring time (Decision 8).

### Decision 4: Preserving Adapter-Specific Error Selection Policies
- **Choice**: Centralize error *rendering/formatting*, but let each adapter or operator retain its domain-specific error selection or grouping rules.
- **Rationale**:
  - The Hugging Face HAP adapter suppresses `extra_forbidden` during flow validation because `validate_config_from_metadata` handles unknown keys from published metadata, but reports them on direct constructor invocation.
  - WatsonX and Presidio adapters prefix provider-specific context (e.g. `f"{config_key} is invalid for provider '{ADAPTER_NAME}': {problem}"`).
  - `IngestSourceOperator.validate()` catches `ValidationError` specifically and prefixes `Configuration validation failed for provider '{self.provider}': {err}` per field error.

### Decision 5: Ingest Execution & Lazy-Fetching Error Normalization
- **Choice**: Catch `ValidationError` explicitly in `_process_documents_from_adapter()` and in lazy binary fetch builders (Google Drive, Box, Dropbox), format errors with `format_pydantic_errors(exc)`, and record normalized failure reasons in metadata and logs.
- **Rationale**: Flows run with `disable_validation: true` or deferred configuration resolution still execute `_build_adapter_config()` or rebuild configs during lazy binary downloads. Normalizing errors here ensures raw inputs and exception objects never reach runtime failure metadata or logger statements.

### Decision 6: Storage Destination and ACL Adapter Formatting
- **Choice**: Catch `ValidationError` explicitly before generic `(ValueError, KeyError)` or `Exception` when building `StorageOutputOperator` and `SharePointACLAdapter` configurations, formatting errors cleanly into failure metadata and error responses via `format_pydantic_errors(exc)` without stringifying raw exception traces.
- **Rationale**: Since `ValidationError` inherits from `ValueError`, catching `ValidationError` first prevents broad handlers from calling `str(exc)` and leaking sensitive storage credentials (such as S3 secret keys or Azure client secrets) in output tables, failure metadata, or error logs.

### Decision 7: Orchestration-Level Constructor Fallback in `FlowValidator` and `PythonOperatorExecutor`
- **Choice**: Catch `ValidationError` explicitly in `FlowValidator` (during validation) and `PythonOperatorExecutor.get_operator()` (during execution), formatting errors via `format_pydantic_errors(exc)` and raising structured validation messages or `DocpipeException`.
- **Rationale**: Unhandled constructor exceptions (such as invalid `input_event` schemas in `IngestSourceOperator.__init__` or invalid adapter configs instantiated at execution time) are caught gracefully and surfaced as clean, standardized messages rather than raw Python exception traces.

### Decision 8: Validator Message Sanitization
- **Choice**: Update validators that interpolate raw input strings (such as `WebPageSourceConfig.validate_urls`) to avoid reflecting raw input that might contain credentials.
- **Rationale**: `include_input=False` only strips Pydantic's separate `error["input"]` field; it cannot strip sensitive strings that a custom validator authored into `ValueError(f"... {raw_input}")`.

### Decision 9: Two-Layer Output Assembly: Location Label vs. Message Body
- **Choice**: Distinguish the **location label** (`<field_path>`) from the **message body** (`<msg>`):
  1. **Location Formatting**: Implement `_format_loc(loc: tuple[str | int, ...]) -> str` mapping object keys with dot notation and array indices with bracket notation (`items[0].val`). If `loc` is empty (model-level validator), `field_path` is empty (`""`).
  2. **Message Body Processing**:
     - `missing`: Body is `f"{field_path} is not provided"` if `field_path` else `"is not provided"`.
     - `value_error`: If `msg.startswith("Value error, ")`, normalize body to `f"Value error: {msg[len('Value error, '):]}"`.
     - Custom errors / other types: Message body `msg` is preserved verbatim without inspecting `ctx["error"]`.
  3. **Complete Formatted Assembly**:
     - `missing`: Output the body directly (e.g. `"connection_params.paths is not provided"`).
     - Empty `field_path` (model-level): Output the normalized message body directly without leading colon (e.g. `"Value error: model check failed"`).
     - Non-empty `field_path`: If the normalized message body (or its inner text after `"Value error: "`) already starts with `field_path`, output the normalized message body directly (e.g. `"Value error: count must be positive"` if the validator authored `ValueError("count must be positive")`). Otherwise, combine location label and message body: `f"{field_path}: {normalized_msg_body}"` (e.g. `"count: Value error: must be positive"`, `"api_key: API key is invalid"`, `"count: Input should be greater than or equal to 1"`).
- **Rationale**: Built-in Pydantic constraint and type errors (e.g. `greater_than_equal`, `int_parsing`) emit generic messages like `"Input should be greater than or equal to 1"`. Attaching the location label ensures the failing field is clearly identified, custom message bodies are preserved verbatim, and redundant duplication is eliminated.

## Risks / Trade-offs

- **[Risk] Custom error message starting with `"Value error, "`**: A custom error using exact type `value_error` whose message starts with `"Value error, "` will have its prefix converted to `"Value error: "`.
  - **Mitigation**: This normalization is intentional to maintain consistent colon punctuation across all `value_error` types.
- **[Risk] Uncaught Pydantic ValidationErrors in downstream components**: Code that uses broad `except Exception:` could obscure `ValidationError` if caught before specific handling.
  - **Mitigation**: Catch `ValidationError` explicitly before general exception handlers across operator validation and execution paths.
