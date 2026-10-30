# Design

## Context

See [proposal.md](proposal.md) for motivation and scope, and [specs/backend/secret-management/spec.md](specs/backend/secret-management/spec.md) for the requirements. A small delta for [custom operator management](specs/backend/custom-operators-api/spec.md) accompanies it.

**Current behavior, as observed in the code:**

- **Execution.** `PythonOperatorExecutor._resolve_operator_params` resolves every `vault://` reference in the merged config with `resolve_value`. The merged `_params` include `global_config`, and `_populate_ingest_source_config` copies the ingest `provider_config` into it, so each downstream node re-resolves the ingest credentials.
- **Resolution.** `secret_provider._resolve_string_vault_ref` returns a malformed `vault://` string unchanged, which is then used as a literal credential. `_parse_secret_json_if_applicable` turns a secret that looks like JSON into a dict or list. Errors do not carry the config key.
- **Re-interpretation.** `resolve_env_var` runs on already-resolved values in several adapters. `$ecret_Value` raises `Environment variable ecret_Value is not set`, and that text reaches run metadata. `MY_SECRET_KEY` is replaced if an environment variable of that name exists.
- **Third-party errors.** Pydantic validation errors include `input_value=<secret>`. They flow to the log and to `record_failed_document` in `ingest_source.py`.
- **Data plane.** SharePoint and OneDrive adapters write `client_id`, `client_secret`, `tenant_id` into document `metadata`. `ingest_source.py` serializes it with `json.dumps`, so it reaches parquet and the storage sidecar. `acl_operator.py` reads the secret back from that metadata. This happens for literal and environment-variable credentials too.
- **Vault client.** `HashiCorpVaultProvider` puts `response.text` in errors and logs the body at DEBUG. The default address is `http://127.0.0.1:8200`, `VAULT_TLS_SKIP_VERIFY` works for any host, and redirects are not controlled.
- **Enrichment.** `FlowEnrichmentService._resolve_dag_secrets` resolves every node including ingest, logs failures at DEBUG, and keeps the literal `vault://` string. The vectordb metadata fetchers then connect with it.
- **Validation.** `FlowValidator` replaces references with `"__vault_placeholder__"`, and with `{"__vault_mock__": True}` for three keys. Placeholders cause false format errors in S3 `endpoint_url`, filesystem `paths`, and web `urls`. The `ingest_source.py` guard that skips validation when vault refs exist is dead code on the validator path. `flow_validator.py:308` echoes the full malformed reference.
- **Lineage.** `derive_dataset_info_from_ingest` builds dataset names from raw field text, for example `s3://vault://hashicorp/s3#bucket`.
- **Custom operators.** `POST /api/v1/custom_operators` accepts a `.py` file. `ASTOperatorValidator` checks only the contract. `filesystem_adapter._load_module_from_file` calls `exec_module`, so module-level code runs inside the API or worker process on every catalog refresh (create, update, delete). `ENABLE_CUSTOM_OPERATORS_DEFAULT` is true. `custom_operators_router` declares no authentication dependency (neither in the router nor in `api_router.py`), and `api/main.py` disables auth when `JWT_SECRET_KEY` is unset. Operators run in-process with threads and no sandbox, so they can import `secret_provider`, read the Vault token and session, `os.environ`, and shared module state.
- **Prefect.** `persist_result=False` and `NO_CACHE` are set. The content of task parameters was not verified, so this is a task.

**Constraints:**
- Project rules: no secrets in logs, `%s` logging, keyword-only arguments, `@staticmethod` for pure helpers, ports not concrete adapters, DDD layering. Operators never call a database directly.
- Flows with no `vault://` values and no untrusted custom operator must behave as before.
- `owner="custom"` operators must keep working where Vault is not configured.

## Goals / Non-Goals

**Goals:**
- One resolution component and one contract for all operators and all paths.
- No resolved value in any user-visible sink, enforced by prevention, containment, scrubbing, and tests.
- Fail closed everywhere, with fixed, non-probing errors.
- A defined, honest trust model for custom operators.

**Non-Goals:**
- New sandbox technology (containers, seccomp). Process isolation is the supported baseline.
- Protection from deployer-installed code.
- Platform credentials, rotation policy, a frontend change, Weaviate.

## Decisions

### D1. One resolver in `integrations/secrets`, called by the construction path

A `SecretResolver` (module `integrations/secrets/resolver.py`) is the only caller of providers. Its entry point is `resolve_node_config(*, node_name, operator_class, config)`. It:

1. Collects secret-capable key paths from the operator's declaration (D2).
2. Walks only those keys, tracks the key path, and applies the grammar (D3), the path policy (D4), and the type rule.
3. Returns a new config with `SecretValue` objects (D5) and registers each value with the per-run registry (D8).
4. Raises `SecretResolutionError` with a fixed category and a correlation identifier.

The executor and `AbstractOperator.__init__` both call it. If the executor already resolved, nothing is left, so no second Vault call happens. This closes direct construction and library use without making adapters aware of Vault.

*Alternative:* resolve in each adapter. Rejected: it repeats security logic in about 25 places, and a new adapter that forgets it is silent. *Alternative:* executor only. Rejected: enrichment, direct construction, and the extract step's on-demand fetch bypass it.

### D2. Per-field declaration; the inventory is the contract

`AbstractOperator.get_metadata()` gains a `secret_fields` list of dotted key paths (wildcards allowed for dict-valued config such as `credentials.*`). The existing `sensitive` schema flag is a floor. The spec's inventory table defines the initial set, and a test enumerates registered operators and fails when a credential-looking field is neither declared nor marked `no_references`. Naming fields (`index_name`, destination `path`, `prefix`, filters) are deliberately not declarable, which closes the route that writes a secret somewhere the author can read it.

For ingest, declarations live on each adapter config class and are aggregated per provider by `IngestSourceOperator.get_metadata()`, so the S3 declaration does not apply to a web node.

### D3. Strict grammar, one parser

A single parser (`parse_reference(*, value)`) implements the grammar and syntax limits. `vault://` appearing anywhere else in a string, or a malformed whole string, is `malformed reference`. The old fall-through in `_resolve_string_vault_ref` is removed. The validator, the enrichment service, and the resolver all call the same parser, which also removes the divergent placeholder logic.

### D4. Path policy

`secrets.vault.allowed_paths` is a list of `provider:glob` entries in `docling-pipelines-config.yaml`. Unset means allow, with one startup WARNING, so existing deployments do not break. Custom operators use the separate, default-empty `secrets.vault.custom_operator_allowed_paths` (D12). Policy runs before any provider call, in validation as well as execution.

### D5. `SecretValue` opaque type and verbatim use

`SecretValue` is a wrapper, not a `str` subclass, because a subclass is easy to format by accident and some client libraries copy it. It masks `__repr__`, `__str__`, `__format__`, `__reduce__`, `__copy__`, and JSON encoding, and exposes `reveal()` used only at client construction. Derived strings (`user:password`, `Authorization` headers) are built inside the client factory from `reveal()` and registered with the scrubber. `resolve_env_var` returns a `SecretValue` unchanged, so its `$` and upper-case heuristics never see it. For fields declared structured (`credentials_json`) the resolver parses once and wraps the parsed object.

*Trade-off:* a wrapper needs a `reveal()` call in every adapter. Most adapters build one client, so the change is small and reviewable. A test fails if `reveal()` is called outside adapter modules.

### D6. Minimal resolution scope

`_populate_ingest_source_config` stops copying credential fields into `global_config`. It copies only non-secret source facts that downstream nodes need (provider name, include filter). The extract step's on-demand fetch obtains a client from a factory keyed by the ingest node name, which resolves the ingest node's own references at fetch time and caches by digest for the run (D9). `_resolve_operator_params` resolves only the node's own declared fields. `global_config` and batch configuration never carry resolved values.

*Alternative:* keep copying and mask. Rejected: the leak surface remains in every downstream node and in micro-batch configs.

### D7. Data-plane fix

SharePoint and OneDrive adapters stop writing credentials to `metadata`. `ACLOperator` gets its own secret-capable `credentials` object. If ACL config has no credentials it fails with a message naming the missing keys, rather than silently reading metadata. A sweeping test asserts no adapter's document metadata contains a configured canary.

### D8. Error sanitization and scrubbing

- **Errors.** Fixed categories (spec) with a correlation identifier. The user message is `secret reference <config key> (provider <p>): <category> [id <cid>]`. Detail and the chained exception go to a server-side log with the same id. `secret unavailable` merges missing path, missing key, denial, and ambiguous multi-key so authors cannot probe.
- **Third-party errors.** `sanitize_exception(*, exc, config_key)` maps Pydantic `ValidationError` to `errors(include_input=False, include_url=False)`, and client, HTTP, and DB exceptions to a category plus key path. Ingest, storage, and vectordb catch sites use it. Job and node message writers call it as a backstop.
- **Registry and scrubber.** A per-run `SecretRegistry` (contextvar keyed by run id) stores each value with its percent-encoded, JSON-escaped, and base64 forms. A `logging.Filter` on the root handlers, the message writers, metadata and statistics serializers, lineage event construction, and the REST error handler all call `scrub(text)`. If scrubbing fails the text is replaced by a fixed placeholder. Short secrets are registered too; over-redaction is accepted.
- **Log rules.** No config dicts or adapter configs are logged. `%s` formatting only. Resolution logs carry no length or hash of the value.

The registry is defense in depth. The primary controls are D2 (where), D5 (type), D6 (scope), and D7 (data plane).

### D9. Lifetime, caches, files

Adapter caches (`_adapter_cache` and similar) are keyed by `sha256(provider + key path + value)` and cleared when the run ends. A client needing a credential file gets a `0600` file in a private temporary directory removed on release. Nothing is set in `os.environ`.

### D10. Vault client hardening

`HashiCorpVaultProvider`: no `response.text` or body logging at any level (status, request-path category, allowlisted headers only); `allow_redirects=False` for login and reads; non-loopback addresses must be `https`; `VAULT_TLS_SKIP_VERIFY` honored only for loopback; explicit `(connect, read)` timeouts. Registration refuses unsafe configuration and logs the reason server-side, after which references fail with `provider not registered`. Exceptions from `requests` are caught and re-raised as category-only errors so the Vault address does not leak.

### D11. Enrichment, validation, lineage

- **Enrichment.** `_resolve_dag_secrets` calls the resolver only for node types that connect during enrichment (`vectordb` today, declared by an operator capability flag). On failure the node's fetch returns the empty result with a WARNING. The failure state is kept in a local dict keyed by node, not in the config. The response is built from the request body.
- **Validation.** `FlowValidator` replaces the two ad-hoc placeholders with one sentinel that provider format checks treat as valid for secret-capable fields. The dead guard in `ingest_source.py` is removed. Messages name the key and not the value.
- **Lineage.** `derive_dataset_info_from_ingest` receives the declaration and uses a fixed placeholder for any component whose field holds a reference. Statistics keys are filtered by declaration.

### D12. Custom operator trust model

*Classes.* **Platform** (in-tree), **deployer-installed** (pip package, `DOCPIPE_CUSTOM_OPERATORS`, trusted as platform code), **untrusted** (`POST /api/v1/custom_operators` upload, S3 source). The loader tags each operator with its class from the source type.

*Options considered for untrusted code:*

| Option | Result |
|---|---|
| A. Keep in-process, add AST deny-lists | Rejected. Deny-lists are bypassable (`__import__`, `getattr`, `importlib`), and an in-process module can reach `sys.modules`, the provider dict, and thread-shared state. |
| B. Separate worker process per node | Chosen as the supported mode (`isolation=process`). The worker has no provider, no token, a scrubbed environment (allowlist), receives the node's own config and the table over a pipe (Arrow IPC), and returns the table and metadata. |
| C. Disable untrusted operators when a provider is registered | Chosen as the default (`isolation=disabled`) so the safe state needs no setup. |
| D. Container or seccomp sandbox | Out of scope; documented as deployment hardening on top of B. |

*Rules.*
1. With a provider registered and no setting, untrusted operators fail validation with `not permitted`. With no provider, behavior is unchanged.
2. The API process never imports untrusted code. Upload and update use AST analysis (`ASTOperatorValidator`, extended to read `short_name`, `category`, and declared secret fields as literals). `_refresh_operator_factories` registers a lightweight descriptor from AST data and defers import to the worker. `exec_module` stays only for platform and deployer-installed sources.
3. The worker receives only the node's own config. References in declared fields resolve only if they match `custom_operator_allowed_paths`, in the parent process, and travel as values over the pipe to that worker alone. The table passed to the worker has had credentials stripped by D7, and `global_config` is replaced by an allowlisted subset (`doc_column`, `job_id`).
4. `/api/v1/custom_operators` create, update, delete require `get_current_user`, return 403 if authentication is disabled while a provider is registered, and write an audit record with the script digest.
5. Documentation states the limit: isolation reduces what a hostile author can reach, it does not make upload safe to expose to untrusted users. Treat upload as an administrator capability.

*Risk:* process isolation costs throughput (table serialization per node). It applies only to untrusted operators and is opt-in when Vault is present.

### D13. Orchestrator parameters

Task parameters in the Prefect engine are audited. The node config passed to tasks is the unresolved config (references); resolution happens inside the task, in the worker. A test inspects the parameters Prefect would record.

### D14. Conformance suite

A parametrized suite iterates every `(operator, secret_field)` from the declarations, injects a unique canary through a fake provider, drives the operator through success, resolution failure, adapter-validation failure, client failure, and mid-run failure (fake clients that raise exceptions embedding the canary), and scans all sinks with the encoded variants. A second suite runs a hostile custom operator in each isolation mode. A final test fails if a declared field lacks a suite entry.

## Risks / Trade-offs

- **[Scale and review cost]** About 34 requirements across 25 adapters. → Staged delivery (stages A to E), each independently useful and shippable, with the spec archived once at the end.
- **[Breaking: metadata no longer carries credentials]** The ACL operator and external sidecar readers may depend on it. → ACL gets its own credentials (D7); the proposal flags it; docs describe the migration.
- **[Breaking: undeclared fields rejected]** Flows with a reference in an undeclared field fail. → The error names the key and the docs list declared fields.
- **[`SecretValue` wrapper vs. client libraries]** Some libraries type-check for `str`. → `reveal()` at the client boundary only; a test constructs each real client with a revealed value.
- **[Process isolation performance]** → Applies to untrusted custom operators only; documented.
- **[Scrubber false positives]** Short secrets can over-redact logs. → Accepted by the spec; the mask is a fixed token.
- **[Dead-code removal in ingest validation]** → Baseline tests in stage A lock current behavior first.
- **[Prefect parameters]** Not verified. → Task in stage D; if parameters hold resolved values, fix in the same task.
- **[Auth on custom operator routes]** No dependency was found on the router. → Task D.1 confirms with a test before the change.

## Migration Plan

- **Stage A** (leaks that exist today, no config needed): data-plane fix, error sanitization, Vault client hardening, grammar fail-closed.
- **Stage B**: resolver, `SecretValue` and `resolve_env_var` interplay, declarations, path policy, executor scope, validation, enrichment, lineage.
- **Stage C**: scrubber, registry, audit trail, log filter.
- **Stage D**: custom operator isolation, authorization, Prefect audit.
- **Stage E**: conformance suite, docs, archive.

Stages A and D carry BREAKING items and need release notes (maintainers handle `CHANGELOG.md`). Rollback per stage is a revert; no stored data changes. Documents already written with credentials in metadata remain; the docs tell operators to rotate those credentials and purge old outputs.

## Open Questions

- **Single change or staged pull requests?** The design supports both. Recommendation: stage A as its own pull request because it removes active leaks, then B to E.
- **Default for `secrets.vault.allowed_paths` when unset.** The spec allows with a WARNING for compatibility. A deny default is safer but breaks existing flows. Needs a maintainer decision.
- **Isolation mechanism for `process` mode.** `multiprocessing` with `spawn` and an Arrow IPC pipe is the proposed baseline. Confirm that worker start-up cost is acceptable for flows with many custom nodes.
- **Is upload administrator-only?** There is no role concept today. The spec requires authentication and audit; a role check is left for a follow-up unless maintainers want it in this change.
