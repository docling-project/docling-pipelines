# Secrets Guide

This guide explains how you keep credentials out of flow definitions, what the platform enforces when it resolves a
`vault://` reference, and what you must configure as a deployer. For installing and authenticating to Vault, see the
[Vault Integration Guide](VAULT_INTEGRATION_GUIDE.md).

## Table of contents

- [Overview](#overview)
- [Reference grammar](#reference-grammar)
- [Declared secret fields](#declared-secret-fields)
- [Deployer policy](#deployer-policy)
  - [Allowed paths](#allowed-paths)
  - [Allowed destinations](#allowed-destinations)
  - [Startup log lines](#startup-log-lines)
- [Validation findings](#validation-findings)
- [Resolution errors](#resolution-errors)
- [Audit records](#audit-records)
- [Custom operators](#custom-operators)
  - [Trust classes](#trust-classes)
  - [Isolation](#isolation)
  - [Who may upload](#who-may-upload)
- [Credentials stay out of storage and logs](#credentials-stay-out-of-storage-and-logs)
- [Migration](#migration)
- [Sample flows](#sample-flows)

## Overview

A flow stores a pointer such as `vault://hashicorp/docpipe/s3#secret_key`. The platform resolves it in memory when it
builds the node, and hands the value to the operator wrapped so that it never reaches a log, an exception message, a
database row or an API response.

The platform applies four rules to every reference:

1. The reference must be the whole value of a field that the operator declares secret-capable.
2. The Vault path must match `secrets.vault.allowed_paths`. When the setting is unset, every reference is denied.
3. A literal network destination next to a secret must match `secrets.vault.allowed_destinations`.
4. Failures report a category and a correlation id. They never include the path, the key, the value or the Vault
   address.

## Reference grammar

```text
vault://<provider>/<path>[#<key>]
```

| Part | Rule |
|---|---|
| `<provider>` | The name of a registered provider, for example `hashicorp`. |
| `<path>` | Slash-separated segments. Empty segments, `.` and `..` are rejected. |
| `#<key>` | Optional. Without it, the secret must hold exactly one key. |

The reference must be the entire value. These are rejected as `malformed reference` and never used as a literal:

- A reference embedded in a larger string, such as `https://vault://...`.
- A value with whitespace or control characters.
- A value longer than 1024 characters.

A reference supplies a single string. A JSON-looking string placed in a scalar field such as `password` is not
parsed. To supply several secrets, use one reference per key:

```json
{
  "destination_config": {
    "credentials": {
      "access_key": "vault://hashicorp/docpipe/s3#access_key",
      "secret_key": "vault://hashicorp/docpipe/s3#secret_key"  # pragma: allowlist secret
    }
  }
}
```

Assigning one reference to a whole object, such as `"credentials": "vault://..."`, fails with `value must be a string`.
Only the fields named `credentials_json` and `service_account_json` hold a structured value: the resolved string is
parsed as JSON once.

## Declared secret fields

A reference works only in a field that the operator declares secret-capable in its `get_metadata()`. A reference in any
other field, such as `index_name`, is reported as `field not secret-capable`. Fields that name a resource, such as an
index, collection, bucket path or folder, can never be declared.

Paths in the table are relative to the operator `config`.

| Operator | Provider | Secret-capable fields |
|---|---|---|
| `ingest_source` | `s3`, `ibm_cos` | `provider_config.{access_key, secret_key, bucket, endpoint_url, region}` |
| | `google_drive` | `provider_config.{credentials_json, credentials_path, service_account_json, service_account_json_path, token_path}` |
| | `onedrive` | `provider_config.{client_id, client_secret, drive_id, tenant_id}` |
| | `sharepoint` | `provider_config.{client_id, client_secret, document_library_id, tenant_id}` |
| | `box_driver` | `provider_config.{credentials_json, credentials_json_path, credentials_path}` |
| | `dropbox` | `provider_config.{access_token, app_key, app_secret, refresh_token}` |
| `storage_output` | all | `destination_config.credentials.*` |
| | `s3`, `ibm_cos` | `destination_config.provider_config.{access_key, secret_key, endpoint_url}` |
| | `sharepoint`, `onedrive` | `destination_config.provider_config.{client_id, client_secret, tenant_id}` |
| | `box` | `destination_config.provider_config.credentials_path` |
| | `google_drive` | `destination_config.provider_config.{credentials_path, service_account_json_path, token_path}` |
| `vectordb` | `opensearch` | `provider_config.{aws_region, host, jwt_token, password, username}` |
| | `milvus` | `provider_config.{database, host, password, token, uri, username}` |
| | `weaviate` | `provider_config.{api_key, bearer_token, password, username}` |
| `embeddings`, `document_classifier` | `litellm` | `provider_config.{api_base, api_key}` |
| | `watsonx` | the `litellm` fields plus `provider_config.url` |
| `chunker` | `litellm` | `provider_config.{api_base, api_key}` and `summarization.provider_config.{api_base, api_key}` |
| | `watsonx` | the `litellm` fields plus `url` |
| `extract_operator` | `docling_library` | `text_extraction.provider_config.vlm_pipeline.engine_options.{api_base, api_key}` |
| | `docling_serve` | `text_extraction.provider_config.{api_key, base_url}` |
| | entity extraction | `entity_extraction.provider_config.{api_base, api_key}` (plus `url` for `watsonx`) |
| `pii_and_hap` | `litellm` | `{provider_config, pii_provider_config, hap_provider_config}.{api_base, api_key}` |
| | `watsonx` | the same three blocks, `{api_key, url}` |
| `acl_operator` | all | `credentials.*` |

`filesystem` and `web` ingest, `filesystem` storage, and the `huggingface` and `presidio` providers have no
secret-capable fields.

Some credential-looking fields deliberately reject references. They are marked `no_references` in the operator schema,
and the validator reports them the same way as any other undeclared field.

## Deployer policy

All keys live in `docling-pipelines-config.yaml`.

```yaml
secrets:
  vault:
    enabled: true
    provider: hashicorp
    allowed_paths:
      - "hashicorp:docpipe/*"
      - "hashicorp:opensearch/prod@vectordb.provider_config.password"
    allowed_destinations:
      - "*.corp.example.com"
```

Set `DOCPIPE_VAULT_ENABLED=true` or `false` to override `enabled` from the environment. `false` always wins.

### Allowed paths

Each entry has the form `provider:glob[@operator.field]`.

| Element | Meaning |
|---|---|
| `provider` | Exact, case-sensitive match. `*` matches any provider. |
| `glob` | `*` stays within one path segment. `**` crosses segments. Matching is case-sensitive. |
| `@operator.field` | Optional scope. The operator `short_name` must equal the entry, and the config key must equal the field or end with `.field`. |

`*:**` allows every path that the platform can read. Use it only on a development system. With the setting unset or
empty, every reference is denied with `not permitted`. This is deliberate: a flow author must not be able to read any
secret that the platform identity can read.

### Allowed destinations

`allowed_destinations` is a list of host globs. It applies when a secret-bearing node also sets a literal network
destination in `endpoint_url`, `host`, `uri`, `api_base`, `url` or `base_url`. The platform parses the host from the
literal, lower-cases it and matches it with `fnmatch`. This stops an author from pairing a permitted secret with a host
they control.

- A literal host that does not match is reported as `destination not permitted`.
- A destination that is itself a reference is accepted, because the reference is checked against `allowed_paths`.
- An unset list rejects every literal destination next to a secret.

### Startup log lines

| Condition | Log record |
|---|---|
| A provider is registered and `allowed_paths` is unset | One `ERROR`. Every reference is denied. |
| `allowed_paths` contains `*:**` | One `WARNING`. |
| An entry is not of the form `provider:glob[@operator.field]` | One `ERROR` for each such entry. The entry is ignored. |

## Validation findings

`docling-pipelines --flow-file <path> --validate` and the validate endpoint check references without contacting Vault.

| Code | Meaning |
|---|---|
| `VAULT_URI_MALFORMED` | The value contains `vault://` but is not exactly one valid reference. |
| `VAULT_FIELD_NOT_SECRET_CAPABLE` | The field is not declared secret-capable. |
| `VAULT_PATH_NOT_PERMITTED` | No `allowed_paths` entry matches. For an untrusted custom operator the message names `custom_operator_allowed_paths`. |
| `VAULT_DESTINATION_NOT_PERMITTED` | A literal destination does not match `allowed_destinations`. |
| `VAULT_PROVIDER_NOT_REGISTERED` | The provider is not registered. It is a warning when no provider is registered at all, so validation still exits 0 on a machine without Vault. |

## Resolution errors

A failure message has this form:

```text
secret reference <config key> (provider <provider>): <category> [id <correlation id>]
```

The same correlation id appears in the server-side log and in the audit record.

| Category | Typical cause |
|---|---|
| `provider not registered` | Vault is disabled or the provider name differs from `secrets.vault.provider`. |
| `secret unavailable` | The path or key does not exist, the platform identity lacks permission, or a secret with several keys was referenced without `#<key>`. |
| `vault unreachable` | The Vault server did not answer. The API returns HTTP 502. |
| `malformed reference` | The value does not match the grammar. The message adds the expected format. |
| `not permitted` | The path, field or destination check failed. |
| `value must be a string` | The reference points at a non-string value, or it was assigned to an object. |

## Audit records

The `docpipe.audit` logger writes one JSON line per event to stdout. The logger is separate from application logging: it
does not propagate to the root logger, its level is fixed at `INFO`, and handler filters do not apply. A failure to
write an audit record never fails the request.

Set `audit.retention_days` to a positive integer to also write a daily-rotating file that keeps that many days. The
default file is `<DOCPIPE_DATA_PATH>/audit/docpipe-audit.log`; override it with `audit.file`.

```yaml
audit:
  retention_days: 90
  file: ./data/audit/docpipe-audit.log
```

| Event | Fields |
|---|---|
| Custom operator create, update or delete | `timestamp`, `caller`, `operator_id`, `short_name`, `action`, `script_sha256`, `outcome` (`success` or `rejected`), optional `reason` |
| Reference resolution | `timestamp`, `job_id`, `job_run_id`, `node`, `config_key`, `provider`, `outcome` (`resolved` or an error category), `correlation_id` |

A `not permitted` outcome is logged at `WARNING`. No record contains a secret value, a Vault path or a Vault key.

## Custom operators

A custom operator is Python code that runs with the permissions of the platform. Python running in the same process
cannot be made safe against a hostile author: it can read any memory in that process. For that reason, uploading a
custom operator is an administrator capability, and the platform adds the controls below.

Custom operators are disabled by default. Set `DOCPIPE_ENABLE_CUSTOM_OPERATORS=true` to load them, and every route
requires an authenticated user. See the [Custom Operators Guide](CUSTOM_OPERATORS_GUIDE.md) for authoring.

### Trust classes

| Class | Source | Secret access |
|---|---|---|
| Platform | Built in (`owner: docpipe`) | Uses `secrets.vault.allowed_paths`. |
| Deployer-installed | A package installed by the deployer, `DOCPIPE_CUSTOM_OPERATORS` | Uses `secrets.vault.allowed_paths`. |
| Untrusted | An API upload or an object-store source | Uses `secrets.vault.custom_operator_allowed_paths`, empty by default. |

### Isolation

`custom_operators.isolation` controls how an untrusted operator runs:

| Value | Behavior |
|---|---|
| `process` | The operator runs in a separate worker process that holds no secret provider, no Vault token and no other node's configuration. |
| `disabled` | The operator is refused with `not permitted`. |
| unset | `disabled` while a provider is registered. Without a provider, operators run in-process as before. |

Any other value is treated as `disabled` and logs one `ERROR`.

The worker receives only these environment variables: `PATH`, `LANG`, `LC_ALL`, `LC_CTYPE`, `TZ`, `TMPDIR`,
`PYTHONPATH`, `VIRTUAL_ENV` and `DS_LOG_LEVEL`. It receives the node's own resolved configuration plus `doc_column`,
`job_id` and the node identity keys from the global configuration.

The parent also sets two variables to operate the worker: `PYTHONUNBUFFERED` and `PYTHON_DOTENV_DISABLED=1`. The second
stops the worker from loading a `.env` file from the repository root when it imports application modules, so no
variable defined in a `.env` appears in the worker's environment. A value of `PYTHON_DOTENV_DISABLED` in the parent
process is ignored. The API, command line, library and Prefect workers keep loading `.env` as before.

Isolation separates memory. It does not separate the operating system account. Worker code can still open a file that
its operating system user can read, including a `.env`, so you must also provide these deployment preconditions:

1. **A distinct worker user.** Run the worker under a UID that differs from the one that owns the Vault token and
   configuration.
2. **Read-restricted credentials.** Make `~/.vault-token` and the AppRole configuration unreadable by the worker UID.
3. **Egress restriction.** Allow the worker network access only to the hosts that the operator needs. Without this, a
   worker that holds a resolved value can send it anywhere.

### Who may upload

`custom_operators.allowed_uploaders` lists the usernames, as authenticated by the API, that may create, update or
delete a custom operator.

```yaml
custom_operators:
  allowed_uploaders:
    - alice
  isolation: process
```

- The list is enforced only while a secret provider is registered. An unset or empty list then permits nobody (403).
- With no secret provider, any authenticated user may upload, as before.
- Read routes stay open to any authenticated user.

## Credentials stay out of storage and logs

| Surface | Behavior |
|---|---|
| Flow storage and API responses | Store and return the reference unchanged. They never hold a resolved value. |
| Exceptions and logs | Pass through `sanitize_exception`, which reports the config key and category but not the value. |
| Process environment | A resolved value is never placed in `os.environ`, and `$VAR` expansion does not apply to it. |
| Credential files | `temporary_credential_file` creates a `0700` directory and a `0600` file, and removes both on exit. |
| Caches | Keys are HMAC-SHA256 values under a per-run key, not the secret. |
| Prefect | A Prefect run carries references only. Each task resolves its own. |
| Document output | Operators do not write credentials into document metadata, parquet output or storage sidecars. |

The wrapper reveals a value only at the adapter boundary, where the client library needs it.

## Migration

Earlier versions of the SharePoint and OneDrive ingest adapters wrote credentials into document metadata, and the
`ACLOperator` read them from there. Treat any credential found in old output as disclosed:

1. Run `python scripts/find_persisted_credentials.py <paths>`. It prints file names and key names, never a value. Exit
   status is `0` for none found, `1` for affected files, and `2` for a usage error or when nothing was scanned.
2. Rotate the credentials in the identity provider.
3. Purge the files, sidecars and backups.
4. Re-ingest.

See [Persisted credentials](VAULT_INTEGRATION_GUIDE.md#persisted-credentials-rotate-purge-re-ingest) for the full
procedure. The `ACLOperator` now takes its own `credentials` setting. See the
[ACL operator README](../operators/extract/acl_readme.md).

To adopt the controls on an existing deployment:

1. Set `secrets.vault.allowed_paths` before the upgrade. Without it, existing references stop resolving.
2. Replace any whole-object reference, such as `"credentials": "vault://..."`, with one reference per key.
3. Replace `VAULT_ENABLED` with `DOCPIPE_VAULT_ENABLED` in your environment.
4. Set `custom_operators.allowed_uploaders` and `custom_operators.isolation` if you upload custom operators.

## Sample flows

| Flow | Shows |
|---|---|
| [`sample_flows/use_cases/s3_ingest_vault.json`](../../sample_flows/use_cases/s3_ingest_vault.json) | S3 credentials from Vault in an ingest node |
| [`sample_flows/vectordb/opensearch_vault_integration.json`](../../sample_flows/vectordb/opensearch_vault_integration.json) | OpenSearch host and credentials from Vault |

For the matching Vault policy and AppRole setup, follow the
[Vault Integration Guide](VAULT_INTEGRATION_GUIDE.md#step-by-step-setup-and-usage-walkthrough).
