# Design

## Context

See `proposal.md` for motivation and scope. Current state that shapes the approach:

- `src/docpipe/api/auth/` already provides HS256 JWT creation and verification, an LDAP authenticator, OAuth2/OIDC providers and routes, and `dependencies.py`. Only `documents.py` uses `Depends(get_current_user)`. `api_router.py` registers 12 sub-routers with no shared dependency.
- `dependencies.py` uses `HTTPBearer()` with `auto_error=True`, so a request with no `Authorization` header is rejected before any cookie could be read. `tests/unit/auth/test_dependencies.py::test_token_in_cookie_is_not_accepted` asserts that cookies are not honored; this change reverses that rule.
- `oauth2_routes.py` returns the token as `#access_token=` in the redirect URL.
- `Flow.created_by` and `Project.created_by` exist in the domain models and schemas, but `FlowService` and `ProjectService` never set or check them.
- `core/` must not import `docpipe.api.*` (DDD layering in `AGENTS.md`). The CLI and `DocpipeFlowManager` call the same services with no caller identity.
- The BFF controllers send only static `Accept` and `Content-Type` headers, so `Cookie` never reaches FastAPI. `app.listen(PORT)` has no host. FastAPI's `proxy_to_bff` rebuilds headers with a dict comprehension, which collapses repeated `Set-Cookie`.
- `EventDispatchService` calls `POST {api}/api/v1/job_runs` over HTTP with no credentials.
- `docker/docker-compose.yml` and `docker/all-in-one-deployment/docker-compose.yml` configure neither LDAP nor OIDC.
- `bcrypt==5.0.0` is locked; `passlib==1.7.4` is incompatible with it.
- `rate_limit.py` is a per-IP in-memory sliding window, not thread-safe, and keyed on the TCP peer.

## Goals / Non-Goals

**Goals:**
- Reuse the existing LDAP, OIDC, JWT and rate-limit code; add no new runtime dependency and no new user store.
- Keep every intermediate state of the rollout usable, and keep all existing tests passing with auth off.
- Put ownership rules in services behind a framework-free actor type so CLI and library callers are unchanged.

**Non-Goals:**
- Anything listed under the proposal's Non-goals.
- A pluggable session-store abstraction. The single process limits above are documented instead.

## Decisions

### D1. Extend the existing stack; drop the #5953 identity model
Reuse `LDAPAuthenticator`, the OIDC providers and the JWT handler. Do not add a `users` table, a `refresh_tokens` table, `/auth/refresh`, registration or password reset.
*Why:* #462 lists these as non-goals; a data-pipeline engine should not become an identity provider; LDAP/OIDC already exist.
*Alternative:* a local users table (#5953). Rejected for the added storage, migration, reset flows and attack surface.

### D2. Router-level session dependency that delegates to `get_current_user`
Add `require_session` and `require_role(min_role)` and attach the session dependency once on `api_router`. `require_session` calls `get_current_user` through `Depends`, so the nine existing route tests that override `get_current_user` keep working. When `DOCPIPE_AUTH_ENABLED=false`, `get_current_user` returns a synthetic local administrator (`username="admin"`, `roles=[Role.ADMIN]`), so routes that inject `get_current_user` directly (such as `documents.py`) also work with auth disabled; tests that assert 401 behavior explicitly opt into the `auth_enabled` fixture. Stricter role dependencies are attached per route. FastAPI's built-in documentation routes (`/api/v1/docs`, `/api/v1/redoc`, `/api/v1/openapi.json`, `/api/v1/docs/oauth2-redirect`) are non-`APIRoute` Starlette routes and are explicitly accounted for in the route-inventory check. The unused `/protected` demo route in `main.py` is removed.
*Alternative:* a global ASGI middleware. Rejected: it hides which routes are protected, bypasses FastAPI's dependency overrides, and makes the route-inventory test impossible.

### D3. Cookie first, Bearer second; `auth_source` recorded; `Secure` flag detection
Switch to `HTTPBearer(auto_error=False)`. Read the cookie, then the Bearer header, and store `request.state.auth_source` as `cookie`, `bearer` or `disabled`. The CSRF check keys off `auth_source == "cookie"`. The cookie is named `docpipe_access_token` (the old test used `access_token`). The `Secure` cookie attribute is set when `request.url.scheme == "https"`, when `DOCPIPE_TRUST_PROXY_HEADERS=true` and `X-Forwarded-Proto == "https"`, or when `DOCPIPE_AUTH_COOKIE_SECURE=true` is explicitly configured. `POST /auth/login` sets the cookie and returns both `access_token` (preserving compatibility for scripts and Bearer API clients) and `user` with `roles` (while the frontend `authSlice` stores only `user`). `CORSMiddleware` sets `allow_credentials=True` when `allowed_origins` does not contain `"*"`.
*Why cookie wins:* a browser has only the cookie; a script has only the header; if both exist the browser one is the intended session.

### D4. Stateless CSRF with `SameSite=Lax` plus `X-Requested-With`
Require a non-empty `X-Requested-With` on cookie-authenticated `POST/PUT/PATCH/DELETE`. A cross-origin page cannot add a custom header without a CORS preflight that the allowed-origin list refuses. Every frontend action module already sends the header.
*Alternative:* synchronizer tokens (#5953). Rejected: needs server state and a token endpoint; no added protection over custom-header plus `SameSite` for this API shape.

### D5. Roles live in the JWT; mapping is configuration
Add a `roles` claim. Group-to-role mapping comes from `docling-pipelines-config.yaml` and `DOCPIPE_AUTH_ROLE_MAPPING_*` variables, with `DOCPIPE_AUTH_DEFAULT_ROLE=viewer` as the fail-closed default. LDAP reads the configurable `memberOf` attribute; OIDC reads a configurable claim, default `groups` then `roles`. Plain OpenLDAP without the `memberof` overlay and nested group expansion are out of scope.
*Trade-off:* roles go stale for up to the token lifetime (30 minutes). Accepted and documented in place of a refresh mechanism.

### D6. `ActorContext` in `core/`, ownership as a pure function
Define a frozen `ActorContext(username, roles)` and a pure `can_modify(actor, owner)` under `core/models/`. Services take `*, actor: ActorContext | None = None`. `None` means CLI, library or internal and is always allowed. On create, `created_by` (for flows and projects) and `user_id` (for job runs) are set from `actor.username` when an actor exists; otherwise they stay empty/default so enabling auth later leaves old assets and runs editable. On update (`PUT`/`PATCH`), `modified_by` is set to `actor.username` when an actor exists. In `JobManagementService`, `list_job_runs` includes `user_id` in its response projection, and `cancel_job_run` / `delete_job_run` fetch the job run stats first and verify `can_modify(actor, job_stats.user_id)`. In `ProjectService.delete_project`, the project is fetched first and `can_modify(actor, project.created_by)` is verified—along with `can_modify(actor, flow.created_by)` for every child flow in the project—before any child flows or the project itself are deleted, preventing partial/orphaned deletes when another editor owns a flow inside the project. Once verified, the cascade calls `bulk_delete_flows` with `actor=None`. A refusal raises a domain `PermissionDeniedException` mapped to 403 in the error handler. Routes build the actor from the session.
*Alternative:* check ownership in routes. Rejected by the issue and by DDD layering; it would also leave the library path unguarded in future callers.

### D7. Logout clears the cookie; no server-side revocation in v1
`POST /auth/logout` expires the cookie. The report from the design debate proposed a `jti` denylist behind a `TokenRevocationPort` with an in-memory store. This design does not adopt it: the store is per-process and lost on restart, so it gives a false sense of invalidation in the multi-worker deployments the Prefect orchestrator targets, while a stolen token remains valid for at most 30 minutes either way. #462 asks only for logout.
*Follow-up:* add `jti` and a shared-store revocation port if multi-replica deployments need it.

### D8. OIDC callback sets the cookie and resolves `/ui` paths
Accept `return_to` on `/auth/oauth2/authorize` (keeping `redirect_after` as a backward-compatible alias). Replace the fragment redirect in `/auth/oauth2/callback` with a `Set-Cookie` and a 302 redirect to a validated `return_to`. Accept only values starting with a single `/` and not `//`, with no scheme, host or backslash. Because the SPA is mounted under `/ui` while React Router strips the `/ui` basename from `location.pathname`, any valid relative `return_to` path that does not already start with `/ui/` (or equal `/ui`) is prefixed with `/ui`, and an absent or invalid `return_to` defaults to `/ui/projects`. Update the existing callback tests.

### D9. Authenticator port with a bootstrap administrator
`POST /auth/login` goes through an `AuthenticatorPort` (`authenticate(*, username, password)`), with LDAP as the primary adapter and a `BootstrapAdminAuthenticator` as a second. The bootstrap adapter is active only when both environment variables are set, verifies with `bcrypt.checkpw` directly, rejects passwords over 72 bytes before calling bcrypt, always grants `admin`, and fails startup on partial or invalid configuration.
*Why:* without it, default-on auth leaves every stock Compose deployment unable to log in.
*Alternative:* make LDAP/OIDC mandatory for default-on. Rejected: breaks evaluation and local use.
*Alternative:* `passlib`. Rejected: incompatible with locked bcrypt 5.

### D10. Harden the existing rate limiter in place
Keep `rate_limit.py` and add a lock, bounded entries, failed-only counting, per-username lockout and `Retry-After`. Client address comes from the TCP peer unless `DOCPIPE_TRUST_PROXY_HEADERS=true`, because behind the BFF every request would otherwise share `127.0.0.1`. No `slowapi` or Redis. Limits stay per-process and are documented as such.

### D11. Internal calls use a system token
`EventDispatchService` mints a short-lived admin token with the existing JWT handler and sends it as `Authorization: Bearer`. Bearer requests are exempt from the CSRF header rule.
*Alternative:* call the job service in-process. Cleaner, but a larger refactor of the event path; revisit separately.

### D12. Audit through the existing logger
Authorization denials and successful writes are logged via `get_logger()` with username, action, target and outcome, in `%s` style. Secrets and tokens are never logged. No new audit store.

### D13. BFF: one header helper, a dedicated auth controller
Add `buildForwardHeaders(req, base)` (forwarding `Cookie`, `Authorization`, `X-Requested-With`, `X-Transaction-ID`, `X-Forwarded-For` and `X-Forwarded-Proto`) and use it in all controllers; add `auth-controller.ts` for `/api/auth/*` that relays all `Set-Cookie` values and passes 3xx through without following them (`maxRedirects: 0`). Default bind is `127.0.0.1`, overridable with `BFF_HOST`. Fix `proxy_to_bff` to copy headers with `multi_items()` and append.

### D14. Frontend state, shell layout and gating
A new `authSlice` follows the existing slice pattern and stores only the `user` object (never `access_token`). `useAuth` reads it and computes `canEdit` and `canAdmin`. `App.tsx` separates the `/login` route from the authenticated shell layout so `AppHeader` and `Breadcrumb` do not render on `/ui/login`. `ProtectedRoute` keeps its structure, but switches from router `state.from` to a `return_to` query parameter, because a full-page OIDC round trip cannot carry router state. The login page uses Carbon `Form`, `TextInput`, `PasswordInput`, `Button` and `InlineNotification` with SCSS Modules and Carbon tokens. `apiClient` gains `withCredentials`, a module-level latch so concurrent 401s navigate once, and a 403 toast through `notificationsSlice`. Row-level ownership gating compares `created_by` with the username, with `canAdmin` as override.

### D15. Rollout order keeps each step usable
The default flips to `true` only in the last phase.

1. Backend auth core, with the default still `false`: roles, session dependency, cookie, CSRF, routes, throttling, ownership, bootstrap admin, tests. Nothing changes for existing users.
2. BFF forwarding and auth routes.
3. Frontend slice, login page, protected routes, client interceptors, gated actions.
4. Flip the default to `true`, update Compose files and docs, add the route-inventory guard.

*Why:* flipping first would 401 every UI call before a login page exists.

## Risks / Trade-offs

- [Existing tests rely on no auth] → Autouse fixture in `tests/conftest.py` sets `DOCPIPE_AUTH_ENABLED=false`; the setting is read per request so `monkeypatch` works; the `get_current_user` override path is preserved (D2).
- [Default-on breaks scripts and deployments] → Documented as **BREAKING** with the one-line opt-out; Bearer keeps working; Compose files gain the bootstrap variables and a documented placeholder secret flow.
- [Stolen token valid until expiry] → 30-minute lifetime, `HttpOnly`, `SameSite=Lax`, `Secure` over HTTPS; revocation deferred (D7).
- [Role staleness up to token lifetime] → Documented; short TTL.
- [In-memory throttling not shared across workers, and lost on restart] → Documented; acceptable as brute-force slowing, not a security boundary.
- [Proxy header spoofing if `DOCPIPE_TRUST_PROXY_HEADERS` is wrongly enabled] → Off by default; documented to enable only behind a trusted proxy.
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
- Should event dispatch call the job service in-process instead of using a system token (D11)?
