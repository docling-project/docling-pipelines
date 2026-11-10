# Tasks

## 1. Shared proxy module

- [x] 1.1 [frontend] Add `frontend/server/utils/proxy.ts` with `proxyRequest()` taking `path` segments and a `query` object, `InvalidPathSegmentError`, and `handleProxyError()`. Verify with `npx vitest run tests/unit/server/proxy.test.ts`.
- [x] 1.2 [frontend] Add `frontend/server/utils/query.ts` with `queryString()`, `queryStringList()` and `routeParam()`, each documented with the backend shape it produces. Verify with `npx vitest run tests/unit/server/proxy.test.ts`.
- [x] 1.3 [frontend] Move the header constants to `frontend/server/constants/http-headers.ts` and import them only from `proxy.ts`.

## 2. Controllers

- [x] 2.1 [frontend] Migrate `flow`, `job-run`, `projects`, `operator`, `validation` and `document-class` controllers to `proxyRequest` and `await handleProxyError`, with typed `Request`, `Response`, `Router` and `Promise<void>`. Verify with `npx vitest run tests/unit/server/controllers.test.ts`.
- [x] 2.2 [frontend] Send `tags` as repeated keys on the flow and project list routes, and pass `is_elyra` as an encoded query value on the validation route.
- [x] 2.3 [frontend] Read streamed error bodies for the report download so a backend error no longer throws in `res.json()`.

## 3. Tests

- [x] 3.1 [frontend] Unit tests for the proxy module and query helpers in `frontend/tests/unit/server/proxy.test.ts`.
- [x] 3.2 [frontend] Controller tests in `frontend/tests/unit/server/controllers.test.ts` covering route registration, URL construction, hostile route and query input, error mapping, the patch-flow name sync, the report download, and the controller conventions.

## 4. Validation

- [x] 4.1 [frontend] Run `npx tsc --noEmit -p tsconfig.server.json` and confirm no errors in `server/controllers`, `server/utils` or `server/constants`.
- [x] 4.2 [frontend] Run `npx eslint server`.
- [x] 4.3 [frontend] Run `npm run build:bff`.
- [x] 4.4 [frontend] Run `npx vitest run` for the whole frontend suite.
- [x] 4.5 [frontend] Run `openspec validate standardise-bff-proxy --strict`.
- [ ] 4.6 [frontend] After review and merge, run `openspec archive standardise-bff-proxy`.
