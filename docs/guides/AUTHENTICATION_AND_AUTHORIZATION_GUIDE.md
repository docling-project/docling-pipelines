# Authentication and Authorization Guide

This guide describes how to configure authentication (who the caller is) and authorization (what the caller may do) for
the Docling Pipelines REST API: login methods, roles, group-to-role mapping, the bootstrap administrator, session
cookies and the settings that depend on your network topology.

> **Authentication is on by default.** `DOCPIPE_AUTH_ENABLED` defaults to `true`, so the API refuses to start until
> `JWT_SECRET_KEY` is set, and every `/api/v1/*` request needs a session. To keep the previous open behavior on a
> local, trusted setup, set `DOCPIPE_AUTH_ENABLED=false` explicitly. A blank value keeps the default (`true`).

## Table of Contents

- [Overview](#overview)
- [Quick start](#quick-start)
- [Environment variables](#environment-variables)
- [Roles and permissions](#roles-and-permissions)
- [Group-to-role mapping](#group-to-role-mapping)
- [Bootstrap administrator](#bootstrap-administrator)
- [Sessions, logout and token validity](#sessions-logout-and-token-validity)
- [Login throttling](#login-throttling)
- [Proxy trust and the Secure cookie](#proxy-trust-and-the-secure-cookie)
- [Startup validation](#startup-validation)
- [Public routes](#public-routes)
- [OIDC login](#oidc-login)
- [Discovering the setup with GET /auth/config](#discovering-the-setup-with-get-authconfig)
- [Troubleshooting](#troubleshooting)

---

## Overview

When authentication is enabled, every route under `/api/v1/` requires a session. A session is either:

- an `HttpOnly`, `SameSite=Lax` cookie named `docpipe_access_token` that holds a signed JWT (browsers), or
- an `Authorization: Bearer <token>` header (scripts and API clients). When both are present, the Bearer header wins.

A session is established by one of three login methods, which can run side by side:

| Method | Configured with | Notes |
|--------|-----------------|-------|
| LDAP | `LDAP_*` variables | `POST /auth/login` with username and password |
| OIDC (Google, Azure AD, generic) | `OAUTH2_*` variables | See [OAuth2 and OIDC Authentication](../api/OAUTH2_AUTHENTICATION.md) |
| Bootstrap administrator | `DOCPIPE_AUTH_BOOTSTRAP_*` variables | Break-glass local `admin` login |

Cookie-authenticated `POST`, `PUT`, `PATCH` and `DELETE` requests must carry a non-empty `X-Requested-With` header (CSRF
defense). Bearer requests are exempt.

When authentication is disabled, `/api/v1/*` accepts requests without credentials and treats the caller as a reserved
local principal with the `admin` role. No `JWT_SECRET_KEY` is needed.

> **Set `DOCPIPE_AUTH_ENABLED` before the process starts.** It is read on each request so tests can change it, but you
> must not rely on changing it at runtime.

## Quick start

1. Generate a signing secret of at least 32 characters:

   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

2. Generate a bootstrap administrator hash (see [Bootstrap administrator](#bootstrap-administrator)).

3. Set the variables and start the API:

   ```bash
   export JWT_SECRET_KEY='<64-hex-character-secret-from-step-1>'
   export DOCPIPE_AUTH_BOOTSTRAP_USERNAME=admin
   export DOCPIPE_AUTH_BOOTSTRAP_PASSWORD_HASH='<bcrypt-hash-from-step-2>'
   uvicorn docpipe.api.main:app --host 0.0.0.0 --port 8080
   ```

4. Log in and call the API with the returned token:

   ```bash
   curl -X POST http://localhost:8080/auth/login \
     -H "Content-Type: application/json" \
     -d '{"username": "admin", "password": "<your-password>"}'

   curl http://localhost:8080/api/v1/flows -H "Authorization: Bearer <access_token>"
   ```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DOCPIPE_AUTH_ENABLED` | `true` | Require a session on `/api/v1/*`. Accepts `1`, `true`, `yes`, `on` as true; any other non-blank value is false |
| `JWT_SECRET_KEY` | none | HS256 signing secret. Required when auth is enabled: at least 32 characters, not a placeholder |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Token and cookie lifetime in minutes |
| `DOCPIPE_AUTH_DEFAULT_ROLE` | `viewer` | Role of a user that matches no mapped group. An invalid value falls back to `viewer` |
| `DOCPIPE_AUTH_ROLE_MAPPING_VIEWER` | empty | Groups that grant `viewer`, separated by `;` |
| `DOCPIPE_AUTH_ROLE_MAPPING_EDITOR` | empty | Groups that grant `editor`, separated by `;` |
| `DOCPIPE_AUTH_ROLE_MAPPING_ADMIN` | empty | Groups that grant `admin`, separated by `;` |
| `DOCPIPE_AUTH_COOKIE_NAME` | `docpipe_access_token` | Name of the session cookie |
| `DOCPIPE_AUTH_COOKIE_SECURE` | `false` | Always set the `Secure` attribute on the session cookie |
| `DOCPIPE_TRUST_PROXY_HEADERS` | `false` | Trust `X-Forwarded-For` and `X-Forwarded-Proto` from a reverse proxy |
| `DOCPIPE_AUTH_BOOTSTRAP_USERNAME` | none | Username of the bootstrap administrator. Must be set together with the hash |
| `DOCPIPE_AUTH_BOOTSTRAP_PASSWORD_HASH` | none | bcrypt hash of the bootstrap administrator password |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins. A `*` entry logs a security warning |
| `LDAP_SERVER`, `LDAP_BASE_DN`, `LDAP_USER_DN`, `LDAP_BIND_DN`, `LDAP_BIND_PASSWORD` | empty | LDAP connection. LDAP login is active only when `LDAP_SERVER` is set |
| `LDAP_USE_SSL`, `LDAP_USE_ACTIVE_DIRECTORY`, `LDAP_AD_DOMAIN` | `false`, `false`, empty | LDAP transport and Active Directory options |
| `LDAP_GROUP_ATTRIBUTE` | `memberOf` | Directory attribute that lists a user's groups |
| `OAUTH2_*`, `OIDC_*`, `AZURE_TENANT_ID` | see guide | OIDC providers. See [OAuth2 and OIDC Authentication](../api/OAUTH2_AUTHENTICATION.md) |
| `OAUTH2_GROUP_CLAIM` | empty | OIDC claim that lists groups. When empty, `groups` is read first and then `roles` |
| `DOCPIPE_CONFIG_PATH` | project default | Path to `docling-pipelines-config.yaml`, which can hold the role mapping |

## Roles and permissions

There are three roles, ordered `viewer` < `editor` < `admin`. A user holds a set of roles and the highest one applies. A
higher role includes the rights of the roles below it. Roles are carried in the JWT `roles` claim and returned by
`GET /auth/me`.

| Role | Allowed |
|------|---------|
| `viewer` | Every `GET` under `/api/v1/`, plus the read-only `POST /api/v1/documents/search`, `POST /api/v1/validation/validate_flow` and `POST /api/v1/validation/enrich_flow_features` |
| `editor` | Everything a viewer can do, plus create, update, delete and run flows, projects, event mappings, job runs, document sets and document libraries |
| `admin` | Everything an editor can do, plus upload, update and delete custom operators, because they run arbitrary code |

A request below the required role gets 403, and a request without a valid session gets 401. Every 403 and every
successful create, update and delete is written to the audit log (logger name `docpipe.audit`) with the username,
action, target and outcome.

Ownership adds a second rule on top of roles. Flows and projects record `created_by`, and job runs record `user_id`,
from the session. An editor can update or delete only what they created. An `admin` can modify anything. An asset with
no owner (created before auth was enabled, or through the CLI or the Python library) stays modifiable by any editor.

The command-line interface and the Python library are not affected by roles or ownership.

## Group-to-role mapping

LDAP and OIDC users receive a role from the groups the directory or identity provider reports. A user that matches no
mapping gets the default role, which is `viewer` unless `DOCPIPE_AUTH_DEFAULT_ROLE` says otherwise. A user that matches
several roles gets the highest.

Configure the mapping in the environment, in `docling-pipelines-config.yaml`, or both:

```bash
DOCPIPE_AUTH_ROLE_MAPPING_EDITOR='cn=pipeline-editors,ou=groups,dc=example,dc=com;data-team'
DOCPIPE_AUTH_ROLE_MAPPING_ADMIN='cn=platform-admins,ou=groups,dc=example,dc=com'
```

```yaml
auth:
  role_mapping:
    viewer:
      - analysts
    editor:
      - cn=pipeline-editors,ou=groups,dc=example,dc=com
    admin:
      - cn=platform-admins,ou=groups,dc=example,dc=com
```

Rules and limits:

- **Separator.** Group identifiers in the environment variables are separated by `;`, not `,`, because LDAP
  distinguished names contain commas. A YAML value can be a list or a `;`-separated string.
- **Precedence.** A non-empty `DOCPIPE_AUTH_ROLE_MAPPING_<ROLE>` variable replaces the YAML entry for that role. Roles
  the variables leave empty keep the YAML entry.
- **Matching.** Identifiers are compared as exact strings after trimming whitespace. LDAP distinguished names are
  compared case-insensitively. OIDC group values are case-sensitive.
- **LDAP source.** The API reads the attribute named by `LDAP_GROUP_ATTRIBUTE` (default `memberOf`). Active Directory
  and OpenLDAP with the `memberof` overlay provide it. Plain OpenLDAP without the overlay does not. Nested groups are
  not expanded.
- **OIDC source.** The API reads the claim named by `OAUTH2_GROUP_CLAIM`, or `groups` and then `roles` when it is empty.
  A provider that sends no group claim (Google) leaves every user at the default role. A provider that omits groups when
  a user belongs to too many (Azure AD overage) does the same for those users.
- **Promotion.** A user that cannot be mapped can be promoted only by the bootstrap administrator account, which is a
  separate login.
- **Staleness.** Roles live in the token. A change to a user's groups takes effect at the next login, or when the
  current token expires, up to 30 minutes by default.
- **Startup log.** At startup the API logs which LDAP attribute and which OIDC claims it reads for groups.

Treat `DOCPIPE_AUTH_DEFAULT_ROLE` with care: setting it to `editor` or `admin` gives that role to every authenticated
user that matches no group.

## Bootstrap administrator

The bootstrap administrator is a local `admin` login that does not depend on LDAP or OIDC. It is active only when both
`DOCPIPE_AUTH_BOOTSTRAP_USERNAME` and `DOCPIPE_AUTH_BOOTSTRAP_PASSWORD_HASH` are set. Setting only one, or setting a
hash that is not a valid bcrypt hash, stops startup with a configuration error. It stays active when LDAP or OIDC is
configured, so you can still log in when the directory is unreachable or groups are unmapped.

Generate a bcrypt hash without putting the password on the command line or into your shell history:

```bash
python -c "import bcrypt, getpass; print(bcrypt.hashpw(getpass.getpass().encode(), bcrypt.gensalt()).decode())"
```

The hash begins with `$2b$`. Passwords longer than 72 bytes are rejected at login because bcrypt ignores the rest. In a
`.env` file, wrap the hash in single quotes. In a Docker Compose `environment:` entry, write each `$` as `$$`, or
reference a variable that the operator supplies. Do not commit a real hash, and do not ship a default hash in a Compose
file.

While the account is configured, the API logs a startup warning, and every successful bootstrap login is written to the
audit log. Unset the two variables when you no longer need the account.

## Sessions, logout and token validity

- `POST /auth/login` validates credentials, sets the session cookie and returns `access_token`, `token_type` and the
  `user` (with `roles`). Scripts can use `access_token` as a Bearer token and ignore the cookie.
- `POST /auth/logout` expires the cookie. It succeeds with or without a valid session, so an expired cookie can still be
  cleared. Send `X-Requested-With` from a browser.
- `GET /auth/me` returns the authenticated user and roles.

**There is no server-side token revocation.** Logout clears the cookie in the browser, but a token that was already
issued stays valid until it expires, 30 minutes by default (`JWT_ACCESS_TOKEN_EXPIRE_MINUTES`). Anyone who copied the
token, from a log or a script for example, can use it for that long. Reduce the lifetime for high-security environments.
Rotating `JWT_SECRET_KEY` invalidates all tokens at once.

## Login throttling

`POST /auth/login` counts failed attempts only:

- At most 5 failures per client address per minute. The sixth gets 429 with a `Retry-After` header.
- 5 consecutive failures for the same address and username lock that pair for 5 minutes (429 with `Retry-After`). A
  successful login clears the pair's failures.

The lockout key is the pair of address and username, so an attacker cannot lock a real user out from another address.

The counters live in process memory. They reset on restart and are not shared across workers or replicas, so treat the
limit as a brake on brute-force attempts, not as a security boundary.

## Proxy trust and the Secure cookie

By default the client address is the TCP peer and the cookie's `Secure` attribute depends on the request scheme. Behind
a TLS-terminating reverse proxy both would be wrong: every client appears to come from the proxy, and the API sees plain
HTTP.

The session cookie gets the `Secure` attribute when any of these holds:

- the request itself is HTTPS,
- `DOCPIPE_TRUST_PROXY_HEADERS=true` and the request carries `X-Forwarded-Proto: https`, or
- `DOCPIPE_AUTH_COOKIE_SECURE=true`.

When `DOCPIPE_TRUST_PROXY_HEADERS=true`, the throttle also uses the rightmost `X-Forwarded-For` entry as the client
address. That entry is the one the trusted proxy appended. Earlier entries come from the client and are ignored.

Set `DOCPIPE_TRUST_PROXY_HEADERS=true` only when the API sits behind exactly one ingress or load balancer that appends
to `X-Forwarded-For`. If clients can reach the API directly, they can forge the header and bypass the throttle.

If auth is enabled and neither `DOCPIPE_AUTH_COOKIE_SECURE` nor `DOCPIPE_TRUST_PROXY_HEADERS` is true, the API logs a
warning at startup, because a proxy that terminates TLS would receive a cookie without `Secure`.

> **Warning:** A custom ingress must never route `/auth` to the BFF. `/auth/*` is served by FastAPI only; the BFF has no
> auth routes and would hide the real client address from the login throttle.

## Startup validation

When `DOCPIPE_AUTH_ENABLED` is true, the API refuses to start unless `JWT_SECRET_KEY` is set, is at least 32 characters
and is not a known placeholder. A placeholder is a value that contains text such as `change-this`, `changeme`,
`your-secret`, `replace-me`, `placeholder` or `local-dev-secret`, which is how example files mark their values. The
startup fails with a `ConfigurationError`:

```text
JWT_SECRET_KEY must be set to a value of at least 32 characters when DOCPIPE_AUTH_ENABLED is true. Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
```

```text
JWT_SECRET_KEY is a known placeholder value and must be replaced when DOCPIPE_AUTH_ENABLED is true. Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
```

Another invalid JWT setting, such as a non-numeric `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`, fails with
`Invalid JWT configuration: <field name>`. A bad configuration never disables login silently. The error message never
contains the secret value.

When auth is disabled no secret is needed and the API starts normally.

Two warnings are logged at startup but do not stop it:

- `CORS_ORIGINS` contains `*`: any origin is allowed. Set the explicit origins of your frontend. The API keeps
  `allow_credentials=False` for CORS, because the UI and the API share one origin and cookies need no CORS credentials.
- Auth is enabled with no `Secure` cookie signal (see [Proxy trust and the Secure
  cookie](#proxy-trust-and-the-secure-cookie)).

## Public routes

When auth is enabled these routes stay reachable without a session:

| Route | Purpose |
|-------|---------|
| `GET /`, `GET /health` | Service root and health check |
| `GET /auth/config` | Auth discovery for the login page |
| `POST /auth/login`, `POST /auth/logout` | Login and logout |
| `GET /auth/oauth2/authorize`, `GET /auth/oauth2/callback` | OIDC login round trip |
| `GET /auth/oauth2/providers`, `GET /auth/oauth2/discovery/{provider}` | OIDC provider list and discovery |
| `GET /api/v1/docs`, `GET /api/v1/redoc`, `GET /api/v1/openapi.json` | Interactive API documentation and schema |
| `/ui/*` | Static single-page application files |

Be aware of what this exposes to unauthenticated callers:

- The documentation routes publish the full API schema.
- The OIDC `discovery` route returns the provider's public discovery document, which lists the provider's endpoint
  addresses.
- `GET /auth/oauth2/providers` and `GET /auth/config` return only `name`, `display_name` and `authorize_url` for each
  provider, never client ids, tenant ids or secrets.

`GET /auth/me` and every route under `/api/v1/` other than the documentation routes require a session.

## OIDC login

OIDC provider setup, scopes and endpoints are described in
[OAuth2 and OIDC Authentication](../api/OAUTH2_AUTHENTICATION.md). This section covers what is specific to the session
model.

**Return path.** `GET /auth/oauth2/authorize` accepts `return_to`, a relative path to open after login. `redirect_after`
is a deprecated alias. The callback sets the session cookie and answers with a 302 redirect to the validated path. The
token is no longer placed in the URL fragment (`#access_token=`), so a client that read the fragment must switch to the
cookie. A `return_to` that is absolute, protocol-relative (`//host`), contains a backslash or points at another origin
is ignored. A relative path that does not start with `/ui` gets the `/ui` prefix, and the default is `/ui/projects`.

**Browser binding.** `authorize` also sets a short-lived `HttpOnly` nonce cookie and ties the stored `state` to it. The
callback answers 400 and sets no session when the nonce is missing or different, which stops an attacker from completing
a login in a victim's browser.

**Per-process state store.** The pending `state` values live in the memory of one process, for 10 minutes. In a
deployment with several workers or replicas, the login round trip (`authorize` then `callback`) must reach the same
process. Configure sticky routing for `/auth/oauth2/`. Without it, some logins fail with 400 "Invalid or expired state
parameter".

**Redirect URI per topology.** Register the callback address that the browser reaches:

| Topology | `OAUTH2_REDIRECT_URI` |
|----------|-----------------------|
| Local, wheel or `uvicorn` on port 8080 | `http://localhost:8080/auth/oauth2/callback` |
| Docker Compose or Kubernetes, published port 8080 | `http://localhost:8080/auth/oauth2/callback` (or the public host name) |
| Behind a TLS ingress | `https://<your-domain>/auth/oauth2/callback` |
| Vite development server on port 3000 | `http://localhost:3000/auth/oauth2/callback` |

The path is always `/auth/oauth2/callback`. It is served by FastAPI, never by the BFF.

## Discovering the setup with GET /auth/config

`GET /auth/config` is public and contains no secrets. With auth disabled and no OIDC provider it returns:

```json
{
  "auth_enabled": false,
  "credential_login": false,
  "providers": []
}
```

`credential_login` is `true` when LDAP or the bootstrap administrator is configured and a JWT configuration exists.
Each entry in `providers` has exactly `name`, `display_name` and `authorize_url`, for example:

```json
{
  "name": "google",
  "display_name": "Google",
  "authorize_url": "/auth/oauth2/authorize?provider=google"
}
```

## Troubleshooting

| Symptom | Cause and fix |
|---------|---------------|
| API exits at startup with `JWT_SECRET_KEY must be set...` | Auth is enabled and the secret is unset or shorter than 32 characters. Set a generated secret. |
| API exits at startup with `known placeholder value` | The secret contains example text such as `change-this`. Generate a new one. |
| API exits at startup with `DOCPIPE_AUTH_BOOTSTRAP_USERNAME and ... must be set together` | Only one bootstrap variable is set. Set both or neither. |
| `POST /auth/login` returns 503 | No login method is configured. Set `LDAP_SERVER`, the bootstrap variables or an OIDC provider. |
| `POST /auth/login` returns 429 | Throttled. Wait for `Retry-After` seconds. |
| Browser mutation returns 403 | Cookie requests need an `X-Requested-With` header on `POST`, `PUT`, `PATCH` and `DELETE`. |
| Every user is `viewer` | The mapping is empty or no group matches. Check the startup log for the attribute or claim in use. |
| Cookie is missing `Secure` behind a proxy | Set `DOCPIPE_TRUST_PROXY_HEADERS=true` or `DOCPIPE_AUTH_COOKIE_SECURE=true`. |

## Related Documentation

- [OAuth2 and OIDC Authentication](../api/OAUTH2_AUTHENTICATION.md)
- [REST API Server](../api/REST_API_SERVER.md)
- [Security Best Practices](SECURITY_BEST_PRACTICES.md)
