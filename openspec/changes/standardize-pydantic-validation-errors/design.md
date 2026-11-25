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

**The whole emitted log is in scope, not only the interpolated message.** A sanitized message does not sanitize an attached traceback or chained exceptions: `exc_info=True` and `logger.exception` render the final `ValidationError` text and its `__cause__` chain. At the sinks in this decision the handler therefore logs the sanitized text with `logger.error` / `logger.warning` and without `exc_info`, `stack_info` or `logger.exception`. Exception chaining stays intact (`raise ... from e`) for non-sensitive chains so that propagation and the orchestrator's sanitizer still see the original cause; for a sensitive chain the cause is replaced by a sanitized stand-in (Decision 8), and the lazy-fetch handlers keep a traceback only when the chain is not sensitive (Decision 9). Trade-off: the raw stack is no longer in these particular log lines when the failure is sensitive; the fixed category and config key remain.

### Decision 5: Fix leaks at their source
Dropping `input`, `ctx` and `url` does not sanitize secrets inside `msg`.
- `WebPageSourceConfig.validate_urls` raises `URL must start with http:// or https://` without the URL (the failing index can be named instead).
- Presidio and Watsonx adapters render through `format_pydantic_errors`, keeping their `"<key> is invalid for provider '<name>': ..."` prefix.
- Validator messages in other provider configs were audited: most interpolate field names and allowed-value lists, not user input. The exception is the environment-reference path: `resolve_env_var` (`operator_utils.py`) raises `Environment variable <NAME> is not set` with the reference name, and `WeaviateConfig._validate_cross_field` calls it for `api_key`, `bearer_token`, `username` and `password`. The reference name is not a credential, but it is reflected input, so the path is fixed at its source rather than added to the permitted list: the validator catches the `ValueError` and raises a fixed message that names the field and not the variable. The shared `resolve_env_var` message is unchanged because about twenty callers and their tests depend on it.
- **Permitted non-sensitive diagnostics.** The contract is not "never reflect input"; it is "never reflect input that can carry a credential". Two reflected values are explicitly permitted:
  - The local path in `FilesystemSourceConfig` (`Root path does not exist: {path}`), because the path is the thing the operator must fix and a credential is not expected in it.
  - The Hugging Face HAP `model_id` in the missing-`toxic_labels` error, because it identifies the model whose labels must be configured, not an authentication credential.
  These are the only entries; adding another requires a design change. Their named scenarios assert that the diagnostic values remain in rendered output.
- Custom message bodies are preserved verbatim by the formatter. This is a documented limit: formatting does not make arbitrary validator text safe.

### Decision 6: Adapter-owned policy stays in adapters
- Hugging Face keeps `_unknown_key_errors` and the `extra_forbidden` suppression; only `_value_errors` delegates its rendering.
- `VectorDBOperator.validate()` keeps its loop's role (call the schema, collect messages) and delegates rendering. `WeaviateConfig.format_config_errors()` is removed in favor of the shared formatter; `WeaviateAdapter` and its tests are updated.

### Decision 7: One complete, fail-closed chain traversal in the sanitizer
Review of PR #627 found that `_exception_chain` follows `pending.__cause__ or pending.__context__` (one branch per link) and stops after `_MAX_CHAIN_DEPTH` (10) links, while `traceback.format_exception` prints every `__cause__` and `__context__` branch and `ExceptionGroup` member at any depth. A `ValidationError` shadowed by `__cause__`, deeper than ten links, or inside a group was classified as not sensitive while its formatted traceback still printed the sentinel. Decisions 8 and 9 gate on that classification, so it is fixed first, in `exception_sanitizer.py`:
- `_exception_chain` is an iterative traversal of the whole exception graph: `__cause__`, `__context__` and `BaseExceptionGroup.exceptions`, using `is not None` checks, following `__context__` even when `__suppress_context__` is set (a consumer that reads the attribute still reaches it), with a visited-id set for cycles. `_MAX_CHAIN_DEPTH` is removed; an unbounded walk matches `traceback.format_exception`, so there is no truncation case that could under-report.
- `is_sensitive_chain(*, exc) -> bool` is true when any visited link is classified by `_classify`. It adds no second classifier. `sanitize_exception`, the ACL operator and the lazy-fetch handlers all use it, so there is one definition of sensitive.
- `sanitize_exception` passes every link below the wrapper, classified or not, to `_redact_wrapper_message` as `causes`. An unclassified link between the wrapper and the classified one (for example `RuntimeError` -> `HTTPError` -> `ValueError`) can carry the same secret text, so filtering to classified links would leave it in the wrapper message. The existing fragment check falls back to the fixed category when a truncated copy of any source remains.
- Parity invariant: if `traceback.format_exception(e)` prints text produced by a classified link, `is_sensitive_chain(exc=e)` is true. Tests assert the invariant over the chain shapes in task 6.1 rather than only specific outcomes.

### Decision 8: Replace a sensitive ACL cause with a sanitized stand-in, raised after the handler
`JobManagementService` formats the full chain with `traceback.format_exception`, so `raise ... from e` in the ACL operator prints each link's `str()`, including Pydantic's `input_value=` text or a credential-bearing URL. The ACL tests assert only the wrapper message and `caplog` records, so they did not see it. Rule, applied at every ACL site that wraps an exception:
1. If `is_sensitive_chain(exc=e)` is false, keep `from e`.
2. Otherwise raise the wrapper `from` a plain `ValueError` subclass whose text is `sanitize_exception(exc=e, config_key=...)`. The original is not chained.
3. Raise after the `except` block exits. Raising inside it makes Python set `__context__` to the original, which still carries the sentinel and which `_exception_chain` would reach. Raising after the block with the stand-in as the only cause leaves `__context__` as `None`.

This replaces the ACL scenario requirement that the original stay on `__cause__` for a sensitive chain; non-sensitive chains keep it. The same rule applies to the Box sites that re-raise or raise from a caught exception (`fetch_documents` generator path and message). It applies to every ACL site that writes to a log, to a raised `FlowExecutionFailedException` message (batch, per-document, output-table), or to run-metadata `reason`, on both `fail_on_error` paths, all through `sanitize_exception`. ACL stays at the source because the job service cannot know which exceptions carry secrets, and changing its formatting globally would alter unrelated tracebacks. `DocpipeException.log_details` is not changed: ACL raises `FlowExecutionFailedException`, which the job service does not route through it.

### Decision 9: Lazy-fetch handlers keep a traceback only for non-sensitive failures
Task 3.5 removed the traceback from the Google Drive handler for every failure (`logger.error`). That also drops useful context for failures that carry no secret, and an HTTP or API error is sensitive too (a reproduction raised an `HTTPError` whose URL carries a credential; the sanitizer reduces it, but `traceback.format_exception` prints the original). Rule for the Google Drive and Box lazy-fetch handlers: decide with `is_sensitive_chain`; when true, log sanitized text with `logger.error` and no traceback; otherwise `logger.exception`. Do not add a second classifier or a local chain walk.

### Decision 10: Remaining Box and Docling sites
Box `fetch_documents` generator path (re-raises to the job path) applies Decision 8. Box `_download_file_content` logs sanitized text with `logger.error` and re-raises, since its only caller `fetch_binary_content` swallows every exception. The raised `ValueError(f"...: {e!s}")` in `fetch_documents` uses sanitized text with the stand-in as cause. Box lazy fetch uses Decision 9. Config key is `box`. The `FileNotFoundError` carries a path and is unchanged. The Docling OCR `ImportError` branch renders through `sanitize_exception` with config key `ocr_engine_options`, for consistency with the adjacent branch (it names a module path, not a credential). The flow-validator alert wording is unchanged: the operator name appearing three times for a classified `ValidationError` is cosmetic, an operator name is not a secret, and dropping the prefix would remove the name from the unclassified alert.

### Decision 11: ACL adapter and factory sanitize before the operator does
The operator sanitizes what it logs and raises, but the SharePoint adapter builds a per-request `SharePointACLConfig` inside `extract_acl` and logged the raw `ValidationError` with a traceback, and put it in the `ExternalServiceError` message, before the operator saw it. The ACL adapter factory did the same when a constructor failed. Both now render through `sanitize_exception` and log without a traceback, so the claim that no emitted ACL log record carries the input holds for the real adapter and not only for a mocked one. `raise ... from e` stays because the operator replaces a sensitive cause with the stand-in (Decision 8). The `ImportError` branch is unchanged.

## Risks / Trade-offs

- **Message text changes.** `Field required` becomes `is not provided` and `Value error, ` becomes `Value error: ` in sanitizer output and adapter messages. A search of `tests/`, `src/` and `docs/` found no consumer outside the sanitizer's own tests. Mitigation: update those tests in the same change and say so in the PR.
- **Overlap with open PRs.** #590 edits `ingest_source.py`, `vectordb_operator.py` and `flow_validator.py`; #583 and #617 edit the ACL operator and adapter. Mitigation: the formatter and the adapter-only fixes do not touch those files and can ship first; the `FlowValidator` and ACL call sites are rebased onto whichever of those PRs merges first.
- **Residual validator risk.** A future validator can still interpolate input. Mitigation: a scenario-based regression test (task 4.2) drives each validator with an explicit valid baseline and a one-field mutation, verifies the intended rejection, and asserts the sentinel is absent from rendered output, except for the two permitted diagnostics above.
- **Less stack detail at the swallowing sinks.** Those log lines lose the raw traceback. Mitigation: they keep the fixed category and config key, and the caller-side handling is unchanged. Re-adding frames without the final exception line is possible later if needed.
- **Broader sensitivity detection.** The complete traversal classifies chains as sensitive that the old walk missed, so some sanitizer results and lazy-fetch log lines change from raw text to a category. This is the intended fail-closed direction. Chains with no classified link anywhere are unchanged, and tests assert that. Removing the depth cap trades a bound for completeness; the visited set guarantees termination.
- **Contract change for ACL `__cause__`.** A sensitive chain no longer exposes the original through `__cause__` or `__context__`. The assertions `exc_info.value.__cause__ is original` in `tests/unit/operators/acl/test_acl_operator_paths.py` are rewritten to the stand-in contract; the non-sensitive path keeps the identity assertion.
- **Diagnostic loss in ACL traces.** The sanitized stand-in and wrapper message still name the config key and the failing field or category.
- **`fail_on_error=False` reason text.** `sanitize_exception` returns the raw message for non-sensitive chains, so non-sensitive reasons are unchanged; an empty message becomes the exception class name.
