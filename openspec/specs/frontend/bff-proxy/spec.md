# frontend/bff-proxy Specification

## Purpose
The bff-proxy capability defines how the Node/Express BFF (`frontend/server/`) forwards browser requests under `/api` to the Python FastAPI backend at `BACKEND_API_URL`. It covers how a backend URL is built from untrusted route and query input, which headers are sent, what the browser receives when the backend fails, and the rules every BFF controller follows so that new routes inherit this behaviour.

## Requirements

### Requirement: Backend URL construction from untrusted input
The BFF SHALL build every backend URL from separate path segments and a query object, never from a pre-joined string. Each path segment SHALL be percent-encoded, so a route parameter cannot add a query parameter or an extra path level. The query string SHALL be built so that keys and values are encoded, entries with an `undefined` value are omitted, and an array value is sent as one repeated key per entry.

#### Scenario: Route parameter containing a query delimiter
- **WHEN** a request targets a route whose parameter decodes to `abc?is_elyra=true`
- **THEN** the backend is called with the path segment `abc%3Fis_elyra%3Dtrue` and no `is_elyra` parameter is added

#### Scenario: Route parameter containing path separators
- **WHEN** a request targets a route whose parameter decodes to `../../operators/metadata`
- **THEN** the backend is called with the single segment `..%2F..%2Foperators%2Fmetadata` and no other backend endpoint is reached

#### Scenario: Query value containing separators
- **WHEN** a query value contains `&` or `=`
- **THEN** the value is percent-encoded and no additional parameter reaches the backend

#### Scenario: List parameter
- **WHEN** a list-valued parameter such as `tags` has the values `x` and `y`
- **THEN** the backend receives `tags=x&tags=y`

#### Scenario: Undefined optional parameter
- **WHEN** an optional query value is `undefined` or an empty filter
- **THEN** the parameter is omitted from the backend URL

### Requirement: Unsafe path segments are rejected
The BFF SHALL reject a path segment that is empty, `.` or `..` before contacting the backend, and SHALL answer HTTP 400 with the body `{ "error": "Invalid request path" }`. The rejection SHALL be logged at warning level and the rejected value SHALL NOT appear in the reply.

#### Scenario: Dot-dot route parameter
- **WHEN** a request targets `GET /api/flows/..`
- **THEN** the response is HTTP 400 with `{ "error": "Invalid request path" }` and the backend is not called

#### Scenario: Single-dot route parameter
- **WHEN** a request targets `GET /api/flows/.`
- **THEN** the response is HTTP 400 with `{ "error": "Invalid request path" }` and the backend is not called

### Requirement: Request headers
The BFF SHALL send `Accept: application/json` on every backend request, and `Content-Type: application/json` when the request has a body. A controller MAY override `Accept` and nothing else. The default header objects SHALL NOT be modified by any request.

#### Scenario: Request without a body
- **WHEN** the BFF sends a request with no body
- **THEN** the headers are exactly `Accept: application/json`

#### Scenario: Request with a body
- **WHEN** the BFF sends a request with a body
- **THEN** the headers are `Accept: application/json` and `Content-Type: application/json`, and the body is sent unchanged

#### Scenario: Accept override for a download
- **WHEN** a controller requests a CSV report with `accept: 'text/csv'`
- **THEN** the headers are exactly `Accept: text/csv` and the next request without an override still sends `Accept: application/json`

### Requirement: Successful responses are relayed unchanged
The BFF SHALL relay the backend payload of a successful call. Create and cancel routes SHALL reply with the backend status. Delete routes SHALL reply with the backend status and an empty body. Other routes SHALL reply with HTTP 200 and the backend payload.

#### Scenario: Create route
- **WHEN** the backend answers `201` with `{ "id": "new" }` to a flow creation
- **THEN** the BFF replies `201` with `{ "id": "new" }`

#### Scenario: Delete route
- **WHEN** the backend answers `204` to a flow deletion
- **THEN** the BFF replies `204` with an empty body

### Requirement: Backend errors are relayed with their status and body
When the backend answers with an error status, the BFF SHALL reply with that status and that body. The body SHALL also be written to the server log together with the status and the failing operation's fallback message. When the error body is a stream (a request made with `responseType: 'stream'`), the BFF SHALL read at most 64 KB of it as text and reply with the parsed JSON, or with `{ "error": <fallback message> }` when the text is not JSON. The BFF SHALL NOT pass a stream to `res.json()`.

#### Scenario: Backend returns 404 with detail
- **WHEN** the backend answers `404` with `{ "detail": "Project not found" }`
- **THEN** the BFF replies `404` with `{ "detail": "Project not found" }` and logs the status and body

#### Scenario: Streamed error body that is JSON
- **WHEN** a report download fails with `404` and a streamed body `{"detail":"Job run not found"}`
- **THEN** the BFF replies `404` with `{ "detail": "Job run not found" }` and does not throw

#### Scenario: Streamed error body that is not JSON
- **WHEN** a report download fails with `502` and the streamed body is `Bad gateway`
- **THEN** the BFF replies `502` with `{ "error": "Failed to download job run report" }`

#### Scenario: Streamed error body above the size cap
- **WHEN** a streamed error body exceeds 64 KB
- **THEN** the BFF stops reading, destroys the stream, and replies with `{ "error": <fallback message> }`

### Requirement: Failures without a backend response
When no backend response exists (network failure, connection refused, or an unexpected error), the BFF SHALL reply HTTP 500 with `{ "error": <fallback message> }`, where the fallback message names the failing operation. The underlying error message SHALL be logged and SHALL NOT be sent to the browser.

#### Scenario: Backend unreachable
- **WHEN** the connection to the backend is refused with the message `connect ECONNREFUSED 10.0.0.5:8000`
- **THEN** the BFF replies `500` with `{ "error": "Failed to fetch document classes" }` and the reply does not contain `10.0.0.5`

#### Scenario: Non-Error value thrown
- **WHEN** a handler fails with a thrown value that is not an `Error`
- **THEN** the BFF replies `500` with `{ "error": <fallback message> }`

### Requirement: Query helpers narrow types and do not encode
The `queryString`, `queryStringList` and `routeParam` helpers SHALL only narrow Express's loosely typed `req.query` and `req.params` values. They SHALL NOT encode; encoding is left to the proxy function.

#### Scenario: Helpers leave values unencoded
- **WHEN** `queryString` receives `'a&b'`
- **THEN** it returns `'a&b'` unchanged

### Requirement: Single-value query helper
`queryString` SHALL return one string for a parameter the backend reads as a single value. Numbers and booleans SHALL be stringified, an array SHALL be joined with commas, and any other value SHALL give `undefined`.

#### Scenario: Primitive value
- **WHEN** `queryString` receives `5` or `false`
- **THEN** it returns `'5'` or `'false'`

#### Scenario: Unsupported value
- **WHEN** `queryString` receives an object or `undefined`
- **THEN** it returns `undefined`

### Requirement: List query helper
`queryStringList` SHALL return the string entries of a value as a list, for parameters the backend reads as repeated keys. A single string SHALL become a one-item list, and entries that are not strings SHALL be dropped.

#### Scenario: Mixed entries
- **WHEN** `queryStringList` receives `['a', { "b": "c" }, 'd']`
- **THEN** it returns `['a', 'd']`

#### Scenario: Missing value
- **WHEN** `queryStringList` receives `undefined`
- **THEN** it returns an empty list

### Requirement: Route parameter helper
`routeParam` SHALL narrow an Express route parameter to a string, using the first entry when it is an array and `''` when it is `undefined`.

#### Scenario: Array parameter
- **WHEN** `routeParam` receives `['first', 'second']`
- **THEN** it returns `'first'`

#### Scenario: Missing route parameter
- **WHEN** `routeParam` receives `undefined`
- **THEN** it returns `''`, which the proxy function rejects as an empty path segment

### Requirement: Flow query defaults and list filters
The flow and project list routes SHALL send `limit` (default `100`) and `offset` (default `0`), SHALL send `is_elyra=true` on flow routes, and SHALL send `tags` as repeated keys. The flow validation route SHALL send `is_elyra` from the request query, defaulting to `true`, as an encoded value.

#### Scenario: Flow list with filters
- **WHEN** the browser requests `GET /api/flows` with `tags=x`, `tags=y` and `name=my flow`
- **THEN** the backend URL query is `limit=100&offset=0&is_elyra=true&name=my+flow&tags=x&tags=y`

#### Scenario: Validation with a hostile is_elyra value
- **WHEN** the browser posts to `/api/validation/validate?is_elyra=true%26admin%3D1`
- **THEN** the backend receives `is_elyra=true%26admin%3D1` and no `admin` parameter

### Requirement: Report download streams CSV and survives backend errors
The report route SHALL request the backend report with `Accept: text/csv` and `responseType: 'stream'`, set `Content-Type: text/csv` and `Content-Disposition: attachment; filename="job-run-<id>-report.csv"`, and pipe the stream to the browser. A stream error after the reply has started SHALL be logged and SHALL destroy the response.

#### Scenario: Successful download
- **WHEN** the backend returns a CSV stream for job run `r1`
- **THEN** the browser receives the CSV bytes with the attachment filename `job-run-r1-report.csv`

#### Scenario: Report missing
- **WHEN** the backend answers `404` for the report
- **THEN** the BFF replies `404` with the backend's JSON body and the process does not raise an unhandled rejection

### Requirement: Controllers use the shared proxy functions only
Every BFF controller under `frontend/server/controllers/` SHALL call the backend only through the shared proxy function and answer failures only through the shared error function. A controller SHALL NOT import axios, SHALL NOT import the default header constants, and SHALL NOT read `status` or `data` from an error response.

#### Scenario: No direct HTTP client or header constants
- **WHEN** the controller sources are inspected
- **THEN** none imports `axios` or the header constants

#### Scenario: No manual error extraction
- **WHEN** the controller sources are inspected
- **THEN** none accesses `.response.status` or `.response.data`

### Requirement: Controllers are explicitly typed
Every request handler in a BFF controller SHALL be typed `(req: Request, res: Response): Promise<void>`, and an unused request MAY be named `_req`. The exported `routes` function SHALL be typed `(router: Router): void`.

#### Scenario: Handler and routes types
- **WHEN** the controller sources are inspected
- **THEN** every handler has the explicit `Request`, `Response` and `Promise<void>` types and every file exports `routes` with the `Router` type

### Requirement: Inputs are validated before the backend is called
A controller SHALL answer HTTP 400 without calling the backend when a required input is missing or not allowed.

#### Scenario: Provider allow list
- **WHEN** the browser requests models for a provider other than `ollama` or `watsonx`
- **THEN** the BFF replies `400` and the backend is not called

#### Scenario: Required bulk delete parameter
- **WHEN** the browser sends `DELETE /api/flows` without `flow_ids`
- **THEN** the BFF replies `400` with `{ "error": "flow_ids query parameter is required" }` and the backend is not called
