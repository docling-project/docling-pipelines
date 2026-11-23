# Spec Delta

## Purpose

The bff-proxy capability defines how the Node/Express backend-for-frontend relays browser requests, session cookies and authentication headers to the REST API without exposing backend addresses or credentials to browser scripts.

## ADDED Requirements

### Requirement: Credential and context header forwarding
Every proxied data request SHALL forward the `Cookie`, `Authorization`, `X-Requested-With` and `X-Transaction-ID` headers from the browser request to the REST API when present, including requests that set their own `Accept` header. The BFF SHALL NOT forward `X-Forwarded-For` or `X-Forwarded-Proto`.

#### Scenario: Cookie reaches backend
- **WHEN** the browser calls `GET /api/flows` with a session cookie
- **THEN** the REST API receives the same `Cookie` header

#### Scenario: CSRF header reaches backend
- **WHEN** the browser sends `X-Requested-With` on a mutation
- **THEN** the REST API receives it

#### Scenario: Cookie reaches backend on a custom Accept request
- **WHEN** the browser downloads a job run report, which sends `Accept: text/csv`
- **THEN** the REST API receives the `Cookie` header as well

#### Scenario: Client forwarding headers are dropped
- **WHEN** the browser sends `X-Forwarded-For` to the BFF
- **THEN** the REST API call does not carry that header

### Requirement: No authentication routes on the BFF
The BFF SHALL NOT expose `/api/auth/*`. The SPA SHALL call the REST API's `/auth/*` routes on the origin that serves it. Deployments that put a custom ingress in front of the BFF MUST route `/ui` and `/auth` to the REST API.

#### Scenario: Auth path not served
- **WHEN** a client calls `GET /api/auth/config` on the BFF
- **THEN** the BFF answers 404

### Requirement: Authentication errors relayed unchanged
The BFF SHALL return 401 and 403 responses from the REST API to the browser with the same status and a JSON body, without converting them to a generic error.

#### Scenario: 401 relayed
- **WHEN** the REST API answers a proxied call with 401
- **THEN** the browser receives 401

#### Scenario: 403 relayed
- **WHEN** the REST API answers 403 with a message
- **THEN** the browser receives 403 with that message

### Requirement: Streamed download errors keep their status
When a streamed download such as the job run report fails upstream, the BFF SHALL return the upstream status with a JSON body. If the upstream body cannot be read as JSON, the BFF SHALL return `{ "error": "Failed to download job run report" }`. It SHALL NOT leave the request unanswered.

#### Scenario: Report download denied
- **WHEN** the REST API answers the report download with 403
- **THEN** the browser receives 403 with a JSON body

#### Scenario: Expired session on download
- **WHEN** the REST API answers the report download with 401
- **THEN** the browser receives 401 within the normal request time

### Requirement: Loopback binding by default
The BFF SHALL listen on `127.0.0.1` unless `BFF_HOST` is set. It SHALL NOT bundle backend addresses or secrets into browser JavaScript.

#### Scenario: Default bind
- **WHEN** the BFF starts with no `BFF_HOST`
- **THEN** it accepts connections only on the loopback interface

#### Scenario: Explicit host
- **WHEN** `BFF_HOST=0.0.0.0` is set
- **THEN** it accepts connections on all interfaces

### Requirement: Container images listen on all interfaces
The BFF container image SHALL set `BFF_HOST=0.0.0.0`, so the Compose `bff` service and the Kubernetes sidecar, whose probes use the pod address, can reach it. The sidecar that the REST API starts itself SHALL keep the loopback default.

#### Scenario: Compose reaches the BFF
- **WHEN** the REST API container calls `http://bff:3001` in the Compose stack
- **THEN** the BFF accepts the connection

#### Scenario: Kubernetes probe reaches the BFF
- **WHEN** the kubelet probes `/health` on the pod address
- **THEN** the BFF answers 200
