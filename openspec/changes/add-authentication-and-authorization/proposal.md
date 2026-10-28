# Proposal

## Why

The REST API and UI have no enforced authentication or authorization. Anyone who can reach the port can read, change or delete flows, projects, job runs, document sets and libraries, and can upload custom operators, which is arbitrary code execution. The backend already has LDAP login, OAuth2/OIDC routes, a rate limiter and a self-issued JWT (`src/docpipe/api/auth/`), but only two document endpoints use it, and the UI auth layer is a stub (`useAuth` returns `isAuthenticated: true`). Tracks upstream issue docling-project/docling-pipelines#462 and the internal OSS stories datasift-tracker#5953 (auth APIs) and #5952 (login page).

## What Changes

Layers affected: **full-stack** (FastAPI backend, Express BFF, React/Carbon frontend).

- Enforce a session on every `/api/v1/*` route at router level, gated by `DOCPIPE_AUTH_ENABLED`. The setting is evaluated per request. The default is `true`, but it is flipped to `true` only in the final phase of this change so that every intermediate state keeps the UI usable.
- Session is an `HttpOnly`, `SameSite=Lax` cookie holding the existing HS256 JWT; `Authorization: Bearer` keeps working for scripts and API clients. Cookie-authenticated mutations also require an `X-Requested-With` header (stateless CSRF defense).
- New public `GET /auth/config` and `POST /auth/logout`; `GET /auth/me` returns roles; `POST /auth/login` sets the cookie and returns both `access_token` (for API/script clients) and `user` with roles (while the UI `authSlice` stores only `user`). `POST /auth/login` goes through an `AuthenticatorPort` (LDAP adapter, plus an env-only `BootstrapAdminAuthenticator` so a stock Docker Compose deployment with no LDAP or OIDC can still log in).
- Fix the OIDC `authorize` and `callback` routes to accept `return_to` (aliasing legacy `redirect_after`), set the cookie, and redirect to a validated same-origin `return_to` path (normalizing UI paths under `/ui` and defaulting to `/ui/projects`) instead of putting the token in the URL fragment. Reverse the existing unit test that asserts cookies are not accepted.
- Three roles: `viewer` (read), `editor` (create, update, delete, run) and `admin` (custom operators, modify any asset), mapped from OIDC `groups`/`roles` claims and LDAP `memberOf` through a configurable mapping. Unmapped users get `viewer`.
- Ownership: `created_by` is set from the session, and `modified_by` is updated on writes. Editors modify only their own flows and projects; admins modify any; assets with no owner stay editable by any editor. Checks live in `FlowService` and `ProjectService` through a domain `ActorContext`, not in routes. Deleting a project verifies project ownership before cascading (and refuses with 403 before deleting anything if any child flow is owned by another user and the caller is not `admin`). Denials and writes are written to the audit log.
- Harden the existing in-memory rate limiter: count failed attempts, add per-username lockout, a `Retry-After` header and bounded state.
- Internal event dispatch (`EventDispatchService`) authenticates its own calls to `/api/v1/job_runs`.
- Startup fails when auth is enabled without a strong `JWT_SECRET_KEY`. `CORSMiddleware` enables `allow_credentials=True` when `CORS_ORIGINS` does not contain `*`.
- BFF forwards `Cookie`, `Authorization`, `X-Requested-With`, `X-Transaction-ID`, `X-Forwarded-For` and `X-Forwarded-Proto`, relays `Set-Cookie` and 401/403 unchanged, exposes `/api/auth/*` (with `maxRedirects: 0` so 3xx redirects are not followed server-side), and binds to `127.0.0.1` by default. The FastAPI `proxy_to_bff` fix preserves multiple `Set-Cookie` headers.
- Frontend: `auth` Redux slice bootstrapped from `/auth/config` and `/auth/me`; `/login` page (Carbon `Form`, `TextInput`, `PasswordInput`, `Button`, `InlineNotification`, OIDC provider buttons); `ProtectedRoute` wired around all other routes with `return_to` redirect-back; header user menu with sign-out; `useAuth` exposes `canEdit` and `canAdmin` so unavailable actions are disabled with a tooltip; `apiClient` sends credentials, redirects once on 401 and toasts on 403.
- **BREAKING**: with auth enabled, unauthenticated `/api/v1/*` calls return 401 and viewers get 403 on writes. Set `DOCPIPE_AUTH_ENABLED=false` for the previous behavior. Cookie-authenticated mutations without `X-Requested-With` return 403.
- **BREAKING**: OIDC callback no longer returns the token in the URL fragment.

## Capabilities

### New Capabilities
- `backend/auth-api`: login, logout, current user, auth config, session cookie and Bearer extraction, CSRF check, OIDC cookie callback, authenticator port with bootstrap admin, rate limiting and lockout, startup validation.
- `backend/authorization`: role model, group-to-role mapping, router-level route guards and endpoint permission matrix, route-inventory guarantee, ownership policy, audit logging of denials and writes.
- `frontend/state/auth-slice`: Redux `auth` slice, `useAuth` hook, `canEdit`/`canAdmin`.
- `frontend/login-page`: `/login` page with credential form and OIDC buttons.
- `frontend/bff-proxy`: BFF header and cookie forwarding, `/api/auth/*` routes, loopback binding.

### Modified Capabilities
- `backend/flows-api`: ownership on create, update, delete and bulk delete.
- `backend/projects-api`: ownership on create, update and delete (including pre-cascade ownership check on project and child flows).
- `backend/custom-operators-api`: create, update and delete require `admin`.
- `backend/documents-api`: session cookie or Bearer token accepted; honors `DOCPIPE_AUTH_ENABLED`.
- `frontend/api-client`: credentialed requests, single-redirect 401, 403 toast.
- `frontend/navigation`: `/login` route outside shell chrome, `ProtectedRoute` with `return_to`, header user menu.
- `frontend/home-page`, `frontend/projects-page`, `frontend/project-detail-page`, `frontend/flow-detail-page`, `frontend/canvas-page`, `frontend/read-only-canvas`, `frontend/common/flow-info-panel`: all write, edit, delete, run and cancel actions across the UI are disabled or hidden with a tooltip when the user lacks the required role or ownership.

## Non-goals

- Per-project or per-asset sharing lists; group ACLs on flows and projects.
- Group support in the document `allowed_users` ACL.
- MFA, password reset, self-registration, a user directory, a `users` table or `refresh_tokens` table (#5953 items dropped in favor of existing LDAP/OIDC).
- Refresh tokens or silent renew; asymmetric JWT signing.
- Server-side token revocation. Logout clears the cookie only. A shared-store revocation list is a follow-up for multi-replica deployments.
- Authentication for the CLI and `DocpipeFlowManager` (they call services with no actor and are unchanged).
- Sandboxing custom operators (covered by `add-secret-management`).

## Impact

- Backend: `src/docpipe/api/auth/` (`dependencies.py`, `jwt_handler.py`, `models.py`, `oauth2_routes.py`, `ldap_auth.py`, `oauth2_provider.py`, new `ports.py`, `config.py`, `roles.py`, `bootstrap_auth.py`), `api/main.py`, `api/api_router.py`, `api/routes/custom_operators.py`, `api/middleware/rate_limit.py` and `error_handler.py`, `core/models/actor_context.py` (new), `FlowService`, `ProjectService`, `core/event_streaming/dispatch_service.py`, `core/constants/constants.py`, `exceptions/`.
- Frontend BFF: `frontend/server/server.ts`, `server/controllers/*`, new `auth-controller.ts`.
- Frontend UI: `slices/authSlice.ts`, `store/index.ts`, `hooks/useAuth.ts`, `components/common/ProtectedRoute`, new `pages/Login`, `config/routes.config.ts`, `App.tsx`, `services/api/client.ts` and action modules, page components listed above.
- Routing under `/ui` gains `/login`; BFF proxy gains `/api/auth/*`; Redux gains the `auth` slice.
- Tests: `tests/unit/auth/test_dependencies.py` cookie test reversed; `tests/unit/auth/test_oauth2_routes.py` fragment assertion replaced; `tests/conftest.py` defaults `DOCPIPE_AUTH_ENABLED=false` for unrelated tests; new route-inventory test.
- Dependencies: none new. `bcrypt` is already locked at 5.0.0 and is called directly (not through `passlib`, which breaks against it).
- Docs/config: `docs/` auth guide, Docker Compose env vars, `docling-pipelines-config.yaml` role mapping.
