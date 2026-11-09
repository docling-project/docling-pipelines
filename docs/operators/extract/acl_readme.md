# ACLOperator

Extracts effective user permissions from document storage providers and appends them as an `allowed_users` column.

- **Short Name:** `acl_operator`
- **Category:** Extract

---

## Overview

`ACLOperator` reads the provider from the input table metadata (populated by
`IngestSourceOperator`), authenticates with the credentials in its own `credentials` config, and
fetches current ACL data for each document from the source system (SharePoint, S3, Google Drive,
etc.). It appends a single `allowed_users` column containing a JSON array of normalised user
identities, leaving all other columns unchanged.

Ingest adapters no longer write credentials into document metadata, so the operator cannot read
them from upstream. Configure `credentials` on the ACL node, preferably as `${ENV_VAR}` references.

## Key Features

- **Own credentials**: Credentials come from the operator's `credentials` config, never from document metadata
- **Fail-fast validation**: A missing credential key stops the flow with an error that names the key (never its value)
- **Stable identity tuples**: Uses `siteId`/`driveId`/`itemId` for reliable ACL lookups
- **Always-fresh data**: ACLs are fetched at pipeline run time, never cached
- **All-or-nothing mode** (`fail_on_error: true`): Fails the flow if any document fails ACL extraction
- **Best-effort mode** (`fail_on_error: false`): Skips failed documents and continues
- **Batch processing**: Concurrent extraction via asyncio

---

## Operator Configuration

```json
{
  "type": "acl_operator",
  "name": "extract_acl_permissions",
  "config": {
    "credentials": {
      "client_id": "${SHAREPOINT_CLIENT_ID}",
      "client_secret": "${SHAREPOINT_CLIENT_SECRET}",
      "tenant_id": "${SHAREPOINT_TENANT_ID}"
    },
    "fail_on_error": true
  },
  "depends_on": ["ingest_documents"]
}
```

---

## Parameters

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `credentials` | object | Yes (SharePoint) | - | Provider credentials. SharePoint requires `client_id`, `client_secret` and `tenant_id`. Values may be `${ENV_VAR}` references |
| `provider_config` | object | No | `{}` | Provider-specific settings (e.g. `resolve_inheritance`, `expand_groups`) |
| `fail_on_error` | boolean | No | `true` | `true` — fail the flow if any document fails ACL extraction; `false` — skip failed documents and continue |

**Note:** `provider` and `connection_params` are still read automatically from
`IngestSourceOperator` metadata — do not set them here. Credentials are not.

---

## Output Columns

All input columns are preserved. The operator appends:

| Column | PyArrow Type | Description |
|---|---|---|
| `allowed_users` | `string` | JSON array of normalised user identities (emails/UPNs) with access to the document, sorted alphabetically. Empty array `"[]"` when no users have access. |

---

## Examples

### Example 1 — Minimal configuration

```json
{
  "type": "acl_operator",
  "name": "extract_acl_permissions",
  "config": {
    "credentials": {
      "client_id": "${SHAREPOINT_CLIENT_ID}",
      "client_secret": "${SHAREPOINT_CLIENT_SECRET}",
      "tenant_id": "${SHAREPOINT_TENANT_ID}"
    },
    "fail_on_error": true
  },
  "depends_on": ["ingest_sharepoint_documents"]
}
```

### Example 2 — With provider-specific settings (best-effort)

```json
{
  "type": "acl_operator",
  "name": "extract_acl_permissions",
  "config": {
    "credentials": {
      "client_id": "${SHAREPOINT_CLIENT_ID}",
      "client_secret": "${SHAREPOINT_CLIENT_SECRET}",
      "tenant_id": "${SHAREPOINT_TENANT_ID}"
    },
    "provider_config": {
      "resolve_inheritance": true,
      "expand_groups": true,
      "normalize_identities": true
    },
    "fail_on_error": false
  },
  "depends_on": ["ingest_sharepoint_documents"]
}
```

### Example 3 — Complete flow (SharePoint → ACL → Extract)

```json
{
  "flow_name": "acl-extraction-pipeline",
  "description": "Extract documents with ACL permissions",
  "flow": [
    {
      "type": "ingest_source",
      "name": "ingest_sharepoint_documents",
      "config": {
        "provider": "sharepoint",
        "connection_params": {
          "document_library_id": "b!...",
          "folder_path": null,
          "recursive": true
        },
        "credentials": {
          "client_id": "your-client-id",
          "client_secret": "your-client-secret",  # pragma: allowlist secret
          "tenant_id": "your-tenant-id"
        },
        "include_filter": ".txt,.pdf,.docx"
      }
    },
    {
      "type": "acl_operator",
      "name": "extract_acl_permissions",
      "config": {
        "credentials": {
          "client_id": "${SHAREPOINT_CLIENT_ID}",
          "client_secret": "${SHAREPOINT_CLIENT_SECRET}",
          "tenant_id": "${SHAREPOINT_TENANT_ID}"
        },
        "fail_on_error": true
      },
      "depends_on": ["ingest_sharepoint_documents"]
    },
    {
      "type": "extract_operator",
      "name": "extract_document_content",
      "config": {
        "text_extraction": {"provider": "docling_library"},
        "entity_extraction": {"provider": "none"}
      },
      "depends_on": ["extract_acl_permissions"]
    }
  ]
}
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `FlowExecutionFailedException: No metadata found in input table` | ACLOperator runs before IngestSourceOperator | Ensure `depends_on` points to the ingest node |
| `FlowExecutionFailedException: Provider not found in metadata` | IngestSourceOperator metadata missing provider field | Verify the ingest node includes `provider` in its config |
| `FlowExecutionFailedException: ACL operator 'credentials' config is missing required key(s) ...` | The ACL node has no `credentials`, or lacks the named keys | Add the named keys to the ACL node's `credentials`; they are no longer read from ingest metadata |
| `FlowExecutionFailedException: ACL operator credential '<key>' references an environment variable that is not set` | A `${ENV_VAR}` reference in `credentials` is unset | Export the variable in the process that runs the flow |
| `ACL extraction completed: 0 processed, N failed` | Credentials invalid or insufficient permissions | Check SharePoint credentials; try `fail_on_error: false` to identify failing documents |

---

## Architecture

### Hexagonal layers

The operator follows a three-layer hexagonal architecture:

- **Domain** (`domain/`) — provider-agnostic models: `ACLRequest`, `ACLResponse`, `ACLExtractionResult`, `RawPermission`
- **Ports** (`ports/`) — `ACLExtractionPort` abstract interface
- **Adapters** (`adapters/`) — concrete provider implementations (SharePoint, future: S3, Google Drive, OneDrive, Box)

### Currently supported providers

- **SharePoint** — full implementation with inheritance resolution and group expansion

### Typical pipeline position

```
IngestSourceOperator → ACLOperator → ExtractOperator → [Chunker → Embeddings → VectorDB]
```

### `allowed_users` output format

```json
{ "allowed_users": "[\"user1@contoso.com\", \"user2@contoso.com\"]" }
```

### Error handling modes

| Mode | Behaviour |
|---|---|
| `fail_on_error: true` | All-or-nothing — any single failure aborts the flow |
| `fail_on_error: false` | Best-effort — failed documents are skipped and tracked in metadata |

### Missing Metadata Error (legacy section)

See the [Troubleshooting table](#troubleshooting) above for quick fixes.

### Credentials persisted by earlier versions

Earlier versions of the SharePoint and OneDrive ingest adapters wrote `client_id`, `client_secret`
and `tenant_id` into document metadata, and therefore into parquet output and `*.meta.json`
sidecars. Treat any credential found there as disclosed. See
[Persisted credentials: rotate, purge, re-ingest](../../guides/VAULT_INTEGRATION_GUIDE.md#persisted-credentials-rotate-purge-re-ingest).
