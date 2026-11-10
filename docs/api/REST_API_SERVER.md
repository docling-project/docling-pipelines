# FastAPI REST API Server

Docling Pipelines ships a FastAPI-based REST API server that exposes pipeline management over HTTP.
It is suitable for programmatic access, UI integrations, and multi-tenant deployments.

> **Status:** Under active development. The interactive docs at `/api/v1/docs` are the
> authoritative source for request/response schemas while the server matures.

## Starting the Server

```bash
# Recommended — uses the installed console entry point
source .venv/bin/activate
docling-pipelines-api

# Alternative — invoke uvicorn directly
source .venv/bin/activate
uvicorn docpipe.api.main:app --reload --host 0.0.0.0 --port 8080

# Or via uv without activating the virtual environment
uv run uvicorn docpipe.api.main:app --reload --host 0.0.0.0 --port 8080
```

Authentication is on by default: the server refuses to start until `JWT_SECRET_KEY` is set (at least 32 random characters). Set `DOCPIPE_AUTH_ENABLED=false` to run without authentication on a local, trusted machine. See the [Authentication and Authorization Guide](../guides/AUTHENTICATION_AND_AUTHORIZATION_GUIDE.md).

Once running, the following URLs are available:

| URL | Description |
|-----|-------------|
| `http://localhost:8080` | Root endpoint |
| `http://localhost:8080/health` | Health check |
| `http://localhost:8080/api/v1/docs` | Swagger UI (interactive API docs) |
| `http://localhost:8080/api/v1/redoc` | ReDoc documentation |
| `http://localhost:8080/api/v1/openapi.json` | Raw OpenAPI schema |

## Authentication

Two authentication paths are supported (plus an optional bootstrap administrator login). Both produce a short-lived JWT
that is sent as the `docpipe_access_token` session cookie by browsers, or as `Authorization: Bearer <token>` by scripts,
on every protected endpoint. See the
[Authentication and Authorization Guide](../guides/AUTHENTICATION_AND_AUTHORIZATION_GUIDE.md).

| Path | Mechanism | Relevant config |
|------|-----------|-----------------|
| LDAP | `POST /auth/login` with `username`/`password` | `LDAPConfig` via environment variables |
| OAuth2 / OIDC | Authorization Code flow with PKCE | See [OAuth2 Authentication](OAUTH2_AUTHENTICATION.md) |

```bash
# Obtain a JWT via LDAP login
curl -X POST http://localhost:8080/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "<your-password>"}'

# Use the token
curl http://localhost:8080/api/v1/flows \
  -H "Authorization: Bearer <token>"
```

See [OAuth2 Authentication](OAUTH2_AUTHENTICATION.md) for full OAuth2/OIDC setup.

## API Endpoints

All data endpoints are prefixed with `/api/v1`.

### Projects — `/api/v1/projects`

Manage projects that group and organise flows. Deleting a project cascade-deletes all flows linked to it.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/projects` | Create a new project |
| `GET` | `/api/v1/projects` | List projects (paginated, filterable by name/tags) |
| `GET` | `/api/v1/projects/{project_id}` | Get a project by ID |
| `PUT` | `/api/v1/projects/{project_id}` | Fully replace a project |
| `PATCH` | `/api/v1/projects/{project_id}` | Partially update a project |
| `DELETE` | `/api/v1/projects/{project_id}` | Delete a project (cascade-deletes linked flows) |
| `GET` | `/api/v1/projects/{project_id}/flows` | List flows belonging to a project, each enriched with aggregated job run status |

### Flows — `/api/v1/flows`

Manage flow definitions (pipeline configurations).

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/flows` | Create a new flow |
| `GET` | `/api/v1/flows` | List flows (paginated) |
| `GET` | `/api/v1/flows/{flow_id}` | Get a flow by ID |
| `PUT` | `/api/v1/flows/{flow_id}` | Replace a flow |
| `PATCH` | `/api/v1/flows/{flow_id}` | Partially update a flow |
| `DELETE` | `/api/v1/flows/{flow_id}` | Delete a flow |
| `DELETE` | `/api/v1/flows` | Bulk delete flows |

### Job Runs — `/api/v1/job_runs`

Create and monitor pipeline executions.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/job_runs` | Create and start a job run |
| `GET` | `/api/v1/job_runs` | List job runs |
| `GET` | `/api/v1/job_runs/{job_run_id}` | Get job run status |
| `POST` | `/api/v1/job_runs/{job_run_id}/cancel` | Cancel a running job |
| `DELETE` | `/api/v1/job_runs/{job_run_id}` | Delete a job run |
| `GET` | `/api/v1/job_runs/{job_run_id}/flow_definition` | Get the flow definition snapshot for a job run |

### Operators — `/api/v1/operators`

Discover available operators and their configuration schemas.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/operators/metadata` | List all operators with metadata |

### Providers — `/api/v1/providers`

Query LLM/embedding provider capabilities.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/providers/{provider}/models` | List available models for a provider (`ollama`, `watsonx`) |

### Document Classes — `/api/v1/document_classes`

Enumerate all document class definitions bundled with the repository.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/document_classes` | List all available document classes |


### Validation — `/api/v1/validation`

Validate a flow definition before submitting it.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/validation/validate_flow` | Validate a flow definition |

### Document Libraries — `/api/v1/document-libraries`

Manage collections of documents with ACL-based access control.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/document-libraries` | Create a document library |
| `GET` | `/api/v1/document-libraries` | List document libraries |
| `GET` | `/api/v1/document-libraries/{library_id}` | Get a document library |
| `PATCH` | `/api/v1/document-libraries/{library_id}` | Update a document library |
| `DELETE` | `/api/v1/document-libraries/{library_id}` | Delete a document library |
| `PUT` | `/api/v1/document-libraries/{library_id}/document-sets` | Add a document set to a library |
| `DELETE` | `/api/v1/document-libraries/{library_id}/document-sets` | Remove a document set from a library |
| `GET` | `/api/v1/document-libraries/{library_id}/document-sets` | List document sets in a library |

### Document Sets — `/api/v1/document-sets`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/document-sets` | Create a document set |
| `GET` | `/api/v1/document-sets` | List document sets |
| `GET` | `/api/v1/document-sets/{set_id}` | Get a document set |
| `PATCH` | `/api/v1/document-sets/{set_id}` | Update a document set |
| `DELETE` | `/api/v1/document-sets/{set_id}` | Delete a document set |
| `GET` | `/api/v1/document-sets/{set_id}/preview` | Preview document set data |

### Documents — `/api/v1/documents`

ACL-filtered document retrieval backed by OpenSearch.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/documents/{document_id}` | Retrieve a single document by ID (ACL-filtered) |
| `POST` | `/api/v1/documents/search` | Search documents (ACL-filtered) |

See [ACL Document Retrieval](ACL_DOCUMENT_RETRIEVAL.md) for full details on ACL enforcement and query options.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DS_LOG_LEVEL` | `INFO` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed CORS origins; a `*` entry logs a security warning at startup |
| `DOCPIPE_AUTH_ENABLED` | `true` | Require a session on `/api/v1/*`; set `false` only for a local, trusted setup |
| `JWT_SECRET_KEY` | — | JWT signing secret; required when auth is enabled (at least 32 characters, not a placeholder) |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Token and session cookie lifetime in minutes |
| `DOCPIPE_AUTH_DEFAULT_ROLE` | `viewer` | Role of an authenticated user that matches no mapped group |
| `DOCPIPE_AUTH_ROLE_MAPPING_VIEWER` / `_EDITOR` / `_ADMIN` | — | Groups per role, separated by `;` |
| `DOCPIPE_AUTH_COOKIE_NAME` | `docpipe_access_token` | Session cookie name |
| `DOCPIPE_AUTH_COOKIE_SECURE` | `false` | Always set `Secure` on the session cookie |
| `DOCPIPE_TRUST_PROXY_HEADERS` | `false` | Trust `X-Forwarded-For` and `X-Forwarded-Proto` from one reverse proxy |
| `DOCPIPE_AUTH_BOOTSTRAP_USERNAME` / `DOCPIPE_AUTH_BOOTSTRAP_PASSWORD_HASH` | — | Break-glass `admin` login; set both or neither |
| `PROJECT_REPOSITORY_BASE_DIR` | — | Override project storage directory (takes precedence over `docling-pipelines-config.yaml`) |
| `DOCPIPE_POSTGRES_*` | — | PostgreSQL backend for job stats (see [Environment Variables](../../USER_GUIDE_PIPELINE_SETUP.md)) |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama host used by `GET /providers/ollama/models` |
| `WATSONX_API_BASE_URL` | — | WatsonX base URL used by `GET /providers/watsonx/models` (required — no default) |

Authentication variables, roles and startup validation are documented in the
[Authentication and Authorization Guide](../guides/AUTHENTICATION_AND_AUTHORIZATION_GUIDE.md). OIDC variables are
documented in [OAuth2 Authentication](OAUTH2_AUTHENTICATION.md).

## Security

The server applies several hardening measures out of the box:

- **Security headers** — `X-Content-Type-Options`, `X-Frame-Options`, `Content-Security-Policy`,
  and `Referrer-Policy` are added to every response.
- **Payload size limit** — `POST`/`PUT`/`PATCH` requests exceeding 5 MB are rejected (HTTP 413).
- **ACL enforcement** — Document endpoints automatically filter results to the authenticated user's
  allowed documents (returns 404 for unauthorized resources, not 403, to prevent information leakage).
- **JWT tokens** — Short-lived, validated on every protected request.

See [Security Best Practices](../guides/SECURITY_BEST_PRACTICES.md) for production hardening
(TLS termination, reverse proxy, etc.).

## Related Documentation

- [OAuth2 Authentication](OAUTH2_AUTHENTICATION.md) — OAuth2 / OIDC provider setup
- [ACL Document Retrieval](ACL_DOCUMENT_RETRIEVAL.md) — ACL-based document access
- [Security Best Practices](../guides/SECURITY_BEST_PRACTICES.md) — Production security
- [Document Libraries Guide](../guides/USER_GUIDE_DOCUMENT_LIBRARIES.md) — Managing document collections
- [Architecture Overview](../../ARCHITECTURE.md#1-rest-api-authentication) — Security model and authentication flows
