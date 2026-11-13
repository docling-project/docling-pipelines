# Proposal

## Why

In `docpipe`, operators and adapters use Pydantic models for configuration and provider validation. However, the formatting and presentation of Pydantic validation errors across operators, adapters, flow validation, and runtime execution is inconsistent:
- Some operators and adapters stringify raw `ValidationError` exceptions (e.g. `f"...: {exc}"` or broad `except Exception as e:` in `IngestSourceOperator`, storage destinations, ACL adapters, and runtime document ingestion / lazy binary fetching), embedding raw Python exception representations and potentially disclosing rejected inputs and credentials in validation responses, logs, and failure metadata.
- Standard Pydantic v2 `ValueError` exceptions raised in field or model validators default to a `"Value error, <message>"` format with a comma, whereas other docpipe validation errors use colon formatting (`"Value error: <message>"`).
- Certain validator implementations interpolate user-supplied input strings (e.g. `WebPageSourceConfig.validate_urls`) directly into `ValueError` messages, allowing credentials in URLs or connection strings to be exposed in validation outputs and execution failure records.
- Operator constructor exceptions during flow validation can fall back to generic string formatting in `FlowValidator`, exposing unformatted exception representations in validation alerts.
- Missing field messages and custom errors need a uniform, secure rendering mechanism that treats the rendered error message (`msg`) as the single source of truth without leaking internal context diagnostics (`ctx["error"]`).

Standardizing Pydantic validation error formatting centrally across validation, orchestration, and runtime execution entrypoints improves developer and user experience, prevents sensitive input disclosure, and provides consistent, clean error messages across all operator configurations, validation endpoints, API routes, and CLI/library execution.

## What Changes

- Add a centralized `format_pydantic_errors(exc: ValidationError) -> list[str]` helper in `docpipe.utils.operators.config_validation`.
- Standardize Pydantic error formatting rules:
  - Format field locations into location labels using standard dot and bracket index syntax (`_format_loc`, e.g. `connection_params.paths`, `items[0].val`).
  - Missing fields are formatted as `"<field_path> is not provided"`.
  - Standard `value_error` message bodies with `"Value error, "` prefixes are normalized to `"Value error: "`.
  - Distinguish the location label from the message body, attaching `<field_path>: ` to non-missing field errors when the message body does not already start with `<field_path>`, while leaving model-level errors with empty locations unprefixed.
  - Custom error messages from `PydanticCustomError` or other error types preserve their rendered message body directly without exposing `ctx["error"]` diagnostics.
  - Omit separate input, context, and URL fields via `exc.errors(include_input=False, include_context=False, include_url=False)` to prevent raw input and diagnostic context exposure.
- Standardize error formatting across operator validation, orchestration, and execution boundaries:
  - Vector database adapters (`VectorDBOperator`, `WeaviateConfig`).
  - Ingest source operator (validation, runtime execution `_process_documents_from_adapter()`, and lazy binary fetching) and provider configs (e.g., sanitizing URL interpolation in `WebPageSourceConfig`).
  - Storage destination operators (`StorageOutputOperator`) and ACL adapters (`SharePointACLAdapter`).
  - Extraction adapters (`DoclingAdapter`, `OcrConfig`, and Docling VLM options).
  - Quality, PII, and HAP adapters (`HuggingFaceHAPAdapter`, `WatsonxPIIAndHAPAdapter`, `PresidioPIIAdapter`).
  - Orchestration constructor fallbacks in `FlowValidator` and `PythonOperatorExecutor` to format unhandled constructor `ValidationError` cleanly.
- Add boundary-level regression tests across validation and execution entrypoints:
  - Flow validation endpoint (`POST /api/v1/validation/validate_flow`).
  - Python library interface (`DocpipeFlowManager.validate()` / execution).
  - CLI flow validation and execution.
  - Ingest provider validation, orchestration, and runtime execution failure metadata.

## Non-goals

- Modifying REST API route request validation handlers (`RequestValidationError` in `FastAPI` middleware) or changing HTTP response DTO schemas.
- Changing startup application settings error logging in `api/main.py`.
- Changing validation semantics or modifying constraint rules of existing operator Pydantic models beyond message sanitization for credential safety.
- Implementing an application-wide translation / i18n framework in this change.

## Capabilities

### New Capabilities
<!-- None -->

### Modified Capabilities
- `backend/operators-api`: Standardize Pydantic configuration validation error formatting across operator validation, introspection, orchestration, and execution boundaries.

## Impact

- **Affected Code**: `src/docpipe/utils/operators/config_validation.py`, `src/docpipe/core/orchestration/flow_validator.py`, `src/docpipe/core/operators/vectordb/`, `src/docpipe/core/operators/ingest/`, `src/docpipe/core/operators/storage/`, `src/docpipe/core/operators/acl/`, `src/docpipe/core/operators/extract/`, `src/docpipe/core/operators/quality/pii_and_hap/adapters/`.
- **APIs & DTOs**: No breaking API contract changes; error strings returned in `FlowValidationResponse.errors` and runtime failure metadata will have consistent formatting without leaked exception objects or raw inputs.
- **Dependencies**: No new external dependencies (uses standard `pydantic`).
