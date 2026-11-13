# Design

## Context

Operator and adapter configurations are Pydantic v2 models. `ValidationError` text normally carries the rejected input (`input_value=...`), a docs URL and sometimes context. #582 added `sanitize_exception`, which:

- renders `ValidationError` with `include_input=False, include_context=False, include_url=False`;
- reduces client, HTTP, database and network exceptions anywhere in the cause chain to a fixed category plus the config key;
- keeps a wrapper's own message while replacing the wrapped text, or falls back to the category alone;
- is applied at ingest, storage, vectordb, entity store, orchestrator, event handler and job tracker catch sites.

That is the existing owner of exception rendering. This change finishes the work around it rather than building a second mechanism.

### Current coverage (verified against `main` after #582)

| Area | State |
|---|---|
| Ingest `process_documents`, `process_document`, download paths, `validate()` | Sanitized. `validate()` still sniffs `"validation error"` in the text; this keeps working because `CATEGORY_VALIDATION` contains it. |
| Storage output and 5 destination adapters, entity store | Sanitized |
| `VectorDBOperator` init, runtime, `validate_vector_feature_types` | Sanitized |
| `VectorDBOperator.validate()` schema loop, `WeaviateConfig.format_config_errors()`, Hugging Face `_value_errors()` | Private renderers (inputs omitted, wording differs) |
| Orchestrator node failure, event handler, job tracker | Sanitized |
| `PythonOperatorExecutor` constructor | Propagates to `_handle_node_failure`, which sanitizes. No change needed. |
| Dropbox lazy fetch | Config is built outside the `try`; a `ValidationError` propagates to the caller. Not a local sink. |
| Google Drive lazy fetch (`fetch_binary_content`) | Swallows the exception: `logger.exception(... %s, e)` logs the `ValidationError` text and traceback, returns `None`. Probed: sentinel and `input_value` appear in the log. |
| Box lazy fetch (`fetch_binary_content`) | `except ValueError` (superclass of `ValidationError`) logs `%s` raw and returns `None`. Confirmed by a Box probe with invalid credentials. |
| Docling `_build_ocr_options` | `except Exception` logs the raw error with `%s`, then falls back to default options. Probed: sentinel and `input_value` appear in the log. |
| `WebPageSourceConfig.validate_urls` | Interpolates the raw URL. Leaks through the sanitizer. |
| Presidio and Watsonx `validate_provider_config` / init | Raw `{exc}`. Leaks `input_value`. |
| `FlowValidator` operator validation fallback | `{exc!s}`. Leaks `input_value` for constructor `ValidationError`. |
| `AclOperator._initialize_acl_adapter` | `except ValueError` stringifies a `ValidationError` and echoes the failing field's value; the generic handler logs with `exc_info=True`. Verified: a rejected `max_concurrent_requests` is echoed; `client_secret` is not exposed because it is coerced with `str()`. Defense in depth. |

## Goals / Non-Goals

**Goals**
- One renderer for `ValidationError` text, reused by the sanitizer and by adapters that need a list of messages.
- Close the four demonstrated leaks above.
- Pin the contract with boundary regression tests.

**Non-Goals**
- Rewriting exception handling across the pipeline or adding `ValidationError` catches that duplicate existing plumbing.
- Reusing `ErrorFormatter` (CLI console presentation) or adding a new class, registry, strategy layer or global constants.
- Moving error-selection policy out of adapters.

## Responsibilities

| Component | Responsibility |
|---|---|
| `format_pydantic_errors` | Extract diagnostic-free details; format locations, missing fields and message prefixes |
| `sanitize_exception` | Classify exceptions, walk cause chains, add configuration context, render wrappers safely |
| Adapter / operator | Select relevant errors, keep provider-specific policy, keep failure accounting |
| Validator | Validate without embedding credentials in its message |
| API / CLI boundary | Present the resulting messages with existing response and display structures |

Sharing formatting does not share policy. Hugging Face still drops `extra_forbidden` during flow validation and reports unknown keys separately; Watsonx and Presidio still prefix `"<key> is invalid for provider '<name>': ..."`.

## Decisions

### Decision 1: The formatter lives in `exception_sanitizer.py`
- **Choice**: `format_pydantic_errors(*, exc: ValidationError, prefix: str = "") -> list[str]` in `docpipe.utils.infrastructure.exception_sanitizer`. `sanitize_exception` calls it in place of `_validation_detail`.
- **Rationale**: the module already owns Pydantic rendering and depends only on `pydantic`. `utils/operators/config_validation.py` owns operator-metadata validation and imports operator and core constants; making a cross-cutting sanitizer depend on it adds coupling in the wrong direction.
- **Alternatives rejected**: `config_validation.py` (coupling above); `ErrorFormatter` (CLI presentation, not canonical messages); a per-adapter helper (drift); a new class or registry (nothing to configure).
- **Constants**: formatting wording stays local to the formatter. Existing `CATEGORY_VALIDATION` is reused. No new global constants.

### Decision 2: Output contract
For each error from `exc.errors(include_input=False, include_context=False, include_url=False)`, let `loc` be the location formatted with dots for keys and brackets for indices (`items[0].val`), and `path` be `loc` joined to `prefix` with a dot (`prefix` alone when `loc` is empty, `loc` alone when `prefix` is empty).

| Case | Output |
|---|---|
| `type == "missing"` | `<path> is not provided` |
| Any other error, non-empty `path` | `<path>: <message>` |
| Model-level error, empty `path` | `<message>` |

`<message>` is `msg` unchanged, except that for `type == "value_error"` a leading `Value error, ` becomes `Value error: `. `ctx["error"]` is never read.

There is no check for whether the message "already names the field". An explicit path is deterministic even when the message repeats the field name. If deduplication is later required, it needs an exact, bounded rule and its own tests; it is out of scope here.

### Decision 3: Sanitizer behavior is preserved
`sanitize_exception` keeps its categories, its `<config_key>: ...` envelope, its cause-chain walk and its wrapper-redaction logic. For a validation error it renders `<config_key>: configuration validation error (<messages joined by "; ">)` where each message comes from `format_pydantic_errors(prefix=config_key)`. Only the per-field wording changes (`Field required` becomes `is not provided`, `Value error, ` becomes `Value error: `). Its existing canary tests keep asserting that no input appears.

### Decision 4: Catch only where a concrete responsibility exists
Where a handler already calls `sanitize_exception`, the Decision 1 change is enough. A specific catch or call is added only when:
- an adapter stringifies the raw exception (Presidio, Watsonx);
- flow validation must turn a constructor failure into an alert (`FlowValidator`);
- a boundary otherwise exposes raw text (`AclOperator`);
- a local handler swallows the exception and emits it to a log itself, so no downstream sanitizer can run (Google Drive and Box lazy fetch, Docling OCR options).

The change at each of these is inside the existing `except` clause: render the exception with `sanitize_exception(exc=..., config_key=...)`. No new `except` clause is introduced and exception propagation, failure accounting and cleanup are unchanged. `PythonOperatorExecutor` is not touched: a constructor failure there already propagates to `_handle_node_failure`.

**The whole emitted log is in scope, not only the interpolated message.** A sanitized message does not sanitize an attached traceback or chained exceptions: `exc_info=True` and `logger.exception` render the final `ValidationError` text and its `__cause__` chain. At the sinks in this decision the handler therefore logs the sanitized text with `logger.error` / `logger.warning` and without `exc_info`, `stack_info` or `logger.exception`. Exception chaining stays intact (`raise ... from e`) so that propagation and the orchestrator's sanitizer still see the original cause. Trade-off: the raw stack is no longer in these particular log lines; the fixed category and config key remain.

### Decision 5: Fix leaks at their source
Dropping `input`, `ctx` and `url` does not sanitize secrets inside `msg`.
- `WebPageSourceConfig.validate_urls` raises `URL must start with http:// or https://` without the URL (the failing index can be named instead).
- Presidio and Watsonx adapters render through `format_pydantic_errors`, keeping their `"<key> is invalid for provider '<name>': ..."` prefix.
- Validator messages in other provider configs were audited: they interpolate field names and allowed-value lists, not user input.
- **Permitted non-sensitive diagnostics.** The contract is not "never reflect input"; it is "never reflect input that can carry a credential". One reflected value is explicitly permitted: the local path in `FilesystemSourceConfig` (`Root path does not exist: {path}`), because the path is the thing the operator must fix and a credential is not expected in it. It is the only entry; adding another requires a design change. Probed: a sentinel in a nonexistent path remains in the authored message and in the sanitizer output, as intended.
- Custom message bodies are preserved verbatim by the formatter. This is a documented limit: formatting does not make arbitrary validator text safe.

### Decision 6: Adapter-owned policy stays in adapters
- Hugging Face keeps `_unknown_key_errors` and the `extra_forbidden` suppression; only `_value_errors` delegates its rendering.
- `VectorDBOperator.validate()` keeps its loop's role (call the schema, collect messages) and delegates rendering. `WeaviateConfig.format_config_errors()` is removed in favor of the shared formatter; `WeaviateAdapter` and its tests are updated.

## Risks / Trade-offs

- **Message text changes.** `Field required` becomes `is not provided` and `Value error, ` becomes `Value error: ` in sanitizer output and adapter messages. A search of `tests/`, `src/` and `docs/` found no consumer outside the sanitizer's own tests. Mitigation: update those tests in the same change and say so in the PR.
- **Overlap with open PRs.** #590 edits `ingest_source.py`, `vectordb_operator.py` and `flow_validator.py`; #583 and #617 edit the ACL operator and adapter. Mitigation: the formatter and the adapter-only fixes do not touch those files and can ship first; the `FlowValidator` and ACL call sites are rebased onto whichever of those PRs merges first.
- **Residual validator risk.** A future validator can still interpolate input. Mitigation: a scenario-based regression test (task 4.2) drives each validator with an explicit valid baseline and a one-field mutation, verifies the intended rejection, and asserts the sentinel is absent from rendered output, except for the single permitted diagnostic above.
- **Less stack detail at the swallowing sinks.** Those log lines lose the raw traceback. Mitigation: they keep the fixed category and config key, and the caller-side handling is unchanged. Re-adding frames without the final exception line is possible later if needed.
