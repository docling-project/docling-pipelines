# Security Best Practices

This guide describes the security practices users of this repository should follow when deploying, configuring, and operating Docling-pipelines.

For the internal security architecture (how Docling-pipelines implements these controls), see [ARCHITECTURE.md — Security Architecture](../../ARCHITECTURE.md#security-architecture).

## Table of Contents

1. [Secret and Credential Management](#1-secret-and-credential-management)
2. [REST API Security](#2-rest-api-security)
3. [Authentication Configuration](#3-authentication-configuration)
4. [Document Access Control](#4-document-access-control)
5. [Network and Infrastructure](#5-network-and-infrastructure)
6. [PII and Sensitive Data in Pipelines](#6-pii-and-sensitive-data-in-pipelines)
7. [Dependency and Supply-Chain Security](#7-dependency-and-supply-chain-security)
8. [Observability and Audit Logging](#8-observability-and-audit-logging)
9. [Quick-Reference Checklist](#9-quick-reference-checklist)

---

## 1. Secret and Credential Management

### Never commit secrets to source control

Docling-pipelines reads all sensitive values from environment variables. The `.env.example` and `.env.oauth2.example` files in the project root show which variables are required; copy one to `.env` and fill in real values — never commit the populated `.env` file.

The repository enforces this with a `detect-secrets` pre-commit hook. Do not bypass pre-commit hooks (`git commit --no-verify` is blocked by project policy).

### Use environment variable substitution in flow files

Flow JSON definitions support `${ENV_VAR}` substitution. Use this pattern for any value that is sensitive — API keys, passwords, or endpoints that should not appear in a committed file:

```json
{
  "type": "embeddings",
  "name": "embed",
  "config": {
    "provider": "watsonx",
    "provider_config": {
      "api_key": "${WATSONX_API_KEY}",
      "url": "${WATSONX_API_BASE_URL}"
    }
  }
}
```

### Rotate secrets regularly

| Credential | Recommended rotation |
|---|---|
| `JWT_SECRET_KEY` | At least every 90 days; immediately after any suspected exposure |
| LDAP bind password (`LDAP_BIND_PASSWORD`) | Follow your organisation's directory policy |
| OAuth2 client secret (`OAUTH2_CLIENT_SECRET`) | At least every 90 days |
| WatsonX / IBM Cloud API keys | Follow IBM Cloud key rotation policy |
| OpenSearch credentials | Follow your OpenSearch deployment policy |
| Object-storage access keys (S3/COS) | Follow your cloud provider's recommendation |

### Secrets at rest

- Store `.env` files in a secrets manager (HashiCorp Vault, AWS Secrets Manager, Azure Key Vault, IBM Secrets Manager) rather than on disk in plain text.
- In containerised deployments, inject secrets as environment variables from the orchestrator (Kubernetes Secrets, Docker secrets) rather than baking them into images.
- Restrict filesystem permissions on `.env` files: `chmod 600 .env`.

---

## 2. REST API Security

### Set a strong JWT secret

`JWT_SECRET_KEY` is used to sign all access tokens. In production this **must** be a cryptographically random string of at least 32 bytes:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Never use the placeholder value from `.env.oauth2.example` in a real deployment.

### Reduce token lifetime for sensitive deployments

The default JWT access token lifetime is 30 minutes (`JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30`). For high-security environments reduce this to 10–15 minutes and implement token refresh.

### Lock down CORS origins

`CORS_ORIGINS` defaults to `http://localhost:3000` (development only). In production, set it explicitly to the exact origins of your frontend:

```bash
CORS_ORIGINS=https://app.example.com,https://admin.example.com
```

Do not use `*` as a CORS origin in production — it disables origin-based cross-site request protection.

### Run the API behind TLS

Docling-pipelines's built-in server (`uvicorn`) does not terminate TLS. In production always place a TLS-terminating reverse proxy (nginx, Traefik, AWS ALB, etc.) in front. Never expose port 8080 to the public internet without TLS.

### Restrict network exposure

Only expose the API port to trusted networks or behind an API gateway. The Prefect server, OpenSearch, and Ollama should never be exposed to the public internet.

---

## 3. Authentication Configuration

### Prefer OAuth2/OIDC over LDAP for new deployments

OAuth2/OIDC delegates authentication to a hardened identity provider (Google, Azure AD, Okta, etc.) and is easier to integrate with MFA enforcement and SSO. LDAP is appropriate for environments that already have a directory service.

### Enforce MFA at the identity provider

Docling-pipelines itself does not enforce multi-factor authentication — this must be configured at the identity provider. Enable MFA for all user accounts in your OAuth2/OIDC provider before connecting it to Docling-pipelines.

### Enable LDAP TLS (`LDAP_USE_SSL=true`)

Plain LDAP (port 389) transmits credentials in clear text. Always enable StartTLS (`LDAP_USE_SSL=true`) or use LDAPS (port 636) to protect credentials in transit.

### Restrict the LDAP service account

The `LDAP_BIND_DN` service account is used only to search for user DNs. Grant it read-only access scoped to the `LDAP_USER_DN` subtree — it does not need write permissions or access to the full directory.

### Validate OAuth2 OIDC configuration

When using a generic OIDC provider, confirm that all three of `OIDC_ISSUER`, `oidc_audience`, and `OAUTH2_JWKS_URI` are set. Missing values weaken token validation:

| Missing variable | Risk |
|---|---|
| `OIDC_ISSUER` | Tokens from any issuer are accepted |
| `oidc_audience` | Tokens issued for other applications are accepted |
| `OAUTH2_JWKS_URI` | Signature cannot be verified |

---

## 4. Document Access Control

### Populate `allowed_users` on every indexed document

The ACL system is fail-closed: documents without an `allowed_users` field, or with an empty array, are inaccessible to all users. Ensure every document ingested into OpenSearch has a non-empty `allowed_users` list populated with the usernames authorised to read it.

### Use usernames that match your identity provider

The `allowed_users` field is compared against the `username` claim in the JWT token. Ensure the usernames in your documents match the claim emitted by your identity provider (e.g. UPN for Azure AD, email for Google).

### Do not share service-account tokens with end users

If you run automated pipelines using a service account, do not reuse that account's JWT token for interactive users. Service accounts should have tightly scoped `allowed_users` access and separate credentials.

---

## 5. Network and Infrastructure

### OpenSearch

- Enable TLS on OpenSearch (`OPENSEARCH_USE_SSL=true`, `OPENSEARCH_VERIFY_CERTS=true`).
- Use a dedicated OpenSearch user for Docling-pipelines with the minimum required permissions (read/write to pipeline indexes only).
- Never use the default `admin`/`admin` credentials in production.

```bash
OPENSEARCH_USE_SSL=true
OPENSEARCH_VERIFY_CERTS=true
OPENSEARCH_USERNAME=docpipe-service-user
OPENSEARCH_PASSWORD=<strong-random-password>
```

### Ollama

- Ollama listens on `localhost:11434` by default. Do not expose it externally unless required.
- If Ollama must be accessible from multiple hosts, place it behind an authenticated reverse proxy.

### Prefect

- The Prefect server and work pools should be accessible only from within the same network as the Docling Pipelines workers.
- Use Prefect's built-in API key authentication for remote work pool access.

### Docker / container deployments

- Do not run containers as `root`. Use a non-root user in the `Dockerfile`.
- Mount secrets as environment variables from the container orchestrator, not as files in the image.
- Scan images for known CVEs with your CI pipeline (e.g. `trivy`, `grype`) before deployment.

---

## 6. PII and Sensitive Data in Pipelines

### Detect and redact PII before storage

If your documents may contain personally identifiable information, add the `PIIAndHAPAnnotator` and `Redaction` operators to your pipeline **before** the `Chunker`, `EmbeddingsOperator`, and `VectorDBOperator` stages:

```json
[
  { "type": "ingest_source",       "name": "ingest"   },
  { "type": "extract",             "name": "extract"  },
  { "type": "pii_and_hap",         "name": "pii_scan" },
  { "type": "redaction",           "name": "redact"   },
  { "type": "chunker",             "name": "chunk"    },
  { "type": "embeddings",          "name": "embed"    },
  { "type": "vector_db",           "name": "store"    }
]
```

This ensures PII is removed before it enters long-term storage or becomes part of an embedding.

### Do not log document content at DEBUG level in production

Set `DS_LOG_LEVEL=INFO` (or `WARNING`) in production. `DEBUG` logging can expose document content, embeddings, and query results in log files.

```bash
DS_LOG_LEVEL=INFO
```

### Treat vector embeddings as sensitive

Embeddings can sometimes be reversed to approximate the original text. Apply the same access controls to your vector index as you would to the source documents.

---

## 7. Dependency and Supply-Chain Security

### Keep dependencies up to date

Run dependency audits regularly:

```bash
source .venv/bin/activate
uv pip audit          # or: pip-audit
```

Pin dependencies to specific versions in `requirements.txt` and review updates before upgrading in production.

### Use pre-commit hooks on every commit

The repository ships with a `.pre-commit-config.yaml` that includes `detect-secrets`, `ruff`, and `mypy`. Install and enable them:

```bash
pre-commit install
```

Never bypass hooks with `--no-verify`.

### Validate custom operators before use

Custom operators loaded from `examples/custom_operators/` or external packages execute arbitrary Python during pipeline runs. Only load operators from trusted, reviewed sources.

---

## 8. Observability and Audit Logging

### Retain authentication logs

The API logs all login attempts, token verifications, and access-denied events at `INFO`/`WARNING` level. Route these logs to a centralised log management system (Splunk, Elastic, IBM Log Analysis) and retain them for at least 90 days for audit purposes.

Key log events to monitor:

| Log message pattern | Significance |
|---|---|
| `Failed login attempt for user:` | Possible brute-force attempt |
| `Invalid authentication token provided` | Invalid or expired token reuse |
| `LDAP server is unavailable` | Authentication service outage |
| `Invalid OAuth2 state parameter received` | Possible CSRF attack |

### Enable OpenTelemetry tracing for production

Distributed tracing helps correlate authentication events with pipeline execution. Enable the telemetry integration in production:

```bash
DOCLING_PIPELINES_TELEMETRY_ENABLED=true
OTEL_SERVICE_NAME=docpipe-production
OTEL_EXPORTER_OTLP_ENDPOINT=https://your-collector:4317
```

See [Telemetry Setup](TELEMETRY_SETUP.md) for full configuration instructions.

---

## 9. Quick-Reference Checklist

Use this checklist when preparing a production deployment.

### Secrets
- [ ] `.env` is not committed to source control
- [ ] `JWT_SECRET_KEY` is a cryptographically random value (≥ 32 bytes), not the example placeholder
- [ ] All API keys and passwords are loaded from environment variables, not hard-coded in flow files
- [ ] Secrets are stored in a secrets manager, not as plain-text files on disk

### Authentication
- [ ] `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` is set to an appropriate value for your risk profile
- [ ] `LDAP_USE_SSL=true` (or LDAPS) is enabled if using LDAP
- [ ] MFA is enforced at the identity provider (OAuth2/OIDC deployments)
- [ ] OIDC configuration includes `OIDC_ISSUER`, `oidc_audience`, and `OAUTH2_JWKS_URI`

### API
- [ ] The API is served behind a TLS-terminating reverse proxy
- [ ] `CORS_ORIGINS` is set to specific production origins (not `*`)
- [ ] The API port is not publicly accessible without TLS

### Data
- [ ] Every document indexed in OpenSearch has a populated `allowed_users` field
- [ ] PII-containing pipelines use `pii_and_hap` → `redaction` before storage
- [ ] `DS_LOG_LEVEL` is set to `INFO` or higher (not `DEBUG`) in production

### Infrastructure
- [ ] OpenSearch TLS is enabled (`OPENSEARCH_USE_SSL=true`, `OPENSEARCH_VERIFY_CERTS=true`)
- [ ] Default OpenSearch credentials have been changed
- [ ] Ollama and Prefect are not exposed to the public internet
- [ ] Container images run as non-root and are scanned for CVEs

### Operations
- [ ] Authentication and access-denied logs are forwarded to a centralised log store
- [ ] Dependency audit (`uv pip audit`) is scheduled in CI
- [ ] Pre-commit hooks are installed and passing

---

*For related internal implementation details, see [ARCHITECTURE.md — Security Architecture](../../ARCHITECTURE.md#security-architecture).*
