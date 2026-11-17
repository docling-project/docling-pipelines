# Design

## Context

The BFF is a thin Express server. Each controller receives a browser request, calls the FastAPI backend at `BACKEND_API_URL`, and relays the result. Before this change each controller did that itself, so URL building, header selection and error mapping existed in about thirty places. Two of those places had real defects (unencoded route parameters and an interpolated query value), and the streamed report download could crash the process on a backend error.

## Goals / Non-Goals

**Goals:**
- One function that calls the backend and one that answers a failed call, used by every controller.
- Make the safe way to build a backend URL the only way the shared function offers.
- Keep the observable behaviour of successful calls unchanged.

**Non-Goals:**
- Changing which status and body a backend error produces for the browser.
- An upstream timeout (not yet agreed).
- Changing any backend route.

## Layer Boundaries

This is a frontend-only change. It stays inside `frontend/server/`.

- **Controllers** (`server/controllers/`): decide the backend path and query for a route, and choose how to send the result (`res.json`, `res.status(...).send()`, or a stream). They own the fallback message for their operation.
- **Shared proxy module** (`server/utils/proxy.ts`): builds the URL and headers, sends the request, and answers failures. It has no knowledge of any specific route.
- **Query helpers** (`server/utils/query.ts`): narrow Express's loose `req.query` and `req.params` types. They do not encode.
- **Constants** (`server/constants/http-headers.ts`): default headers, imported only by the proxy module.

Component hierarchy, Carbon components, SCSS modules, Redux actions and the `/ui` routing are not affected.

## Decisions

### 1. `path` is an array of segments, and `query` is an object
- **Decision**: `proxyRequest({ method, path: ['api', 'v1', 'flows', flowId], query: { ... } })`. The function percent-encodes every segment with `encodeURIComponent` and builds the query string with `URLSearchParams`.
- **Rationale**: Express has already decoded route parameters, so a string-based path invites interpolation of untrusted text. With segments, a caller cannot add a query parameter or another path level by accident.
- **Alternatives considered**: Encode at each call site and document the `path` string. Rejected because one forgotten call site reopens the hole, and the type would still accept unsafe strings.

### 2. `.`, `..` and empty segments are rejected, not encoded
- **Decision**: These segments throw `InvalidPathSegmentError`, which `handleProxyError` maps to HTTP 400 `{ error: 'Invalid request path' }` without calling the backend.
- **Rationale**: `encodeURIComponent` leaves dots unchanged, and an HTTP client or server normalises `/flows/../x` to `/x`, so encoding alone does not stop a dot segment from leaving the intended resource. An empty segment would collapse into a different route (`/flows/` and `/flows`).
- **Trade-off**: A resource identifier that is literally `.` or `..` can never be proxied. No backend identifier has that form.

### 3. Query values may be arrays, sent as repeated keys
- **Decision**: An array value is appended once per entry (`tags=a&tags=b`), and `undefined` values are omitted.
- **Rationale**: The backend declares `tags` as a FastAPI `list[str]`, which reads repeated keys. The old comma-joined value arrived as a single tag.
- **Consequence**: `queryString` (one value) and `queryStringList` (a list) are different helpers. Their doc comments state which backend shape each produces.

### 4. `proxyRequest` returns the raw Axios response
- **Decision**: It returns `Promise<AxiosResponse>`, not parsed data.
- **Rationale**: Controllers differ in how they reply: JSON with the backend status, JSON with 200, an empty body, or a pipe of a stream. The caller keeps that choice.

### 5. Callers cannot pass headers
- **Decision**: Headers come from `BODY_HEADERS` when a body is present and `NO_BODY_HEADERS` otherwise. `accept` is the only override. The headers object is a fresh copy.
- **Rationale**: A controller cannot accidentally replace the defaults, and the shared constants are never mutated.

### 6. `handleProxyError` is async and reads streamed error bodies
- **Decision**: When the error response body is a Node `Readable` (requests made with `responseType: 'stream'`), it reads at most 64 KB as text and parses it as JSON, then replies with that. Non-JSON text falls back to `{ error: fallbackMessage }`.
- **Rationale**: A stream cannot be serialised by `res.json()`. Passing it threw and left an unhandled rejection. The size cap bounds memory for a misbehaving backend.
- **Consequence**: Every call site must `await handleProxyError(...)`.

### 7. Backend errors keep their status and body
- **Decision**: When the backend answered, its status and body are relayed. When there was no answer (network failure or an unexpected error), the reply is HTTP 500 `{ error: fallbackMessage }`. The network error message is logged but not sent.
- **Rationale**: The UI reads `detail` from backend error bodies. Changing this is out of scope (see Non-goals).
- **Logging**: The backend body is written to the server log with the status, so a failure can be diagnosed from the log even when the browser receives only the fallback.

## Risks / Trade-offs

- **Backend 5xx bodies still reach the browser.** A backend handler that puts exception detail in a 500 body exposes it. Mitigation: tracked as a follow-up decision, and the body is already logged server-side so a later change can drop it from the reply without losing diagnostics.
- **No upstream timeout.** A backend that accepts a connection and then stalls holds the BFF request open. Mitigation: deferred until a value is agreed. The browser client already gives up after 10 seconds, but the BFF request keeps running.
- **Query encoding differences.** `URLSearchParams` encodes a space as `+`. FastAPI decodes `+` as a space in query strings, so values round-trip correctly.
