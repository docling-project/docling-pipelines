# Proposal

## Why

The REST API and UI have no enforced authentication or authorization. Anyone who can reach the port can read, change or delete flows, projects, job runs, document sets and libraries, and can upload custom operators, which is arbitrary code execution. The backend already has LDAP login, OAuth2/OIDC routes, a rate limiter and a self-issued JWT (`src/docpipe/api/auth/`), but only two document endpoints use it, and the UI auth layer is a stub (`useAuth` returns `isAuthenticated: true`). Tracks upstream issue docling-project/docling-pipelines#462.

## What Changes

Layers affected: **full-stack** (FastAPI backend, Express BFF, React/Carbon frontend).

- Enforce a session on every `/api/v1/*` route at router level, gated by `DOCPIPE_AUTH_ENABLED`. The default is `true`. The setting is read per request so tests can change it, but operators set it before the process starts.
- Session is an `HttpOnly`, `SameSite=Lax` cookie holding the existing HS256 JWT; `Authorization: Bearer` keeps working for scripts and API clients. Cookie-authenticated mutations also require an `X-Requested-With` header (stateless CSRF defense).
- New public `GET /auth/config` and `POST /auth/logout`; `GET /auth/me` returns roles; `POST /auth/login` sets the cookie and returns both `access_token` (for API/script clients) and `user` with roles (while the UI `authSlice` stores only `user`). `POST /auth/login` goes through an `AuthenticatorPort` (LDAP adapter, plus an env-only `BootstrapAdminAuthenticator` so a stock Docker Compose deployment with no LDAP or OIDC can still log in).
- Fix the OIDC `authorize` and `callback` routes to accept `return_to` (aliasing legacy `redirect_after`), set the cookie, and redirect to a validated same-origin `return_to` path (normalizing UI paths under `/ui` and defaulting to `/ui/projects`) instead of putting the token in the URL fragment. A short-lived nonce cookie binds the callback to the browser that started the login. Reverse the existing unit test that asserts cookies are not accepted.
- Three roles: `viewer` (read), `editor` (create, update, delete, run) and `admin` (custom operators, modify any asset), mapped from OIDC `groups`/`roles` claims and LDAP `memberOf` through a configurable mapping. Unmapped users get `viewer`.
- Ownership: `created_by` is set from the session on flows and projects, `user_id` is set from the session on job runs, and `modified_by` is updated on writes. Editors modify only their own flows and projects and cancel/delete only their own job runs; admins modify/cancel/delete any; assets or job runs with no owner stay editable by any editor. Checks live in `FlowService`, `ProjectService`, and `JobManagementService` through a domain `ActorContext`, not in routes. Deleting a project verifies project ownership before cascading (and refuses with 403 before deleting anything if any child flow is owned by another user and the caller is not `admin`). Denials and writes are written to the audit log.
- Harden the existing in-memory rate limiter: count failed attempts, lock the pair of client address and username, add a `Retry-After` header and bounded state. The client address is the TCP peer unless `DOCPIPE_TRUST_PROXY_HEADERS=true`, which takes the rightmost `X-Forwarded-For` entry.
- Internal event dispatch (`EventDispatchService`) authenticates its own calls to `/api/v1/job_runs` with a short-lived `editor` token for a fixed system username.
- Startup fails when auth is enabled without a strong `JWT_SECRET_KEY`. `CORSMiddleware` keeps `allow_credentials=False`, because the SPA and the API share one origin.
- BFF forwards `Cookie`, `Authorization`, `X-Requested-With` and `X-Transaction-ID` on data requests, relays 401/403 unchanged (including on the streamed report download), and binds to `127.0.0.1` by default with `BFF_HOST=0.0.0.0` set in its container image. The BFF has no `/api/auth/*` routes. The SPA calls FastAPI `/auth/*` on its own origin, and the Vite dev server proxies `/auth` to FastAPI.
- Frontend: `auth` Redux slice bootstrapped from `/auth/config` and `/auth/me`; `/login` page (Carbon `Form`, `TextInput`, `PasswordInput`, `Button`, `InlineNotification`, OIDC provider buttons); `ProtectedRoute` wired around all other routes with `return_to` redirect-back; header user menu with sign-out; `useAuth` exposes `canEdit` and `canAdmin` so unavailable actions are disabled with a tooltip; `apiClient` sends credentials, redirects once on 401 and toasts on 403. The UI gating is a convenience, and the backend enforces every rule.
- **BREAKING**: with auth enabled, unauthenticated `/api/v1/*` calls return 401 and viewers get 403 on writes. Set `DOCPIPE_AUTH_ENABLED=false` for the previous behavior. Cookie-authenticated mutations without `X-Requested-With` return 403.
- **BREAKING**: OIDC callback no longer returns the token in the URL fragment.

## Capabilities

### New Capabilities
- `backend/auth-api`: login, logout, current user, auth config, session cookie and Bearer extraction, CSRF check, OIDC cookie callback, authenticator port with bootstrap admin, rate limiting and lockout, startup validation.
- `backend/authorization`: role model, group-to-role mapping, router-level route guards and endpoint permission matrix, route-inventory guarantee, ownership policy, audit logging of denials and writes.
- `frontend/state/auth-slice`: Redux `auth` slice, `useAuth` hook, `canEdit`/`canAdmin`.
- `frontend/login-page`: `/login` page with credential form and OIDC buttons.
- `frontend/bff-proxy`: BFF header and cookie forwarding, no auth routes, loopback binding with a container exception.

### Modified Capabilities
- `backend/flows-api`: ownership on create, update, delete and bulk delete.
- `backend/projects-api`: ownership on create, update and delete (including pre-cascade ownership check on project and child flows).
- `backend/job-runs-api`: `user_id` attribution on create, `user_id` in list projection, and ownership enforcement on cancel and delete.
- `backend/custom-operators-api`: create, update and delete require `admin`.
- `backend/documents-api`: session cookie or Bearer token accepted; honors `DOCPIPE_AUTH_ENABLED`; the reserved local principal sees all documents when auth is off.
- `frontend/api-client`: credentialed requests, `/auth/*` calls, Vite `/auth` proxy, single-redirect 401, 403 toast.
- `frontend/navigation`: `/login` route outside shell chrome, `ProtectedRoute` with `return_to`, header user menu.
- `frontend/home-page`, `frontend/projects-page`, `frontend/project-detail-page`, `frontend/flow-detail-page`, `frontend/canvas-page`, `frontend/read-only-canvas`, `frontend/common/flow-info-panel`: all write, edit, delete, run and cancel actions across the UI are disabled or hidden with a tooltip when the user lacks the required role or ownership.

## Non-goals

- Per-project or per-asset sharing lists; group ACLs on flows and projects.
- Group support in the document `allowed_users` ACL.
- MFA, password reset, self-registration, a user directory, a `users` table or `refresh_tokens` table (existing LDAP/OIDC is used instead).
- Refresh tokens or silent renew; asymmetric JWT signing.
- Server-side token revocation. Logout clears the cookie only, and an issued token stays valid for up to 30 minutes. A shared-store revocation list is a follow-up for multi-replica deployments.
- Authentication for the CLI and `DocpipeFlowManager` (they call services with no actor and are unchanged).
- Sandboxing custom operators (covered by `add-secret-management`).

## Impact

- Backend: `src/docpipe/api/auth/` (`dependencies.py`, `jwt_handler.py`, `models.py`, `oauth2_routes.py`, `ldap_auth.py`, `oauth2_provider.py`, new `ports.py`, `config.py`, `roles.py`, `bootstrap_auth.py`), `api/main.py`, `api/api_router.py`, `api/routes/custom_operators.py`, `api/routes/job_runs.py`, `api/middleware/rate_limit.py` and `error_handler.py`, `core/models/actor_context.py` (new), `FlowService`, `ProjectService`, `JobManagementService`, `core/event_streaming/dispatch_service.py`, `core/constants/constants.py`, `exceptions/`.
- Frontend BFF: `frontend/server/server.ts`, `server/controllers/*`, `frontend/vite.config.ts`, `docker/bff.Dockerfile`.
- Frontend UI: `slices/authSlice.ts`, `store/index.ts`, `hooks/useAuth.ts`, `components/common/ProtectedRoute`, new `pages/Login`, `config/routes.config.ts`, `App.tsx`, `services/api/client.ts` and action modules, page components listed above.
- Routing under `/ui` gains `/login`; the Vite dev proxy gains `/auth`; Redux gains the `auth` slice.
- Tests: `tests/unit/auth/test_dependencies.py` cookie test reversed; `tests/unit/auth/test_oauth2_routes.py` fragment assertion replaced; `tests/conftest.py` defaults `DOCPIPE_AUTH_ENABLED=false` for unrelated tests; new route-inventory test.
- Dependencies: none new. `bcrypt` is already locked at 5.0.0 and is called directly (not through `passlib`, which breaks against it).
- Docs/config: `docs/` auth guide (including the OIDC redirect URI per topology and proxy trust), Docker Compose env vars, `docling-pipelines-config.yaml` role mapping.
