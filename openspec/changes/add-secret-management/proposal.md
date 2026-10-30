# Proposal

## Why

Flows can already carry `vault://provider/path#key` references in operator config, and the Python executor resolves them before an operator is built. The behavior is accidental, untested, and unsafe in ways that apply to every credential-bearing operator, not only `vectordb`:

- **Resolved secrets leak.** The executor resolves every reference in the merged config, including `global_config`, so an ingest credential is re-resolved by every downstream node. Pydantic validation errors echo `input_value=<secret>` into logs and run metadata. `resolve_env_var` re-interprets resolved secrets, so a secret `$ecret_Value` raises an error that discloses the secret minus its first character.
- **Secrets are persisted.** SharePoint and OneDrive ingest write `client_id`, `client_secret`, and `tenant_id` into document metadata, which is serialized into the table, parquet files, and storage sidecars. The ACL operator reads the secret back from that metadata.
- **Failures fall through.** A malformed `vault://` string is silently used as a literal credential. Flow enrichment swallows Vault failures at DEBUG and connects with the literal reference.
- **Vault client is not hardened.** Error messages and DEBUG logs include `response.text`. The default address is plaintext HTTP, TLS verification can be disabled for any host, and redirects are not controlled.
- **Nothing limits what a reference can read.** Any field accepts a reference and any Vault path the platform can read is reachable, so a flow author can place a secret into an index name, a path, or a prefix and read it back.
- **Untrusted code runs beside secrets.** Custom operators uploaded through `POST /api/v1/custom_operators` are arbitrary Python. They are executed in the API or worker process (module-level code runs at discovery time), where they can call the secret provider, read the Vault token, the environment, and other nodes' resolved configuration. The upload routes have no authorization dependency of their own.

Nothing detects a regression. The goal is a platform-wide, layered guarantee (prevent, contain, scrub, verify, fail closed) that no resolved Vault value reaches a user-visible sink, with canary tests that turn any leak into a build failure.

## What Changes

- **Backend: one contract for all operators.** New capability `backend/secret-management` defines a strict reference grammar, secret-capable field declarations per operator, a deployment path allowlist, one shared resolution component, fail-closed behavior, minimal resolution scope (a reference is resolved only for the node that owns it), an opaque secret type, and verbatim use of resolved values.
- **Backend: no secrets in the data plane.** Source adapters stop copying credentials into document metadata; the ACL operator reads credentials from its own secret-capable configuration.
- **Backend: no disclosure.** Fixed error categories with correlation identifiers, a uniform `secret unavailable` category, sanitized third-party errors (Pydantic `include_input=False`), a per-run secret registry with scrubbing at every outbound boundary, logging rules, lineage placeholders, and an audit trail.
- **Backend: Vault client hardening.** No response bodies in errors or logs, no redirects on credentialed requests, TLS required for non-loopback addresses, bounded timeouts.
- **Backend: enrichment and validation.** Enrichment never connects with an unresolved reference and resolves only connecting nodes. Validation accepts references without contacting Vault and reports malformed, undeclared, and out-of-policy references without echoing them.
- **Backend: untrusted custom operators.** Uploaded and object-store custom operators are never imported in a process that holds secrets. A new `custom_operators.isolation` setting (`process` or `disabled`) applies, defaulting to `disabled` when a secret provider is registered. Discovery and upload use static analysis only. Custom operators get only their own node configuration and, by default, no Vault access. Create, update, and delete routes require authentication and are audited.
- **Backend: coverage and conformance.** Every operator in the inventory (ingest, storage, `vectordb`, LLM and service operators, ACL) declares its fields. A canary conformance suite, including a hostile custom operator, makes leaks a test failure.
- **Docs:** a secrets guide, updates to the ingest, storage, and `vectordb` operator READMEs and `docs/reference/OPERATORS.md`, a sample flow, and a statement of the custom-operator trust classes.

**BREAKING:**
- Source adapters no longer put `client_id`, `client_secret`, or `tenant_id` into document metadata. Anything that reads them from metadata (the ACL operator, external readers of the sidecar) must use the operator's own credential configuration.
- A `vault://` reference in a field not declared secret-capable is rejected by validation and execution. It used to be passed through.
- A malformed `vault://` value is rejected instead of used as a literal.
- A secret that is not valid for a scalar field (JSON-looking value in `password`) fails instead of being parsed.
- `VAULT_ADDR` with plaintext HTTP on a non-loopback address, or `VAULT_TLS_SKIP_VERIFY` on a non-loopback address, causes the Vault provider not to register.
- When a secret provider is registered, untrusted custom operators are disabled unless `custom_operators.isolation=process` is configured, and custom operator management requires authentication.
- Flows with no `vault://` values and no untrusted custom operator behave as before.

**Delivery.** This is a large change. The tasks are grouped in stages A to E that can ship as separate pull requests in order (stage A first, as it closes the leaks that exist today), but the capability spec is archived once, after the last stage. See the open questions in `design.md`.

**Out of scope:**
- Weaviate and any provider not on `main`. A future provider inherits the contract through its declaration.
- Frontend changes. The Vault input component already exists (`frontend/common/vault-input`).
- Secrets other than `vault://` references in flow definitions: platform credentials (job store, LDAP, OAuth, JWT) keep their own configuration.
- Secret rotation and caching policy beyond the lifetime rules in the spec.
- Building a new sandbox technology. Process isolation uses a separate worker process; stronger sandboxing (containers, seccomp) is a deployment concern recorded in the docs.
- Protection against deployer-installed packages, which run with platform trust.

## Capabilities

### New Capabilities

- `backend/secret-management`: how `vault://` references in flow definitions are declared, validated, resolved, held, scrubbed, and kept out of every sink, for every operator and execution path, including the trust model for custom operators.

### Modified Capabilities

- `backend/custom-operators-api`: adds an authorization and audit requirement for create, update, and delete. The existing requirements are unchanged, so the delta uses ADDED only.

## Impact

- **Secrets integration:** `integrations/secrets/secret_provider.py` (grammar, errors, shared resolver, opaque type), `hashicorp_vault.py` (bodies, redirects, TLS, timeouts), `vault_initializer.py` (registration rules).
- **Orchestration:** `PythonOperatorExecutor._resolve_operator_params` (scoped resolution), `abstract_orchestrator._populate_ingest_source_config`, `flow_validator.py`, `prefect_engine.py` (task parameters), job and node message storage.
- **Assets:** `FlowEnrichmentService._resolve_dag_secrets`.
- **Operators:** `operator_utils.resolve_env_var`, metadata declarations for every operator in the inventory, ingest adapters and configs (S3, SharePoint, OneDrive, Google Drive, Box, Dropbox, web), storage destination adapters, `vectordb` adapters and metadata fetchers, `ACLOperator`, LLM and service operators.
- **Lineage:** `lineage/dataset_naming.py`, `lineage/utils.py`.
- **Logging:** a shared logging filter and message sanitizer in `utils/infrastructure/logging.py`.
- **Custom operators:** `core/custom_operators/{validation,service}.py`, `core/orchestration/operator_loader/**`, a new isolated worker entry point, `api/routes/custom_operators.py`, `api/main.py` catalog setup, `constants.py`.
- **REST routes:** no route added. Behavior changes: validation messages, enrichment results, custom operator routes (401/403).
- **Configuration:** new `secrets.vault.allowed_paths`, `secrets.vault.custom_operator_allowed_paths`, `custom_operators.isolation` in `docling-pipelines-config.yaml`.
- **Dependencies:** none expected.
- **Tests:** new canary conformance suite and characterization tests under `tests/unit/` and `tests/integration/`.
- **Docs:** secrets guide, operator READMEs, `docs/reference/OPERATORS.md`. `CHANGELOG.md` is not touched.
