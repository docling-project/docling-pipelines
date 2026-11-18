# HashiCorp Vault Integration

HashiCorp Vault enables secure credential resolution for Docling Pipelines without storing sensitive credentials in flow JSON files, source control, or database storage.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [URI Format and Patterns](#uri-format-and-patterns)
  - [URI syntax](#uri-syntax)
  - [Pattern A — individual field references](#pattern-a--individual-field-references)
  - [Pattern B — one reference per key](#pattern-b--one-reference-per-key)
- [Supported Operators and Fields](#supported-operators-and-fields)
- [Configuration](#configuration)
  - [Configuration file (`docling-pipelines-config.yaml`)](#configuration-file-docling-pipelines-configyaml)
  - [Authentication methods](#authentication-methods)
  - [Environment variables](#environment-variables)
- [Web UI and Properties Panel Usage](#web-ui-and-properties-panel-usage)
- [Validation and Masking Lifecycle](#validation-and-masking-lifecycle)
- [Testing Guide](#testing-guide)
- [Troubleshooting](#troubleshooting)

---

## Overview

In standard flow execution, operators often require sensitive configuration parameters such as database passwords, API tokens, and cloud storage access keys. Hardcoding these credentials inside flow definitions presents security risks.

The Vault integration replaces cleartext credentials in flow definitions with immutable `vault://` URIs. When a pipeline runs:
1. Flow JSON stores only reference pointers (e.g., `vault://hashicorp/docpipe/embeddings#api_key`).
2. Flow validation sanitizes and verifies reference formats without exposing or leaking credentials.
3. The orchestrator resolves references dynamically from Vault just prior to operator initialization in memory.
4. Resolved values remain strictly transient and are never written back to disk, database, or API response payloads.

---

## Architecture

The following diagram illustrates the lifecycle of a `vault://` reference from authoring to operator execution:

```mermaid
graph TD
    UI[Web UI Canvas / Flow JSON] -->|vault:// URI| API[REST API / Storage]
    API -->|Authoring Flow intact| Val[Flow Validator]
    Val -->|Dry-run sanitization| Orch[Python Orchestrator]
    Orch -->|Resolve URIs| SecProv[SecretProvider / HashiCorpVault]
    SecProv -->|AppRole or Token Auth| Vault[(HashiCorp Vault)]
    Vault -->|Decrypted Secret| SecProv
    SecProv -->|In-memory Config| Op[Operator Instance]
    Op -->|Execute transform| Svc[External Service / DB]
```

### Key Components

- **`SecretProvider` / `HashiCorpVault`** (`src/docpipe/integrations/secrets/`): Interacts with Vault's KV v2 engine, handles authentication (Token or AppRole), auto-refreshes tokens, and auto-deserializes JSON strings into dictionaries.
- **`VaultInitializer`** (`src/docpipe/integrations/secrets/vault_initializer.py`): Initializes configured secret providers on server and CLI startup.
- **`FlowValidator`** (`src/docpipe/core/orchestration/flow_validator.py`): Sanitizes `vault://` placeholders during schema validation so schema type-check rules pass without network dependency on Vault.
- **`PythonOperatorExecutor`** (`src/docpipe/core/orchestration/python/python_operator_executor.py`): Recursively walks operator configuration trees and replaces all `vault://` paths with resolved values before instantiating operator classes.
- **`FlowMapper`** (`src/docpipe/api/dto/mappers/flow_mapper.py`): Preserves `vault://` strings unchanged in API responses so authoring workflows round-trip cleanly without masking them as `********`.

---

## URI Format and Patterns

### URI syntax

Every Vault secret reference follows the standard format:

```text
vault://<provider>/<secret_path>#<field_key>
```

| Component | Description | Example |
|---|---|---|
| `vault://` | Protocol scheme identifier | `vault://` |
| `<provider>` | Registered provider name in config | `hashicorp` |
| `<secret_path>` | Path to the secret in Vault KV v2 mount | `docpipe/s3` or `secret/data/docpipe/s3` |
| `#<field_key>` | Specific key within the secret's data map | `#access_key` |

### Pattern A — individual field references

Use this pattern to store secrets as distinct key-value pairs in Vault. Recommended for granular access control and standard credential fields:

**Vault Secret Data (`docpipe/s3`):**
```json
{
  "auth_token": "placeholder-token-value"
}
```

**Flow Configuration:**
```json
{
  "type": "embeddings",
  "name": "embed",
  "config": {
    "provider": "openai",
    "provider_config": {
      "api_key": "vault://hashicorp/docpipe/openai#api_key"  # pragma: allowlist secret
    }
  }
}
```

### Pattern B — one reference per key

For a credential block with several keys, reference each key separately. A reference supplies one string, so a reference
to a whole object fails with `value must be a string`. Only the fields named `credentials_json` and
`service_account_json` hold a structured value, and the resolved string is parsed as JSON once.

**Flow Configuration:**
```json
{
  "type": "storage_output",
  "name": "export_s3",
  "config": {
    "destination_type": "s3",
    "destination_config": {
      "bucket_name": "processed-output",
      "credentials": {
        "access_key": "vault://hashicorp/docpipe/s3#access_key",
        "secret_key": "vault://hashicorp/docpipe/s3#secret_key"  # pragma: allowlist secret
      }
    }
  }
}
```

See the [Secrets Guide](../../guides/SECRETS_GUIDE.md) for the declared fields and the `allowed_paths` policy.

---

## Supported Operators and Fields

Each operator declares which of its fields accept a `vault://` reference. A reference in any other field is rejected as
`field not secret-capable`. The [Secrets Guide](../../guides/SECRETS_GUIDE.md#declared-secret-fields) lists every
declared field. Examples:

| Operator | Parameter Path | Description |
|---|---|---|
| **`ingest_source`** | `provider_config.access_key`, `provider_config.secret_key` | S3 and IBM COS keys |
| | `provider_config.client_secret` | SharePoint and OneDrive client secret |
| | `provider_config.credentials_json` | Google Drive and Box credential JSON |
| **`embeddings`** | `provider_config.api_key` | LLM API key |
| **`extract_operator`** | `entity_extraction.provider_config.api_key` | Entity extraction LLM API key |
| **`document_classifier`** | `provider_config.api_key` | Classification LLM provider API key |
| **`vectordb`** | `provider_config.username`, `provider_config.password` | OpenSearch, Milvus and Weaviate login |
| | `provider_config.api_key`, `provider_config.token` | Weaviate API key, Milvus token |
| **`storage_output`** | `destination_config.credentials.<key>` | One reference per credential key |
| | `destination_config.provider_config.access_key` | Destination S3 access key |
| | `destination_config.provider_config.client_secret` | Destination SharePoint secret |

---

## Configuration

### Configuration file (`docling-pipelines-config.yaml`)

Enable Vault in `docling-pipelines-config.yaml` under the `secrets` block:

```yaml
secrets:
  vault:
    enabled: true
    provider: hashicorp
    url: "http://127.0.0.1:8200"
    mount_point: "secret"
    auth_method: "approle"      # "approle" (production) or "token" (dev/testing)
    role_id: ""                 # set via VAULT_ROLE_ID environment variable
    secret_id: ""               # set via VAULT_SECRET_ID environment variable
    token: ""                   # set via VAULT_TOKEN environment variable (if auth_method is token)
    timeout: 30
```

### Authentication methods

#### 1. AppRole Authentication (Production Recommended)
AppRole authentication is intended for automated services. Docpipe uses a `role_id` and `secret_id` to authenticate against Vault, obtain a transient client token, and automatically manage token renewal.

1. Enable AppRole in Vault:
   ```bash
   vault auth enable approle
   ```
2. Create a policy (`docpipe-read-policy.hcl`):
   ```hcl
   path "secret/data/docpipe/*" {
     capabilities = ["read"]
   }
   ```
   ```bash
   vault policy write docpipe-read docpipe-read-policy.hcl
   ```
3. Create AppRole binding:
   ```bash
   vault write auth/approle/role/docpipe-role \
     secret_id_ttl=0 \
     token_num_uses=0 \
     token_ttl=1h \
     token_max_ttl=24h \
     token_policies="docpipe-read"
   ```
4. Fetch Role ID and generate Secret ID:
   ```bash
   vault read auth/approle/role/docpipe-role/role-id
   vault write -f auth/approle/role/docpipe-role/secret-id
   ```

#### 2. Token Authentication (Development / Local Testing)
For local testing or development, pass a static developer or root token directly:
```bash
export VAULT_AUTH_METHOD=token
export VAULT_TOKEN="root-dev-token"
```

### Environment variables

Environment variables override values configured in `docling-pipelines-config.yaml`:

| Variable | Description | Default |
|---|---|---|
| `DOCPIPE_VAULT_ENABLED` | `true` enables the secret provider, `false` disables it and always wins | `secrets.vault.enabled` |
| `VAULT_PROVIDER` | Provider identifier used in URIs | `hashicorp` |
| `VAULT_ADDR` or `VAULT_URL` | HashiCorp Vault server address | `http://127.0.0.1:8200` |
| `VAULT_MOUNT_POINT` | KV v2 secrets engine mount point | `secret` |
| `VAULT_AUTH_METHOD` | Auth mechanism: `approle` or `token` | `approle` |
| `VAULT_ROLE_ID` | AppRole Role ID | `""` |
| `VAULT_SECRET_ID` | AppRole Secret ID | `""` |
| `VAULT_TOKEN` | Vault token (when `VAULT_AUTH_METHOD=token`) | `""` |
| `VAULT_TIMEOUT` | Connection timeout in seconds | `30` |

---

## Web UI and Properties Panel Usage

The Docling Pipelines web canvas provides integrated support for Vault credential references via the shared `VaultInput` component.

### Interactive properties panel controls

When editing any sensitive parameter in an operator's properties panel:

1. **Direct Entry vs Vault Reference Toggle**:
   - Click the **Vault** icon or mode toggle next to the input field to switch from direct text entry to Vault reference mode.
2. **Simplified Reference Input**:
   - In Vault mode, the prefix `vault://hashicorp/` is managed automatically. You only type the path and key: `docpipe/opensearch#password`.
3. **Round-Trip Safety**:
   - Existing `vault://` URIs in loaded flows are automatically detected and displayed in Vault mode.
   - Saving the flow preserves the exact `vault://...` URI in the flow definition without converting it into a plaintext masked password.

---

## Validation and Masking Lifecycle

To prevent credential leakage while maintaining robust flow authoring and execution:

1. **Schema Validation (`FlowValidator`)**:
   - When validating flow JSON, fields marked as `sensitive` that contain `vault://` strings are replaced in-memory with dummy mock values matching the required schema type (e.g. valid dummy strings).
   - If Vault is not configured in the active environment, the validator issues a clear warning (`Config key '...' references unregistered vault provider '...'`) instead of failing execution unconditionally.
2. **REST API Masking (`FlowMapper`)**:
   - Direct cleartext credentials stored in flows are masked as `********` when retrieved through REST endpoints (`GET /api/v1/flows`).
   - `vault://` URI references are recognized as safe pointer strings and are returned unmasked, enabling UI canvas editors to load and edit the flow without corrupting the reference.
3. **Logging Hygiene**:
   - Resolved secret values are never printed in application logs. Operator executor logs record only the configuration path names being resolved (e.g. `['provider_config.username', 'provider_config.password']`), never the resolved values.

---

## Integration Guide

For end-to-end setup instructions, AppRole configuration walkthroughs, and security details, see the [Vault Integration Guide](../../guides/VAULT_INTEGRATION_GUIDE.md).

---

## Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| `Vault AppRole login failed: connection failed` (or `Vault secret read failed (kv2): connection failed`) | Vault service is stopped or unreachable. Messages name a category only and omit the address | Check if Vault is running (`curl $VAULT_ADDR/v1/sys/health`) |
| `Vault provider will not be registered - unsafe transport configuration` | Plaintext `http` to a non-loopback host, `VAULT_TLS_SKIP_VERIFY` with a non-loopback host, or credentials (`user:password@`) in `VAULT_ADDR` | Use an `https` `VAULT_ADDR` without credentials; reserve `VAULT_TLS_SKIP_VERIFY` for loopback development |
| `Key 'api_key' not found at vault path 'docpipe/embeddings'` | Secret key mismatch or secret not written | Check secret path in Vault: `vault kv get secret/docpipe/embeddings` |
| `VAULT_URI_MALFORMED` / `malformed reference` | The value contains `vault://` but is not exactly one valid reference (truncated, embedded, `..` segment, whitespace, over 1024 characters). It is rejected and never used as a literal | Use the whole value `vault://<provider>/<path>[#<key>]` |
| `Unregistered vault provider 'hashicorp'` | Vault provider is not initialized | Ensure `DOCPIPE_VAULT_ENABLED=true` or configure `secrets.vault` in config YAML |
| `value must be a string` | A reference was assigned to a whole object, or the secret value is not a string | Use Pattern B: reference each key separately |
