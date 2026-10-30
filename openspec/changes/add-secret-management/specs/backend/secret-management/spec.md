# Spec Delta

## Purpose

Defines the platform-wide contract for credentials supplied as `vault://<provider>/<path>[#<key>]` references in flow definitions: where a reference may appear, when and how it is resolved, how the resolved value is held, and the places it must never reach. The contract applies to every operator and adapter (built-in or custom), in every execution path (CLI, REST job runs, `DocpipeFlowManager`, Prefect), and to flow validation and flow enrichment. Vector database providers, ingest sources, storage destinations, and LLM-backed operators are instances of this one contract, not special cases.

**Threat model.** The contract exists to stop seven classes of failure:

- **T1 Disclosure.** A resolved value appears in logs, exception text, REST responses, run metadata, job messages, lineage events, validation results, or orchestrator task parameters.
- **T2 Persistence.** A resolved value is written into the data plane: table columns, document metadata, parquet files, storage sidecar files, vector index documents, or long-lived caches.
- **T3 Exfiltration by a flow author.** A reference is placed in a field that is not a credential (an index name, a path, a prefix, a filter) or points at a Vault path the author should not read, so that the secret is written somewhere the author can read it.
- **T4 Confusion.** A resolved value is re-interpreted (environment expansion, JSON parsing, trimming), or a failed resolution silently falls back to the literal reference string.
- **T5 Vault-side leakage.** Vault response bodies, the platform's own Vault credentials or token, or Vault traffic are exposed through error text, logs, redirects, or plaintext transport.
- **T6 Regression.** A new operator, provider, or log statement introduces a leak that nothing detects.
- **T7 Untrusted code.** A custom operator uploaded through the API (or loaded from an object-store source) is arbitrary Python. Run in the platform process, it can call the secret provider directly, read the Vault token or AppRole identifiers, read the process environment, read other nodes' resolved configuration and upstream table data, and send any of it out through the network, logs, metadata, or table output. Declarations and scrubbing do not stop this; only isolation, or refusing to run such code next to secrets, does.

**Principles.** Requirements are layered so that no single defect discloses a secret.

1. *Prevent*: references are accepted only where declared, and only for permitted secrets.
2. *Contain*: a resolved value lives in an opaque type, in the smallest scope, for the shortest time.
3. *Scrub*: every outbound boundary removes known secret values even if upstream code forgot to.
4. *Verify*: canary-based conformance tests make a leak a build failure.
5. *Fail closed*: when resolution, scrubbing, or policy evaluation cannot complete, the node fails and nothing is attempted.

**Definitions.**

- *Secret value*: any value obtained by resolving a reference, whatever field held it, and any string derived from it (percent-encoded, JSON-escaped, base64, or concatenated into a token, connection string, or header, for example `username:password`).
- *User-visible sink*: anything a flow author, API caller, or downstream system can read: REST responses, flow validation results, enrichment responses, run and node metadata, job and node messages, job statistics, lineage events, orchestrator-visible task parameters, document metadata, table columns, parquet output, storage sidecar and destination files, and vector index contents.
- *Server-side sink*: logs, traces, and diagnostics readable only by platform operators.
- *Untrusted custom operator*: an operator with `owner="custom"` whose code was uploaded through `POST /api/v1/custom_operators` or loaded from an object-store source. An operator installed by the deployer as a Python package or through `DOCPIPE_CUSTOM_OPERATORS` is *deployer-installed* and has the same trust as platform code, but is still subject to the declaration rules.
- *Secret-capable field*: a configuration field declared in an operator's metadata as allowed to hold a reference.

**Secret-capable field inventory.** The declarations cover at least the following fields. The requirement "Coverage of credential-bearing operators" makes this table binding.

| Operator group | Secret-capable fields |
|---|---|
| `ingest_source`: `s3`, `ibm_cos` | `access_key`, `secret_key`, `endpoint_url`, `bucket`, `region` |
| `ingest_source`: `sharepoint` | `client_id`, `client_secret`, `tenant_id`, `document_library_id` |
| `ingest_source`: `onedrive` | `client_id`, `client_secret`, `tenant_id`, `drive_id` |
| `ingest_source`: `google_drive` | `service_account_json`, `service_account_json_path`, `credentials_json`, `credentials_path`, `token_path` |
| `ingest_source`: `box_driver` | `credentials_json`, `credentials_path`, `credentials_json_path` |
| `ingest_source`: `dropbox` | `access_token`, `refresh_token`, `app_key`, `app_secret` |
| `ingest_source`: `web` and any other adapter | every credential field the adapter defines |
| Storage output operator, all destinations | the `credentials` object and each credential field of `provider_config`: S3 and IBM COS `access_key`, `secret_key`, `endpoint_url`; SharePoint `client_id`, `client_secret`, `tenant_id`; Box `credentials_json_path`; Google Drive service account and OAuth credentials | <!-- pragma: allowlist secret -->
| `vectordb`: OpenSearch | `host`, `username`, `password`, `jwt_token`, `aws_region`, and any AWS credential field |
| `vectordb`: Milvus | `host`, `uri`, `token`, `username`, `password`, `database` |
| `embeddings`, `document_classifier`, `pii_and_hap`, `ml_enrichment`, `extract` (Docling Serve and LLM entity extraction), `chunker` (remote service) | `api_key`, `api_token`, and `api_base` or `url` where a credential may be embedded |
| `acl_operator` | its credential object (`client_id`, `client_secret`, `tenant_id`) |

## ADDED Requirements

### Requirement: Strict reference grammar
A value SHALL be treated as a Vault reference only when the entire string is exactly one `vault://<provider>/<path>[#<key>]`, with a non-empty provider, a non-empty path, and a non-empty key when `#` is present. A string containing `vault://` that is not exactly one valid reference MUST be rejected as malformed and MUST NOT be used as a literal credential.

#### Scenario: Valid reference
- **WHEN** a field value is `vault://hashicorp/opensearch/credentials#password`
- **THEN** it is parsed into provider `hashicorp`, path `opensearch/credentials`, key `password`

#### Scenario: Reference without a key
- **WHEN** a field value is `vault://hashicorp/opensearch/token` and the secret has exactly one key
- **THEN** it is parsed with no key and resolves to that single value

#### Scenario: Truncated reference is rejected
- **WHEN** a field value is `vault://` or `vault://hashicorp`
- **THEN** the value is rejected as malformed and is never passed on as a literal credential

### Requirement: Reference syntax limits
A reference MUST NOT contain whitespace, control characters, `.` or `..` path segments, or empty path segments, MUST NOT exceed 1024 characters, and MUST NOT be embedded in a larger string. A field SHALL hold at most one reference.

#### Scenario: Embedded reference is rejected
- **WHEN** a field value is `Bearer vault://hashicorp/api#token` or `https://host/?k=vault://hashicorp/api#token`
- **THEN** the value is rejected as malformed, because a reference must be the whole value

#### Scenario: Path traversal is rejected
- **WHEN** a field value is `vault://hashicorp/team-a/../team-b/db#password`
- **THEN** the value is rejected as malformed and no request is made to the provider

### Requirement: References accepted only in secret-capable fields
Every operator SHALL declare in its metadata which configuration fields are secret-capable. A reference in any other field SHALL be rejected by validation and by execution with an error naming the config key. An operator that declares nothing accepts no references, and a custom operator MUST declare its fields to receive resolved values.

#### Scenario: Credential field accepts a reference
- **WHEN** an S3 ingest node sets `provider_config.secret_key` to a reference
- **THEN** validation accepts it and execution resolves it

#### Scenario: Undeclared operator
- **WHEN** a custom operator declares no secret-capable fields and its config contains a reference
- **THEN** validation and execution reject it, and the operator is constructed with no resolved value

#### Scenario: Sensitive schema flag is a floor
- **WHEN** an operator's schema marks a field `sensitive`
- **THEN** that field is secret-capable without a separate declaration

### Requirement: Scope of secret-capable declarations
A declaration SHALL include every credential field and every connection-identity field (host, URI, endpoint, bucket, tenant, drive identifier) that may reasonably be kept in Vault. It MUST NOT include fields whose value names or locates something written at an external system, such as index or collection names, destination paths, key prefixes, filters, and file names.

#### Scenario: Naming field rejects a reference
- **WHEN** a `vectordb` node sets `index_name`, or a storage node sets a destination path or `prefix`, to a reference
- **THEN** validation reports an error naming the config key, execution fails before any connection, and no Vault request is made

#### Scenario: Connection identity accepts a reference
- **WHEN** a Milvus node sets `uri` to a reference
- **THEN** validation accepts it and execution resolves it

### Requirement: Coverage of credential-bearing operators
The secret-capable declarations SHALL cover at least the fields in the inventory table in the Purpose section. A change that adds a credential-carrying field MUST add it to its operator's declaration in the same change.

#### Scenario: Every listed field resolves
- **WHEN** each listed field of an operator is supplied as a reference that resolves
- **THEN** the adapter's client constructor receives the resolved value for that field

#### Scenario: Operator outside the inventory
- **WHEN** an operator not in the inventory (for example `doc_quality` or `merge`) receives a reference
- **THEN** it is rejected under the secret-capable-field requirement

#### Scenario: Inventory is enforced by a test
- **WHEN** the test suite runs
- **THEN** a test enumerates every registered operator and fails if a field named like a credential (`password`, `*_key`, `*_secret`, `*_token`, `credentials*`) is neither declared secret-capable nor explicitly marked as not accepting references

### Requirement: Deployment policy for providers and paths
The platform SHALL support a deployment policy `secrets.vault.allowed_paths`, a list of provider-qualified glob patterns such as `hashicorp:opensearch/*`. When configured, a reference matching no pattern SHALL be rejected as not permitted by validation and by execution, without a Vault request. When not configured, the platform SHALL log one WARNING at startup.

#### Scenario: Path outside policy
- **WHEN** the policy is `hashicorp:opensearch/*` and a flow references `vault://hashicorp/prod/payments#key`
- **THEN** validation reports an error naming the config key, execution fails before any connection, and Vault is not contacted

#### Scenario: Path inside policy
- **WHEN** the policy is `hashicorp:opensearch/*` and a flow references `vault://hashicorp/opensearch/credentials#password`
- **THEN** the reference is permitted and resolved

#### Scenario: Policy not configured
- **WHEN** the platform starts without `secrets.vault.allowed_paths`
- **THEN** exactly one WARNING is logged stating that any Vault path readable by the platform can be referenced, and existing flows behave as before

### Requirement: Mixed credential sources
Within one operator configuration, `vault://` references, `$ENV_VAR` or `${ENV_VAR}` references, and literal values SHALL be supported together, with each field resolved independently by its own form. Environment resolution SHALL be applied only to values that were present in the configuration, never to the output of a secret provider.

#### Scenario: Vault password with environment username
- **WHEN** `username` is `${OPENSEARCH_USER}` and `password` is a reference
- **THEN** the username comes from the environment and the password from Vault

#### Scenario: Flow without references
- **WHEN** an operator's configuration contains no `vault://` value
- **THEN** behavior is identical to behavior before this capability and no secret-provider call is made on that operator's behalf

### Requirement: Single resolution component
Resolution SHALL happen in one shared component used by every execution path and by flow enrichment. Operators and adapters MUST NOT call a secret provider themselves, and resolution SHALL complete for every reference in a node's configuration before the node opens any connection, reads any source, or writes any data.

#### Scenario: Direct construction
- **WHEN** an operator is constructed directly, without the Python executor, with a reference in a secret-capable field
- **THEN** the reference is resolved by the shared component before any client is created

#### Scenario: No second resolution
- **WHEN** the executor has already resolved a node's configuration
- **THEN** the shared component finds no reference and makes no further provider request

### Requirement: Resolution fails closed
If any reference cannot be resolved, the node SHALL fail with no I/O performed. A failed or unavailable provider MUST NOT cause a fallback to the literal reference string, an environment variable, a default, or a previously resolved value.

#### Scenario: One failure aborts the node
- **WHEN** a node has three references and the second cannot be resolved
- **THEN** the node fails, no client is created, no data is read or written, and no further reference is resolved

#### Scenario: No fallback on provider failure
- **WHEN** Vault is unreachable and the same field name is also set in the environment
- **THEN** the node fails and the environment value is not used

### Requirement: Minimal resolution scope
A reference SHALL be resolved only for the node whose configuration owns it, when that node is constructed. A resolved value MUST NOT be merged into configuration shared across nodes (`global_config`, batch configuration). Shared configuration SHALL carry the original reference or nothing, and a downstream node needing a source credential SHALL declare its own secret-capable field.

#### Scenario: Downstream node does not resolve upstream references
- **WHEN** an ingest node uses references and a downstream `vectordb` node has only literal configuration
- **THEN** no Vault request is made while constructing the `vectordb` node, and a Vault outage cannot fail it

#### Scenario: On-demand source fetch
- **WHEN** the extract step fetches file content through the ingest source's adapter
- **THEN** credentials come from the shared component for the ingest node's own references, scoped to that fetch, and not from shared configuration

#### Scenario: Enrichment resolves only connecting nodes
- **WHEN** a flow is enriched
- **THEN** references are resolved only for node types that open a live connection during enrichment, and not for nodes such as ingest

### Requirement: Opaque secret type
A resolved value SHALL be held in an opaque secret type whose `repr`, `str`, `format`, JSON, pickle, and copy outputs are masked, exposing the real value only through one explicit accessor used at the client boundary. A string derived from a secret (a `user:password` token, a URL with credentials, an `Authorization` header) SHALL also be built through that type.

#### Scenario: Accidental formatting
- **WHEN** code logs or formats a configuration dict, an adapter object, or an exception that holds a secret value
- **THEN** the secret renders as a fixed mask

#### Scenario: Derived value
- **WHEN** the Milvus adapter builds a token from `username` and `password`
- **THEN** the combined string is itself masked and scrubbed

### Requirement: Verbatim use of resolved values
A resolved value MUST be used exactly as stored: not trimmed, case-changed, expanded, treated as an environment variable name, parsed as JSON, or converted to another type. The only exception is a field declared as structured (such as `credentials_json`), which MAY receive a parsed object when the stored value is valid JSON.

#### Scenario: Secret that resembles an environment variable
- **WHEN** a Vault secret is `$ecret_Value`, `${HOME}`, or `MY_PASSWORD`, and `MY_PASSWORD` is set in the environment to a different value
- **THEN** the connection uses the exact stored string and no environment lookup occurs for it

#### Scenario: Secret that resembles JSON in a scalar field
- **WHEN** the stored value of a scalar field such as `password` or `token` is `{"a":1}` or `[1]`
- **THEN** the node fails with category `value must be a string`, and no client is created

### Requirement: Secrets never enter the data plane
A secret value MUST NOT be written to any table column, document metadata, parquet or intermediate file, storage sidecar or destination file, vector index document, lineage event, or node statistic. Source adapters MUST NOT copy credential fields into document metadata. An operator needing source credentials SHALL obtain them from its own configuration through the shared component, not from data produced by another operator.

#### Scenario: SharePoint and OneDrive ingest metadata
- **WHEN** a SharePoint or OneDrive ingest node processes a document
- **THEN** the document metadata contains no `client_id`, `client_secret`, or `tenant_id`, whether they came from a reference, an environment variable, or a literal

#### Scenario: Storage sidecar
- **WHEN** a storage node writes a comprehensive export with a metadata sidecar
- **THEN** the sidecar and the destination file contain none of the secret values used by any node in the flow

#### Scenario: ACL operator
- **WHEN** the ACL operator needs source credentials
- **THEN** it reads them from its own secret-capable credential object, and a flow whose ingest metadata lacks credentials still works

#### Scenario: Intermediate output scan
- **WHEN** a flow with canary secrets completes, fails, or is cancelled
- **THEN** a byte scan of every intermediate and final file written by the run finds no canary value

### Requirement: Fail-fast with fixed error categories
If any reference cannot be resolved, the node SHALL fail before any I/O with a fixed message naming the config key path, the provider name, and one category from: `provider not registered`, `secret unavailable`, `vault unreachable`, `malformed reference`, `not permitted`, `value must be a string`.

#### Scenario: Provider not registered
- **WHEN** a reference names a provider that was not registered at startup
- **THEN** the node fails with category `provider not registered` naming the config key and provider, and no client is created

#### Scenario: Vault unreachable
- **WHEN** Vault cannot be reached
- **THEN** the error states `vault unreachable`, and contains neither the Vault address nor the transport exception text

#### Scenario: Malformed reference
- **WHEN** a value starting with `vault://` fails the grammar
- **THEN** the error names the config key and the expected format, and does not echo the value

### Requirement: Non-echoing error content
The user-visible error MUST NOT contain the secret value, reference text beyond provider and config key path, Vault paths or key names, a Vault response body, the platform's Vault credentials or token, or underlying exception text. The detail and chained exception SHALL be written to a server-side log, and a correlation identifier SHALL appear in both the log entry and the message.

#### Scenario: Correlation
- **WHEN** a resolution fails
- **THEN** the same correlation identifier appears in the user-visible message and in the server-side log entry that holds the detail

#### Scenario: Chained exception stays server-side
- **WHEN** the provider raised an exception whose text names the Vault path
- **THEN** that text appears only in the server-side log

### Requirement: Uniform secret-unavailable category
The category `secret unavailable` SHALL cover a missing path, a missing key, a permission denial, and an ambiguous multi-key secret, so that a flow author cannot probe which Vault paths exist.

#### Scenario: Missing key, missing path, and denial are indistinguishable
- **WHEN** references target a missing key, a missing path, and a path the platform is denied
- **THEN** the user-visible error is identical in all three cases, and the server-side log distinguishes them

### Requirement: Enrichment never connects with an unresolved reference
During flow enrichment, a connecting node (such as `vectordb`) with a reference that cannot be resolved SHALL return its empty result and log a WARNING naming the config key and provider. An unresolved reference MUST NOT be passed to any adapter, client, or fetcher, no connection SHALL be opened for it, and other nodes SHALL still be enriched.

#### Scenario: Vault failure during enrichment
- **WHEN** a Milvus node's `token` is a reference and Vault is unreachable
- **THEN** the node returns the empty five-key result, a WARNING names `token` and the provider, and no Milvus connection is attempted

#### Scenario: Other nodes unaffected
- **WHEN** one node cannot resolve its credentials
- **THEN** enrichment of the remaining nodes completes normally

#### Scenario: Successful resolution during enrichment
- **WHEN** every reference in the node resolves
- **THEN** enrichment connects with the resolved values and returns metadata as it does for literal credentials

### Requirement: Enrichment responses carry no resolved data
Enrichment responses SHALL be built from the original request body, never from the resolved in-memory configuration, and no internal marker or flag SHALL appear in the response.

#### Scenario: Response after successful resolution
- **WHEN** enrichment succeeds for a node with resolved credentials
- **THEN** the response contains the original reference text only where the request held it, and no resolved value

#### Scenario: No internal marker
- **WHEN** enrichment records that a node's resolution failed
- **THEN** the response contains no marker key

### Requirement: Validation accepts references without resolving them
Flow validation SHALL accept a reference in any secret-capable field, including fields that must be present or well-formed for the selected provider, without contacting Vault and without requiring the secret to exist.

#### Scenario: Required field supplied by reference
- **WHEN** a field required by the provider, such as Milvus `uri` or S3 `secret_key`, is a reference
- **THEN** validation reports no missing-field or format error for it and makes no Vault request

#### Scenario: Placeholder does not trigger format errors
- **WHEN** a reference is placed in a field with a format check, such as S3 `endpoint_url`, a filesystem path, or a web URL list
- **THEN** validation does not report a format error caused by the validation placeholder

### Requirement: Validation reports reference problems
Flow validation SHALL report as errors a malformed reference, a reference in a field that is not secret-capable, a reference outside the path policy, and an embedded reference. It SHALL report as a warning a reference to an unregistered provider. Messages SHALL name the config key and MUST NOT echo reference text beyond the provider.

#### Scenario: Malformed reference in validation
- **WHEN** a credential starts with `vault://` but is malformed
- **THEN** validation reports an error naming the config key without echoing the value

#### Scenario: Unregistered provider in validation
- **WHEN** a credential references an unregistered provider
- **THEN** validation reports a warning naming the config key and provider, and no Vault request is made

### Requirement: Third-party error text is sanitized
Every exception that can carry a secret value SHALL be sanitized before its text reaches a log, a node or job message, run metadata, or a REST response. Configuration-model validation errors SHALL be rendered without input values, and errors from client, HTTP, and database libraries SHALL be reduced to a fixed category and the config key path.

#### Scenario: Validation error on a resolved field
- **WHEN** an adapter configuration model rejects a resolved value, for example an S3 `endpoint_url` that lacks a scheme
- **THEN** the recorded reason names the config key and the constraint and does not contain the value

#### Scenario: Client connection failure
- **WHEN** a connection fails after credentials were resolved from Vault
- **THEN** the reported error and the run metadata do not contain the credential, a derived `user:password` string, or a URL carrying credentials

#### Scenario: Job-level message
- **WHEN** a node fails and the orchestrator stores the error as the job message
- **THEN** the stored message has passed through the sanitizer and contains no secret value

### Requirement: Per-run secret registry and scrubbing
The platform SHALL keep a per-run registry of secret values, with their percent-encoded, JSON-escaped, and base64 forms, and SHALL replace every registered value in outbound text with a fixed mask at: the logging pipeline (all handlers and levels), exception-to-message conversion, node and job message storage, run metadata and statistics serialization, lineage event construction, and REST response serialization.

#### Scenario: Forgotten log statement
- **WHEN** code logs a string containing a resolved password at DEBUG
- **THEN** the emitted record contains the mask and not the password

#### Scenario: Encoded form
- **WHEN** a client library error contains the percent-encoded form of a resolved password
- **THEN** the stored message contains the mask

### Requirement: Scrubber fails closed
A secret of any length SHALL be registered, accepting over-redaction of short values. If the scrubber raises, the outbound text MUST be replaced with a fixed placeholder rather than emitted unscrubbed. Registry entries SHALL exist only for the lifetime of the run that resolved them.

#### Scenario: Scrubber failure
- **WHEN** the scrubber raises while processing a log record
- **THEN** the record is emitted with a fixed placeholder message

#### Scenario: Registry lifetime
- **WHEN** a run ends
- **THEN** its registry entries are removed and no longer held in memory

### Requirement: Logging rules for secret-bearing code
Code that handles configuration containing references or secret values SHALL NOT log a configuration dict, an adapter configuration object, or request parameters at any level, and SHALL NOT use f-strings or `%r` in log calls that can involve them. Resolution logging SHALL record only operator and node name, config key paths, provider name, count, outcome, and correlation identifier. It SHALL NOT include any portion, length, or hash of a secret value.

#### Scenario: Successful resolution logged
- **WHEN** references resolve successfully
- **THEN** logs name the node, provider, and config key paths and nothing derived from the values

#### Scenario: Debug logging of configuration
- **WHEN** `DS_LOG_LEVEL=DEBUG` is set and a node with resolved credentials runs
- **THEN** no log record contains a secret value

### Requirement: Vault client never exposes responses or credentials
The Vault client SHALL never place a response body in an exception message or log record at any level, recording only the HTTP status, a request-path category, and allowlisted headers (request identifier, content type). It SHALL NOT log the login payload, AppRole identifiers, or Vault token, nor include its own address or transport exception text in user-visible errors.

#### Scenario: Error response body
- **WHEN** Vault returns a failing status with a body containing request details
- **THEN** neither the raised error nor any log record at any level contains the body

#### Scenario: Failed login
- **WHEN** AppRole login fails
- **THEN** no log record or error contains the role identifier, the secret identifier, or the response body

### Requirement: Vault client transport safety
The Vault client SHALL NOT follow redirects on any request carrying credentials or a token, SHALL require TLS for any non-loopback address, SHALL honor a TLS-verification opt-out only for a loopback address and otherwise refuse to register, and SHALL apply bounded timeouts to every request.

#### Scenario: Redirect
- **WHEN** Vault responds with a redirect to another host
- **THEN** the client does not follow it and the token is not sent to the other host

#### Scenario: Plaintext non-loopback address
- **WHEN** `VAULT_ADDR` is `http://vault.internal:8200`
- **THEN** the provider is not registered, and a server-side log states that TLS is required

#### Scenario: TLS opt-out on a remote address
- **WHEN** `VAULT_TLS_SKIP_VERIFY=true` and the address is not loopback
- **THEN** the provider is not registered

### Requirement: Bounded lifetime of secret values
Secret values SHALL be held only for the duration of the node's execution and released when its executor is released. Caches of clients, tokens, or loaders SHALL be keyed by a non-reversible digest, never by a string containing the secret, and cleared when the run ends.

#### Scenario: Cache key
- **WHEN** an adapter caches an authenticated client
- **THEN** its cache key contains a digest and no substring of the secret

#### Scenario: Run end
- **WHEN** a run ends, whether it succeeds or fails
- **THEN** cached clients built from its secrets are released

### Requirement: No secret persistence
Secrets MUST NOT be written to disk, set in process environment variables, or passed on command lines. Where a client library requires a credential file, it SHALL be created with owner-only permissions in a private temporary location and removed after use.

#### Scenario: Temporary credential file
- **WHEN** an adapter must write a credential file for a client library
- **THEN** the file is created with mode `0600` and is deleted when the client is released

#### Scenario: Process environment
- **WHEN** a secret is resolved
- **THEN** the process environment is unchanged

### Requirement: Distributed orchestration carries references only
Task parameters, cache keys, and persisted results of distributed orchestration MUST contain references only, never resolved values, and result persistence and caching MUST remain disabled for tasks that handle secrets.

#### Scenario: Orchestrator-visible parameters
- **WHEN** a flow runs under Prefect
- **THEN** the parameters recorded for tasks contain references or no credential data, and no resolved value

#### Scenario: Persistence disabled
- **WHEN** a Prefect task that handles configuration is defined
- **THEN** result persistence is off and its cache policy is disabled

### Requirement: Lineage and statistics carry no references or secrets
Lineage events, dataset names and namespaces, job statistics, and node statistics SHALL NOT contain a resolved secret value or reference text. When a dataset identity would be derived from a field holding a reference, the identity SHALL use a fixed placeholder for that component.

#### Scenario: S3 bucket from Vault
- **WHEN** an S3 ingest node's `bucket` is a reference
- **THEN** the lineage dataset uses a placeholder component and contains neither the reference nor the bucket name obtained from Vault

#### Scenario: Statistics keys
- **WHEN** operator metadata is converted to lineage statistics
- **THEN** secret-capable fields are excluded by declaration, not only by a fixed list of key names

### Requirement: Audit trail
Every resolution attempt SHALL emit one server-side audit record containing timestamp, job and job-run identifiers, node name, config key path, provider name, outcome category, and correlation identifier. The record MUST NOT contain a secret value or reference text beyond provider and config key path. Policy denials SHALL be recorded at WARNING.

#### Scenario: Successful resolution
- **WHEN** a reference resolves
- **THEN** one audit record with outcome `resolved` is emitted for that config key path

#### Scenario: Policy denial
- **WHEN** a reference is denied by the field or path policy
- **THEN** a WARNING audit record with outcome `not permitted` is emitted and no provider request is made

### Requirement: Canary conformance tests gate every secret-capable field
For every secret-capable field of every operator, the suite SHALL include a conformance test that supplies a unique canary secret through a fake provider, runs the operator through a success path and each failure path (resolution, adapter validation, client, mid-run), and asserts the canary and its encoded and derived forms are absent from every sink. A test SHALL fail if a secret-capable field has no conformance test.

#### Scenario: Hostile custom operator
- **WHEN** the suite runs a custom operator that reads `os.environ`, imports the secret provider, reads the Vault token, and inspects other nodes' configuration, in each isolation mode
- **THEN** it obtains no canary, no provider, no token, and no other node's configuration

#### Scenario: Sinks covered
- **WHEN** a conformance test runs
- **THEN** it inspects all captured log records at all levels, exception text and `repr`, node and job messages, run metadata, REST responses, lineage events, orchestrator task parameters, table columns, document metadata, and every file written

#### Scenario: New secret-capable field without a test
- **WHEN** a field is declared secret-capable and no conformance test covers it
- **THEN** the suite fails with a message naming the operator and field

#### Scenario: Leak introduced by a later change
- **WHEN** a change makes any adapter echo a credential into an exception or a log
- **THEN** the conformance test for that field fails

### Requirement: Secure defaults for new operators and providers
A new operator, adapter, or vector database provider SHALL inherit this contract without Vault-specific code: it declares its secret-capable fields and receives resolved, opaque values from the shared component. One that does not declare its fields MUST receive no resolved values. Custom operators loaded from external packages are subject to the same rule.

#### Scenario: New provider
- **WHEN** a new vector database provider is added and declares `token` as secret-capable
- **THEN** a reference in `token` resolves, fails closed, is masked, and is scrubbed without any provider-specific resolution code

#### Scenario: Provider that skips declaration
- **WHEN** an adapter omits the declaration
- **THEN** references in its configuration are rejected rather than passed through

### Requirement: Untrusted custom operators never share a process with secrets
An untrusted custom operator SHALL NOT be imported, constructed, or executed in a process that holds a registered secret provider, a Vault token, AppRole identifiers, or a per-run secret registry. Deployment setting `custom_operators.isolation` SHALL be `process` (separate worker, no provider, scrubbed environment) or `disabled`. When a secret provider is registered and no setting is given, the default is `disabled`.

#### Scenario: Default with Vault configured
- **WHEN** a Vault provider is registered and `custom_operators.isolation` is not set
- **THEN** a flow that contains an untrusted custom operator fails validation with category `not permitted` naming the node, and the operator is not loaded

#### Scenario: Process isolation
- **WHEN** `custom_operators.isolation` is `process`
- **THEN** the operator runs in a separate process whose environment, memory, and module state contain no provider, token, AppRole identifier, or other node's configuration

#### Scenario: No Vault configured
- **WHEN** no secret provider is registered
- **THEN** untrusted custom operators load and run as they do before this capability

### Requirement: Untrusted code is not executed outside isolation
Upload, update, validation, listing, and discovery of an untrusted custom operator SHALL rely on static analysis only and MUST NOT execute module-level code in the API or worker process. The operator's module SHALL be imported only inside its isolation boundary, and only when a flow node that uses it runs.

#### Scenario: Module-level code at upload
- **WHEN** an uploaded script runs `os.environ` access or a network call at import time
- **THEN** upload returns the validation result without that code having executed in the API process

#### Scenario: Catalog refresh
- **WHEN** the operator catalog is refreshed after create, update, or delete
- **THEN** no untrusted module is imported in the API process

### Requirement: Untrusted custom operators receive only their own declared values
An untrusted custom operator SHALL be constructed with its own node configuration only, not `global_config` or another node's configuration. A reference is resolved for it only in a field it declares as secret-capable and only when the path matches `secrets.vault.custom_operator_allowed_paths`, which is empty by default. Credentials MUST NOT be present in the table or metadata passed to it.

#### Scenario: Default deny
- **WHEN** an untrusted custom operator's declared field holds a reference and `secrets.vault.custom_operator_allowed_paths` is empty
- **THEN** validation and execution reject it with category `not permitted` and Vault is not contacted

#### Scenario: Allowed path
- **WHEN** the setting lists `hashicorp:custom-ops/team-a/*` and the node references `vault://hashicorp/custom-ops/team-a/svc#token`
- **THEN** the value is resolved and delivered as an opaque value to the isolated process only

#### Scenario: Shared configuration not delivered
- **WHEN** an ingest node with references precedes an untrusted custom operator
- **THEN** the custom operator's configuration, the table it receives, and its document metadata contain no value or reference from the ingest node's credentials

### Requirement: Platform and deployer-installed code limits are stated
This capability SHALL NOT claim protection against deployer-installed packages or platform code, which run with full trust. Documentation SHALL state that in-process Python cannot be made safe against a hostile author, and that the guarantees for untrusted custom operators are those of isolation or `disabled`.

#### Scenario: Documentation
- **WHEN** the operator documentation for secrets is read
- **THEN** it names the custom-operator trust classes and the isolation setting, and states that untrusted code is never run beside secrets

### Requirement: Platform credentials are out of scope
This contract SHALL apply to credentials written in flow definitions. Credentials used by the platform itself (job store connections, LDAP, OAuth and JWT settings, and the AppRole identifiers used to reach Vault) are governed by their own configuration, except that this contract's non-disclosure rules apply to the Vault AppRole identifiers and token.

#### Scenario: Platform database password
- **WHEN** a platform setting such as the Postgres password is configured through its environment variable
- **THEN** this capability does not alter how it is read or resolved
