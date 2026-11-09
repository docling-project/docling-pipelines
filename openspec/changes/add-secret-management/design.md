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
- **Custom operators.** `POST /api/v1/custom_operators` accepts a `.py` file. `ASTOperatorValidator` checks only the contract. `filesystem_adapter._load_module_from_file` calls `exec_module`, so module-level code runs inside the API or worker process on every catalog refresh (create, update, delete). `ENABLE_CUSTOM_OPERATORS_DEFAULT` is true. On `main`, none of the six `custom_operators_router` handlers (create, update, delete, list, get, `directory_tree`) declares an authentication dependency. PR #572 (`secure-custom-operator-defaults`) adds a router-level `get_current_user` dependency and changes the default to disabled; this change assumes it and does not repeat it. Operators run in-process with threads and no sandbox, so they can import `secret_provider`, read the Vault token and session, `os.environ`, and shared module state. `CustomOperatorService` logs only `Refreshed operator factory ...`, so there is no audit record today.
- **Prefect.** `persist_result=False` and `NO_CACHE` are set, and `_populate_ingest_source_config` passes the unresolved ingest `provider_config` to the batch subflow. The content of task parameters was not otherwise verified, so this is a verification task.

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

`secrets.vault.allowed_paths` is a list of `provider:glob[@operator.field]` entries in `docling-pipelines-config.yaml`. The optional `@operator.field` suffix (for example `hashicorp:opensearch/*@vectordb.password`) scopes an entry to one operator field. Custom operators use the separate, default-empty `secrets.vault.custom_operator_allowed_paths` (D12). Policy runs before any provider call, in validation as well as execution.

*Glob semantics.* Matching runs on the normalized parsed path (after the grammar in D3, so no traversal segments exist). The provider part is an exact, case-sensitive match. In the path part, `*` matches any characters within one segment and does not cross `/`, `**` matches across segments, and matching is case-sensitive. A pattern with no `**` therefore cannot match a deeper path than it spells out.

### D4b. Deny by default, and destination binding

*Default.* When a secret provider is registered and `secrets.vault.allowed_paths` is unset or empty, every reference is `not permitted`. Allowing everything is an explicit choice: `allowed_paths: ["*:**"]`. The platform logs one WARNING at startup when that explicit wildcard is configured, and one ERROR-level startup message naming the setting when a provider is registered and the policy is unset. This favors the secure state over compatibility, because the only flows affected already use `vault://`, and this change already rejects those flows in other cases (malformed references, undeclared fields, plaintext `VAULT_ADDR`, JSON in a scalar field). The release notes tell deployers to set the policy before upgrading.

*Destination binding.* A path allowlist does not stop a flow author from sending a permitted credential to a host they control, for example `endpoint_url=https://attacker.example` with `secret_key=vault://...`. Fields that choose where a credential is sent (`endpoint_url`, `host`, `uri`, `api_base`, `url`) are therefore bound as follows when any other field of the same node resolves from a provider:

1. The destination is itself a reference (resolved under the path policy), or
2. its host matches an entry in `secrets.vault.allowed_destinations` (a list of host globs, empty by default), or
3. it is unset and the adapter uses its fixed default endpoint.

Otherwise the node fails with category `not permitted` before any connection. The check runs on the parsed host of the literal value, in validation and in execution. Scoped path entries (`@operator.field`) add a second control: they limit which operator field may read a given Vault path.

### D5. `SecretValue` opaque type and verbatim use

`SecretValue` is a wrapper, not a `str` subclass, because a subclass is easy to format by accident and some client libraries copy it. It masks `__repr__`, `__str__`, `__format__`, `__reduce__`, `__copy__`, and JSON encoding, and exposes `reveal()` used only at client construction. Derived strings (`user:password`, `Authorization` headers) are built inside the client factory from `reveal()` and registered with the scrubber. `resolve_env_var` returns a `SecretValue` unchanged, so its `$` and upper-case heuristics never see it. For fields declared structured (`credentials_json`) the resolver parses once and wraps the parsed object.

`SecretValue` also fails loudly when it is coerced by accident: `__eq__` against a `str` returns `False`, `__iter__` and `__len__` raise, and `__hash__` is based on identity. A `"".join(...)` or an f-string in a client factory then fails in tests instead of embedding the mask.

*Trade-off:* a wrapper needs a `reveal()` call in every adapter. Most adapters build one client, so the change is small and reviewable. `reveal()` returns a `str` by design, and the registry (D8) holds raw values, so the guarantee is limited to the adapters' client-construction points. An AST-based check, run as a pre-commit hook and in CI, fails when `reveal()` (including `getattr(value, "reveal")` and re-exports) is called outside adapter modules. The same AST check enforces D2's rule that a credential-looking field is either declared or marked `no_references`.

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

Adapter caches (`_adapter_cache` and similar) are keyed by `HMAC-SHA256` over `provider + key path + value`, using a per-run random key that is never persisted, and are cleared when the run ends. An unsalted hash of a low-entropy secret can be brute-forced offline if a key is ever logged. The existing SharePoint and OneDrive loader caches use `sha256(client_secret)[:16]` and move to the HMAC key. Cache keys are never logged. A client needing a credential file gets a `0600` file in a private temporary directory removed on release. Nothing is set in `os.environ`.

An empty resolved value is treated as `secret unavailable` and is never registered with the scrubber, because replacing an empty string would corrupt every scrubbed line.

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
| B. Separate worker process | Chosen as the supported mode (`isolation=process`). The worker has no provider, no token, an allowlisted environment, no inherited file descriptors, receives the node's own config and the table over a pipe (Arrow IPC), and returns the table and metadata. One persistent worker per operator class per run is reused across batches, instead of one `spawn` per node. |
| C. Disable untrusted operators when a provider is registered | Chosen as the default (`isolation=disabled`) so the safe state needs no setup. |
| D. Container or seccomp sandbox | Out of scope; documented as deployment hardening on top of B. |

*What `process` isolation guarantees, and what it does not.* A worker started with `multiprocessing` `spawn` under the API's UID removes **in-memory and inherited state**: no secret provider, no Vault session or token held by the parent, no per-run registry, no other node's configuration, no inherited environment variables beyond an allowlist, and no inherited file descriptors. It does **not** stop code running under the same UID from reading `/proc/<ppid>/environ`, `~/.vault-token`, mounted Kubernetes service-account tokens, or configuration files holding the AppRole, from reaching the cloud metadata endpoint, or from opening outbound connections. Those need deployment controls: a distinct UID for the worker, a read-restricted token and config location, and egress restriction. The docs state these as deployment preconditions, and the normative hostile-operator test asserts only the in-memory and inherited guarantees.

*Secret hand-off across the process boundary.* `SecretValue` masks `__reduce__`, so it cannot be pickled to the worker, and it must not be. For each declared field of that node that resolved, the parent calls `reveal()`, sends the string as a UTF-8 JSON message (`{field path: value}`) over the private pipe with the Arrow IPC table, and registers the value with the scrubber. The worker rebuilds a `SecretValue` and calls `reveal()` only at its own client construction. The value goes to that one worker only, never in environment variables, command-line arguments, or files, and the pipe is closed when the worker is released.

*Rules.*
1. With a provider registered and no setting, untrusted operators fail validation with `not permitted`. With no provider, behavior is unchanged.
2. The API process never imports untrusted code. Upload and update use AST analysis (`ASTOperatorValidator`, extended to read `short_name`, `category`, and declared secret fields as literals). `_refresh_operator_factories` registers a lightweight descriptor from AST data and defers import to the worker. `exec_module` stays only for platform and deployer-installed sources.
3. The worker receives only the node's own config. References in declared fields resolve only if they match `custom_operator_allowed_paths`, in the parent process, and cross the boundary as described above. The table passed to the worker has had credentials stripped by D7, and `global_config` is replaced by an allowlisted subset (`doc_column`, `job_id`).
4. **Authentication.** Delivered by PR #572, which puts `get_current_user` on the router so all six routes, including the read routes and `directory_tree`, fail closed (401 without a valid token, 503 when `JWT_SECRET_KEY` is missing or too short). It also disables custom operators by default. This change relies on that and adds nothing to it. Whichever of the two changes is archived second must not re-add the requirement.
5. **Who may upload.** Create, update and delete additionally require the caller to be listed in `custom_operators.allowed_uploaders` (usernames) when a secret provider is registered. An empty list means nobody and the routes return 403. With no provider registered, any authenticated user may upload, as before. The reason is that with `isolation=process` an uploaded script runs on the worker host with network access, so it must not be open to every logged-in user. A role model is out of scope for this change.
6. **Audit.** Create, update and delete write one structured JSON record to a dedicated `docpipe.audit` logger that debug and scrub filters cannot suppress, with fields: timestamp, caller, `operator_id`, `short_name`, action, `script_sha256`, and `outcome` (`success` or `rejected`). Rejected attempts (403, validation failure) are recorded too. Retention is set by `audit.retention_days` and the logger's handler is configured by the deployer. The "Audit trail" requirement for secret resolution uses the same logger and field conventions.
7. Documentation states the limit: isolation reduces what a hostile author can reach, it does not make upload safe to expose to untrusted users. Treat upload as an administrator capability.

*Risk:* process isolation costs throughput. It applies only to untrusted operators and is opt-in when Vault is present. The cost is a gate, not an open question: p95 overhead for starting a worker plus a 1000-row Arrow round-trip must stay at or below 2 seconds, measured on the CI runner, and a persistent worker per operator class per run must keep the per-batch overhead below that. Measuring it is a blocking task in D.3, and the number can be revised in review.

### D13. Orchestrator parameters

The node config passed to Prefect tasks is the unresolved config (references); resolution happens inside the task, in the worker. A `SecretValue` MUST NOT appear as a task argument or flow parameter. On `main`, `persist_result=False` and `NO_CACHE` are already set, and `abstract_orchestrator._populate_ingest_source_config` already passes the unresolved ingest `provider_config` to the batch subflow in `global_config`, so Stage D's work is a verification: a test inspects the parameters Prefect would record. It becomes a fix only if a resolved value is found.

### D14. Conformance suite

A parametrized suite iterates every `(operator, secret_field)` from the declarations, injects a unique canary through a fake provider, drives the operator through success, resolution failure, adapter-validation failure, client failure, and mid-run failure (fake clients that raise exceptions embedding the canary), and scans all sinks with the encoded variants. A second suite runs a hostile custom operator in each isolation mode. A final test fails if a declared field lacks a suite entry.

## Risks / Trade-offs

- **[Scale and review cost]** About 34 requirements across 25 adapters. → Staged delivery (stages A to E), each independently useful and shippable, with the spec archived once at the end.
- **[Breaking: metadata no longer carries credentials]** The ACL operator and external sidecar readers may depend on it. → ACL gets its own credentials (D7); the proposal flags it; docs describe the migration.
- **[Breaking: undeclared fields rejected]** Flows with a reference in an undeclared field fail. → The error names the key and the docs list declared fields.
- **[`SecretValue` wrapper vs. client libraries]** Some libraries type-check for `str`. → `reveal()` at the client boundary only; a test constructs each real client with a revealed value.
- **[Process isolation performance]** → Applies to untrusted custom operators only; a persistent worker per operator class per run; a measured p95 gate in task D.3.
- **[Same-UID worker]** `process` isolation does not stop a same-UID worker from reading `/proc`, token files, or the network. → The claim is limited to in-memory and inherited state; distinct UID, restricted token location, and egress restriction are documented deployment preconditions (D12).
- **[Deny-by-default path policy]** Existing `vault://` flows fail until `secrets.vault.allowed_paths` is set. → Startup ERROR names the setting; release notes call it out; `["*:**"]` is an explicit opt-out (D4b).
- **[Dependence on PR #572]** The uploader allowlist and audit assume authenticated callers. → Stage D does not start before #572 is merged; if it is not, the auth requirement moves back into this change.
- **[Scrubber false positives]** Short secrets can over-redact logs. → Accepted by the spec; the mask is a fixed token.
- **[Dead-code removal in ingest validation]** → Baseline tests in stage A lock current behavior first.
- **[Prefect parameters]** `persist_result=False`, `NO_CACHE`, and unresolved `global_config` are already in place on `main`. → Task in stage D is a verification test; it becomes a fix only if a resolved value is found.

## Migration Plan

- **Stage A** (leaks that exist today): data-plane fix, error sanitization, Vault client hardening, grammar fail-closed, and the audit logger. Route authentication and the disabled-by-default setting come from PR #572, which closes the most serious open exposure on its own.
- **Stage B**: resolver, `SecretValue` and `resolve_env_var` interplay, declarations, path policy, executor scope, validation, enrichment, lineage.
- **Stage C**: scrubber, registry, audit trail, log filter.
- **Stage D**: custom operator isolation, uploader allowlist, Prefect parameter verification.
- **Stage E**: conformance suite, docs, archive.

Stages A, B, and D carry BREAKING items and need release notes (maintainers handle `CHANGELOG.md`). Rollback per stage is a revert; no stored data changes.

**Credentials already persisted.** Every deployment that has run a SharePoint or OneDrive ingest holds `client_id`, `client_secret`, and `tenant_id` in document metadata, and therefore in parquet files and storage sidecars. Stopping the write (D7) is necessary and not sufficient. Those credentials MUST be treated as disclosed to anyone with read access to the output store, and rotated. Stage A also ships a small utility, `scripts/find_persisted_credentials.py`, that scans parquet files and sidecar JSON under given paths for these keys and lists the affected files without printing values, so operators do not have to guess which outputs to purge or re-ingest. The docs describe rotation, purge, and re-ingest.

## Open Questions

- **Single change or staged pull requests?** The design supports both. Recommendation: stage A as its own pull request because it removes active leaks, then B to E.
- **Disclosure of the custom operator finding.** The Context section describes the unauthenticated upload path in detail while it is still unfixed. Maintainers decide whether to move that detail into a private security advisory and leave a short reference here.
- **Role model for upload.** This change uses a configured uploader allowlist (D12). A role model is a follow-up.

*Resolved in review:* default for `allowed_paths` is deny (D4b); route authentication moved to PR #572, agreed with its author (D12); the worker start-up cost is a measured gate (D12).
