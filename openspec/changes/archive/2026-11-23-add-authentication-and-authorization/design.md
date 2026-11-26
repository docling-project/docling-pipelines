# Design

## Context

See `proposal.md` for motivation and scope. Current state that shapes the approach:

- `src/docpipe/api/auth/` already provides HS256 JWT creation and verification, an LDAP authenticator, OAuth2/OIDC providers and routes, and `dependencies.py`. Only `documents.py` uses `Depends(get_current_user)`. `api_router.py` registers 12 sub-routers with no shared dependency.
- `dependencies.py` uses `HTTPBearer()` with `auto_error=True`, so a request with no `Authorization` header is rejected before any cookie could be read. `tests/unit/auth/test_dependencies.py::test_token_in_cookie_is_not_accepted` asserts that cookies are not honored; this change reverses that rule.
- `oauth2_routes.py` returns the token as `#access_token=` in the redirect URL.
- `Flow.created_by` and `Project.created_by` exist in the domain models and schemas, but `FlowService` and `ProjectService` never set or check them.
- `core/` must not import `docpipe.api.*` (DDD layering in `AGENTS.md`). The CLI and `DocpipeFlowManager` call the same services with no caller identity.
- The BFF controllers send only static `Accept` and `Content-Type` headers, so `Cookie` never reaches FastAPI. `app.listen(PORT)` has no host. In wheel, Compose and Kubernetes deployments the browser talks to FastAPI, which serves `/ui` and `/auth/*` and reverse-proxies `/api/*` to the BFF. The BFF serves only `/api` and `/health`.
- `EventDispatchService` resolves the saved flow through `FlowService` and runs it in process through `StreamingOrchestrator.execute()`. It makes no HTTP call to the API, so the REST guards and `ActorContext` checks never run for event-triggered runs.
- `docker/docker-compose.yml` and `docker/all-in-one-deployment/docker-compose.yml` configure neither LDAP nor OIDC.
- `bcrypt==5.0.0` is locked; `passlib==1.7.4` is incompatible with it.
- `rate_limit.py` is a per-IP in-memory sliding window, not thread-safe, and keyed on the TCP peer.
- `main.py` wraps JWT setup in an `except` block that silently disables login on a configuration error.
- `documents.py` builds its `allowed_users` ACL filter from the username of `get_current_user`.

## Goals / Non-Goals

**Goals:**
- Reuse the existing LDAP, OIDC, JWT and rate-limit code; add no new runtime dependency and no new user store.
- Keep every intermediate state of the rollout usable, and keep all existing tests passing with auth off.
- Put ownership rules in services behind a framework-free actor type so CLI and library callers are unchanged.

**Non-Goals:**
- Anything listed under the proposal's Non-goals.
- A pluggable session-store abstraction. The single process limits above are documented instead.

## Decisions

### D1. Extend the existing stack; no local identity model
Reuse `LDAPAuthenticator`, the OIDC providers and the JWT handler. Do not add a `users` table, a `refresh_tokens` table, `/auth/refresh`, registration or password reset.
*Why:* the issue lists these as non-goals; a data-pipeline engine should not become an identity provider; LDAP/OIDC already exist.
*Alternative:* a local users table. Rejected for the added storage, migration, reset flows and attack surface.

### D2. Router-level session dependency that delegates to `get_current_user`
Add `require_session` and `require_role(min_role)` and attach the session dependency once on `api_router`. `require_session` calls `get_current_user` through `Depends`, so the existing route tests that override `get_current_user` keep working. When `DOCPIPE_AUTH_ENABLED=false`, `get_current_user` returns a reserved local principal with the `admin` role and a username that no login can produce, so routes that inject `get_current_user` directly (such as `documents.py`) also work with auth disabled. The documents ACL filter treats that principal explicitly: it sees every document when auth is off, and the reserved name matches no `allowed_users` entry when auth is on. A literal `admin` username would be a name a real LDAP user could also hold, so the principal gets a reserved name instead. Tests that assert 401 behavior explicitly opt into the `auth_enabled` fixture. Stricter role dependencies are attached per route. FastAPI's built-in documentation routes (`/api/v1/docs`, `/api/v1/redoc`, `/api/v1/openapi.json`, `/api/v1/docs/oauth2-redirect`) are non-`APIRoute` Starlette routes and are explicitly accounted for in the route-inventory check. The unused `/protected` demo route in `main.py` is removed.
*Alternative:* a global ASGI middleware. Rejected: it hides which routes are protected, bypasses FastAPI's dependency overrides, and makes the route-inventory test impossible.

### D3. Bearer first, cookie second; `auth_source` recorded; `Secure` flag detection
Switch to `HTTPBearer(auto_error=False)`. Read the Bearer header, then the cookie, and store `request.state.auth_source` as `cookie`, `bearer` or `disabled`. The CSRF check keys off `auth_source == "cookie"`. The cookie is named `docpipe_access_token` (the old test used `access_token`). The `Secure` cookie attribute is set when `request.url.scheme == "https"`, when `DOCPIPE_TRUST_PROXY_HEADERS=true` and `X-Forwarded-Proto == "https"`, or when `DOCPIPE_AUTH_COOKIE_SECURE=true` is explicitly configured. `POST /auth/login` sets the cookie and returns `user` with `roles`; for browser requests (when `X-Requested-With` is present) it omits `access_token` from the JSON response body so the token is held only in the `HttpOnly` cookie, returning `access_token` in the JSON body only to non-browser clients (preserving compatibility for scripts and Bearer API clients). Authenticated identities use provider-prefixed canonical usernames (`ldap:<uid>`, `oidc:<provider>:<sub>`, `bootstrap:<username>`) across the JWT, `ActorContext`, `GET /auth/me`, and ownership fields so identities cannot collide across providers. If auth is enabled and none of those `Secure` signals can apply, startup logs a warning, because a TLS-terminating proxy with the flag off would issue a cookie without `Secure`. `CORSMiddleware` keeps `allow_credentials=False`: the SPA and the API share one origin, so cookies need no CORS credentials, and the wildcard methods and headers stay uncredentialed.
*Why the header wins:* an explicit `Authorization` header is a deliberate choice by the caller. Treating the request as Bearer also keeps a stray cookie from adding the CSRF requirement to a script call. A browser sends only the cookie, so its behavior is unchanged.

### D4. Stateless CSRF with `SameSite=Lax` plus `X-Requested-With`
Require a non-empty `X-Requested-With` on cookie-authenticated `POST/PUT/PATCH/DELETE`. A cross-origin page cannot add a custom header without a CORS preflight that the allowed-origin list refuses. Every frontend action module already sends the header.
*Alternative:* synchronizer tokens. Rejected: needs server state and a token endpoint; no added protection over custom-header plus `SameSite` for this API shape.

### D5. Roles live in the JWT; mapping is configuration
Add a `roles` claim. Group-to-role mapping comes from `docling-pipelines-config.yaml` and `DOCPIPE_AUTH_ROLE_MAPPING_*` variables, with `DOCPIPE_AUTH_DEFAULT_ROLE=viewer` as the fail-closed default. LDAP reads the configurable `memberOf` attribute; OIDC reads a configurable claim, default `groups` then `roles`. Group identifiers are compared as trimmed exact strings, and LDAP distinguished names case-insensitively. Plain OpenLDAP without the `memberof` overlay and nested group expansion are out of scope. Startup logs the claim and attribute in use. Providers that send no group claim (Google) or omit groups on overage (Azure) leave users as `viewer`, and only the bootstrap administrator can promote them.
*Trade-off:* roles go stale for up to the token lifetime (30 minutes). Accepted and documented in place of a refresh mechanism.

### D6. `ActorContext` and `SYSTEM_ACTOR` in `core/`, fail-closed ownership, and operator containment
Define a frozen `ActorContext(username, roles)`, a reserved `SYSTEM_ACTOR` sentinel, and a pure `can_modify(actor, owner)` under `core/models/`. `can_modify` and service write methods on `FlowService`, `ProjectService`, and `JobManagementService` fail closed and require an explicit `ActorContext` (there is no `actor=None` bypass). Internal callers, the CLI, `DocpipeFlowManager`, and `EventDispatchService` explicitly pass `SYSTEM_ACTOR`, which `can_modify` always permits. On create, `created_by` (for flows and projects) and `user_id` (for job runs) are set from `actor.username` when the actor is a user principal, and left empty/default when the caller passes `SYSTEM_ACTOR` or when auth is disabled so enabling auth later leaves old assets and runs editable. On update (`PUT`/`PATCH`), `modified_by` is set to `actor.username` for user principals. In `JobManagementService`, `list_job_runs` includes `user_id` in its response projection, and `cancel_job_run` / `delete_job_run` fetch the job run stats first and verify `can_modify(actor, job_stats.user_id)`. In `ProjectService.delete_project`, the project is fetched first and `can_modify(actor, project.created_by)` is verified, along with `can_modify(actor, flow.created_by)` for every child flow in the project, before any child flows or the project itself are deleted, preventing partial/orphaned deletes when another editor owns a flow inside the project. Once verified, the cascade calls `bulk_delete_flows` with `actor=SYSTEM_ACTOR`. A refusal raises a domain `PermissionDeniedException` mapped to 403 in the error handler. Routes build the actor from the session. The service sets `modified_by` itself and ignores any client value. A bulk-delete failure entry gives a generic permission reason and never names the other owner. The ownership check and the cascade in `delete_project` are not atomic, so a child flow added between them can be deleted; this race is accepted for v1. Ownerless assets stay editable by any editor until an operator backfills `created_by`. In addition, because `editor`s can author and run flows, when `DOCPIPE_AUTH_ENABLED=true`, `sql_filter` disables DuckDB external file access (`enable_external_access = false`) so SQL expressions cannot read arbitrary host files, and `ingest_source` (`filesystem` provider) restricts resolved paths to configured allowed roots (`DOCPIPE_INGEST_ALLOWED_PATHS`, defaulting to the data directory).
*Alternative:* check ownership in routes or allow `actor=None`. Rejected by the issue and by DDD layering; `actor=None` could accidentally bypass checks if a future route omits the argument.

### D7. Logout clears the cookie; no server-side revocation in v1
`POST /auth/logout` expires the cookie. The report from the design debate proposed a `jti` denylist behind a `TokenRevocationPort` with an in-memory store. This design does not adopt it: the store is per-process and lost on restart, so it gives a false sense of invalidation in the multi-worker deployments the Prefect orchestrator targets, while a stolen token remains valid for at most 30 minutes either way. The issue asks only for logout. Users and the setup guide are told that an issued token stays valid for up to 30 minutes. `POST /auth/logout` succeeds without a valid session so that an expired cookie can still be cleared.
*Follow-up:* add `jti` and a shared-store revocation port if multi-replica deployments need it.

### D8. OIDC callback sets the cookie, resolves `/ui` paths, and enforces PKCE, ID-token nonce, and verified email
Accept `return_to` on `/auth/oauth2/authorize` (keeping `redirect_after` as a backward-compatible alias). Replace the fragment redirect in `/auth/oauth2/callback` with a `Set-Cookie` and a 302 redirect to a validated `return_to`. Accept only values starting with a single `/` and not `//`, with no scheme, host or backslash. Because the SPA is mounted under `/ui` while React Router strips the `/ui` basename from `location.pathname`, any valid relative `return_to` path that does not already start with `/ui/` (or equal `/ui`) is prefixed with `/ui`, and an absent or invalid `return_to` defaults to `/ui/projects`. `/auth/oauth2/authorize` generates a PKCE `code_verifier` (sending an `S256` `code_challenge`), an OIDC `nonce` parameter, and a short-lived `HttpOnly` browser cookie tied to the stored `state`. The callback exchanges the code with `code_verifier`, validates the ID-token `nonce` claim against the stored `nonce`, and rejects a missing or mismatched browser cookie or ID-token `nonce`, stopping login CSRF and authorization-code interception. Canonical OIDC identities use `oidc:<provider>:<sub>`; when falling back to an `email` claim for the identifier, `email_verified` must be `true` or authentication is rejected. The `state` store is in-memory and per process, so the setup guide states that a multi-worker deployment needs sticky routing for the login round trip. Update the existing callback tests.

### D9. Authenticator port with a bootstrap administrator
`POST /auth/login` goes through an `AuthenticatorPort` (`authenticate(*, username, password)`), with LDAP as the primary adapter (emitting `ldap:<uid>` identities) and a `BootstrapAdminAuthenticator` as a second (emitting `bootstrap:<username>` identities). The bootstrap adapter is active only when both environment variables are set, verifies with `bcrypt.checkpw` directly, rejects passwords over 72 bytes before calling bcrypt, always grants `admin`, and fails startup on partial or invalid configuration. It stays active when LDAP or OIDC is configured, because a break-glass login is its main value, and every successful bootstrap login is audited. Compose files reference operator-supplied variables and ship no default hash.
*Why:* without it, default-on auth leaves every stock Compose deployment unable to log in.
*Alternative:* make LDAP/OIDC mandatory for default-on. Rejected: breaks evaluation and local use.
*Alternative:* `passlib`. Rejected: incompatible with locked bcrypt 5.

### D10. Harden the existing rate limiter in place and configurable trusted-proxy hops
Keep `rate_limit.py` and add a lock, bounded entries, failed-only counting, lockout and `Retry-After`. The lockout key is the pair of client address and username, so an attacker cannot lock a real user out from another address. The client address is the TCP peer unless `DOCPIPE_TRUST_PROXY_HEADERS=true`, in which case it selects the `X-Forwarded-For` entry `DOCPIPE_TRUSTED_PROXY_COUNT` hops from the right (defaulting to `1`, the address appended by the innermost trusted proxy). Earlier client-controlled entries are ignored. Login does not pass through the BFF, so the peer is the real client or the ingress. Operators behind one or more trusted proxies set `DOCPIPE_TRUST_PROXY_HEADERS=true` and configure `DOCPIPE_TRUSTED_PROXY_COUNT` to match their proxy chain, and the same trust flag drives the `Secure` cookie decision. No `slowapi` or Redis. Both the rate-limiter state and concurrent LDAP bind limits are enforced per process and documented as per-process limits in the setup guide.

### D11. In-process event dispatch uses `SYSTEM_ACTOR` and needs no system credential
`EventDispatchService` runs mapped flows in process and calls `FlowService.get_flow` (and downstream services) with `SYSTEM_ACTOR`, which D6 defines as an internal caller sentinel that is always allowed. No token is minted. The trust boundary is the Kafka listener and its broker configuration, not the REST API. Event mappings stay protected by the `editor` guard on the REST routes that create them.
*Alternative:* mint a system token as the earlier design did. Rejected: there is no HTTP call to attach it to, and a token that is never verified would be dead code.

### D12. Audit through the existing logger
Authorization denials and successful writes are logged via `get_logger()` with username, action, target and outcome, in `%s` style. Failed writes such as 404 and 409 are logged with the same fields and the status code. Usernames and targets from untrusted sources have newlines and control characters removed first. Secrets and tokens are never logged. No new audit store.

### D13. BFF: one header helper, no auth controller
Add `buildForwardHeaders(req, base)` forwarding `Cookie`, `Authorization`, `X-Requested-With` and `X-Transaction-ID`, and use it in every controller, including the handlers that set their own `Accept` header. Do not forward `X-Forwarded-For` or `X-Forwarded-Proto`: no data route reads them, and passing client-supplied values through would be a spoofing path if proxy trust were ever on. Fix the streamed report download so an upstream 401 or 403 returns its status with a JSON body instead of throwing inside the `catch`. Default bind is `127.0.0.1`, overridable with `BFF_HOST`; the BFF container image sets `BFF_HOST=0.0.0.0`, which also covers the Kubernetes sidecar probes that use the pod address.
*No auth controller:* a follow-up debate (PR review point 13) found that in wheel, Compose and Kubernetes the browser talks to FastAPI, which already serves `/ui` and `/auth/*`. A BFF auth route would add a FastAPI to BFF to FastAPI loop, hide the real client address from the login throttle, force the OIDC redirect URI onto a `/api/auth/oauth2/callback` path that the docs and tests do not use, and fail outright in the all-in-one Compose stack, which has no BFF. Only the Vite dev server puts the browser on another origin, and an `/auth` proxy entry there covers it. In development the OIDC redirect URI is `http://localhost:3000/auth/oauth2/callback`.
*Follow-up:* if a BFF route ever sets a cookie, `proxy_to_bff` in `api/main.py` collapses repeated `Set-Cookie` headers and must switch to `multi_items()`.

### D14. Frontend state, shell layout and gating
A new `authSlice` follows the existing slice pattern and stores only the `user` object (never `access_token`). `useAuth` reads it and computes `canEdit` and `canAdmin`. `App.tsx` separates the `/login` route from the authenticated shell layout so `AppHeader` and `Breadcrumb` do not render on `/ui/login`. `ProtectedRoute` keeps its structure, but switches from router `state.from` to a `return_to` query parameter, because a full-page OIDC round trip cannot carry router state. The login page uses Carbon `Form`, `TextInput`, `PasswordInput`, `Button` and `InlineNotification` with SCSS Modules and Carbon tokens. `apiClient` gains `withCredentials`, a module-level latch so concurrent 401s navigate once, and a 403 toast through `notificationsSlice`. Row-level ownership gating compares `created_by` with the username, with `canAdmin` as override. This gating is a convenience only: the backend is the authority, and every action the UI hides has a backend test that expects 403. The login page uses the `authorize_url` from `GET /auth/config`, whose provider entries carry only `name`, `display_name` and `authorize_url`.

### D15. Rollout order keeps each step usable
The specs describe the end state, where the default is `true`. In implementation the default flips to `true` only in the last phase, so every intermediate state stays usable. This is an implementation detail.

1. Backend auth core, with the default still `false`: roles, session dependency, cookie, CSRF, routes, throttling, ownership, bootstrap admin, tests. Nothing changes for existing users.
2. BFF forwarding, the report-download fix, the `BFF_HOST` image setting and the Vite `/auth` proxy.
3. Frontend slice, login page, protected routes, client interceptors, gated actions.
4. Flip the default to `true`, update Compose files and docs, add the route-inventory guard.

*Why:* flipping first would 401 every UI call before a login page exists.

## Risks / Trade-offs

- [Existing tests rely on no auth] → Autouse fixture in `tests/conftest.py` sets `DOCPIPE_AUTH_ENABLED=false`; the setting is read per request so `monkeypatch` works; the `get_current_user` override path is preserved (D2).
- [Default-on breaks scripts and deployments] → Documented as **BREAKING** with the one-line opt-out; Bearer keeps working; Compose files gain the bootstrap variables and a documented placeholder secret flow.
- [Stolen token valid until expiry] → 30-minute lifetime, `HttpOnly`, `SameSite=Lax`, `Secure` over HTTPS; revocation deferred (D7).
- [Role staleness up to token lifetime] → Documented; short TTL.
- [In-memory throttling and LDAP bind concurrency limits not shared across workers, and lost on restart] → Documented; acceptable as brute-force slowing, not a security boundary.
- [Proxy header spoofing if `DOCPIPE_TRUST_PROXY_HEADERS` or `DOCPIPE_TRUSTED_PROXY_COUNT` is misconfigured] → Off by default; selects the entry `DOCPIPE_TRUSTED_PROXY_COUNT` (default `1`) hops from the right; documented to match the exact number of trusted proxies.
- [`Secure` cookie missing behind a TLS-terminating proxy] → Startup warning; documented to set `DOCPIPE_TRUST_PROXY_HEADERS=true` or `DOCPIPE_AUTH_COOKIE_SECURE=true`.
- [OIDC `state` store is per process] → Documented; the nonce cookie stops login CSRF either way.
- [Public docs and OIDC discovery routes reveal the API schema and provider endpoints] → Documented in the setup guide; `providers` and `/auth/config` expose no client or tenant ids.
- [Open redirect through `return_to`] → Strict same-origin relative-path validation on server and client, with tests.
- [Locked-out loop if the secret is weak] → Startup validation fails fast with a clear message rather than serving 503s.
- [Group claims differ per provider; Azure may truncate on overage; Google emits none] → Mapping is configurable and the limits are documented; unmapped users get `viewer`.
- [The OIDC callback change breaks any client reading `#access_token`] → Marked **BREAKING**; the old behavior contradicted #462.
- [Mixed tabs across a logout] → Other tabs get 401 and redirect once through the latch.

## Migration Plan

1. Merge phases 1 to 3 with `DOCPIPE_AUTH_ENABLED` defaulting to `false`; deploy freely.
2. Configure `JWT_SECRET_KEY` (32+ characters), the group mapping, and either LDAP, an OIDC provider, or the bootstrap administrator.
3. Merge phase 4 to flip the default. Environments that must stay open set `DOCPIPE_AUTH_ENABLED=false`.
4. Rollback: set `DOCPIPE_AUTH_ENABLED=false` and restart; no data migration is involved. Existing `created_by` values remain valid either way.

## Open Questions

- Should a follow-up add a shared-store revocation port for multi-replica deployments (D7)?
- Should event-triggered runs record an owner or an audit entry, which requires a way to attribute a Kafka event to a user (D11)?
