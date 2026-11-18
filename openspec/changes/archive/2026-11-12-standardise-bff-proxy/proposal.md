# Proposal

## Why

The six BFF controllers (`flow`, `job-run`, `projects`, `operator`, `validation`, `document-class`) each imported axios, built their own headers, read `error.response?.status` and `?.data` by hand in about thirty near-identical `catch` blocks, and joined route parameters into backend URLs as raw strings. The copies had drifted: some handlers were untyped, one sent a one-off inline header, and error handling differed per route.

Centralising the proxy call and the error reply also made two latent defects visible, which are fixed here because they now have a single place to be fixed:

- Express decodes `req.params` before a controller sees it. A request to `/flows/abc%3Fis_elyra%3Dtrue` therefore reached the backend as `/api/v1/flows/abc?is_elyra=true`, and `%2F..%2F` could reach backend endpoints outside the resource the route was meant to expose. `validation-controller` also interpolated the `is_elyra` query value into the URL.
- An error response to the streamed CSV report download carried a Node stream as its body. Passing it to `res.json()` threw `Converting circular structure to JSON` and surfaced as a process-level unhandled rejection.

## What Changes

- **New capability**: `frontend/bff-proxy` specifies how the BFF forwards requests to the Python backend, how it builds the backend URL from untrusted input, and how it reports failures to the browser.
- New shared module `frontend/server/utils/proxy.ts` with `proxyRequest()` and `handleProxyError()`. New `frontend/server/utils/query.ts` with `queryString()`, `queryStringList()` and `routeParam()`.
- The header constants move from `server/controllers/http-headers.ts` to `server/constants/http-headers.ts`. Only `proxy.ts` imports them.
- All six controllers use the shared module. They no longer import axios or the header constants, no longer read `error.response`, and type every handler as `(req: Request, res: Response): Promise<void>` and `routes` as `(router: Router): void`.
- Route parameters and query values are encoded by `proxyRequest`: each path segment is percent-encoded, `.`, `..` and empty segments are rejected with HTTP 400, and the query string is built with `URLSearchParams`.
- `GET /flows` and `GET /projects` now send `tags` as repeated keys (`tags=a&tags=b`), which is the form the backend's `list[str]` parameter reads. The previous single comma-joined value was read as one tag.
- The report download now answers a backend error with that error's status and body instead of crashing.
- The upstream error body is written to the server log before the reply.
- Unchanged by design: the BFF routes, their request and response shapes for successful calls, and the status and body relayed for backend errors.

## Non-goals

- Replacing the bodies of 5xx backend responses with a fixed message. This changes what the browser receives, because the UI reads `detail` from error bodies (for example flow load and save), and needs a maintainer decision.
- Adding an upstream request timeout. The value is not yet agreed.
- Authentication, authorization or rate limiting on BFF routes.
- Changing any backend (FastAPI) route or the browser-side `apiClient` in `frontend/src/services/api/`.
- Fixing the unrelated TypeScript errors in `server/server.ts`.

## Capabilities

### New Capabilities
- `frontend/bff-proxy`: Forwarding of BFF requests to the backend, safe construction of backend URLs from untrusted route and query input, and normalised error replies.

### Modified Capabilities
- None. `frontend/api-client` describes the browser side and is unchanged.

## Impact

- **Affected Layer**: Frontend-only. The BFF is the Node/Express server under `frontend/server/`.
- **Affected BFF proxy routes**: all of `/api/flows*`, `/api/projects*`, `/api/job_runs*`, `/api/fetchOperatorMetadata`, `/api/enrichFlowFeatures`, `/api/providers/:provider/models`, `/api/documentClasses` and `/api/validation/validate`.
- **Affected code**:
  - `frontend/server/utils/proxy.ts` (new)
  - `frontend/server/utils/query.ts` (new)
  - `frontend/server/constants/http-headers.ts` (moved from `server/controllers/`)
  - `frontend/server/controllers/{flow,job-run,projects,operator,validation,document-class}-controller.ts`
- **Routing under /ui and Redux state**: None.
- **Backend routes and operators**: None.
- **Documentation**: None required.
- **Tests**: `frontend/tests/unit/server/proxy.test.ts`, `frontend/tests/unit/server/controllers.test.ts`.
