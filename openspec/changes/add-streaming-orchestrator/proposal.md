# Proposal

## Table of Contents

- [Why](#why)
- [What Changes](#what-changes)
- [Scope](#scope)
- [Capabilities](#capabilities)
- [Non-goals](#non-goals)
- [Impact](#impact)

## Why

File events currently submit asynchronous HTTP job runs and commit Kafka offsets before document processing completes.
Direct, synchronous execution removes per-event job tracking and makes acknowledgement follow the pipeline's
terminal outcome.

## What Changes

- Replace event-to-HTTP job submission with direct, synchronous execution of saved flows through a streaming runtime.
  The complete deliverable list and limits are defined in [Scope](#scope).
- **BREAKING** for event-streaming consumers: `dispatch()` signals completed processing instead of returning a job-run
  response; event processing produces no job-run history, report, snapshot, or cancellation handle. Kafka commits move
  from HTTP acceptance to completion or retry exhaustion. Existing REST job-run request/response contracts are retained.

## Scope

This section is the authoritative scope boundary for `add-streaming-orchestrator`. Only S01-S08 below are included.
The spec deltas define acceptance within this boundary; design decisions, task edits, reference material, and
backlog entries cannot independently expand it.

### In scope

- **S01 - Saved-flow preparation:** Load and compile existing authoring/Elyra definitions per attempt. Reuse operator
  discovery, compiler/runtime integrity checks, and required feature propagation without full per-event validation.
- **S02 - Event input and configuration:** Bind the existing create/update `InputEvent` to one document through the
  existing provider contract; force reprocessing while preserving filters, configuration precedence, and secret
  resolution. Use isolated event/session configuration without inherited job/run IDs.
- **S03 - Existing operator execution:** Run the DAG sequentially with Arrow tables in memory. Preserve schemas,
  applicable rows/chunks, feature drops/renames, empty-document filtering, branch selection, merge link identities,
  and empty-route behavior. Propagate exceptions and reported document failures; stop the failed attempt's remaining
  work.
- **S04 - Attempt lifecycle:** Use fresh operator instances per attempt, release resources through supported cleanup
  hooks, restore session state, and retain configured sink writes. Create no jobs, intermediate spill files, or batch
  finalization artifacts. Use existing no-job-context behavior rather than redesigning operators.
- **S05 - Direct integration:** Wire the existing listener, mapping service, flow service, and operator discovery to
  the new runtime. Remove the dispatch HTTP/API URL dependency and job-run response handling.
- **S06 - Event handling policy:** Process one event at a time with configurable bounded immediate retries. Log terminal
  outcomes, attempt manual commits after success/exhaustion or invalid-event rejection, and retain existing commit-error
  reporting. Add only the planned retry-count setting, `DOCPIPE_EVENT_MAX_RETRIES`, with default `0`.
- **S07 - Graceful shutdown:** Stop accepting new work and drain the active event, including its allowed retries,
  cleanup, and terminal commit attempt, before closing the consumer. Leave unfinished work uncommitted.
- **S08 - Verification and documentation:** Test and document S01-S07, verify sink output and no event job records,
  update the existing streaming sample/guide, and run the planned batch regressions, lint, type, build, and spec checks.
  Deferred backlog experiments and safeguards are excluded from acceptance.

### Scope control

- Every implementation or validation task must map to S01-S08. Implementation details may vary within those behaviors;
  they cannot add unlisted capabilities, configuration, APIs, storage changes, dependencies, or guarantees.
- Anything not explicitly covered is out of scope, whether already known, newly discovered, unplanned, or previously
  unconsidered. Record it in the [deferred backlog](design.md#deferred-backlog), including corner cases and
  improvements.
  Do not implement it or add its acceptance tests to this change because it is adjacent, small, or convenient.
- If an unplanned item blocks a listed deliverable, record and report the blocker and continue independent scoped work.
  Do not silently broaden the implementation, weaken an acceptance criterion, or mark the blocked task complete.
- Backlog promotion defaults to a separate OpenSpec change. Expanding this change requires explicit user approval of
  a scope revision, followed by coherent updates to this section, the affected specs, design, and tasks before
  code changes.
- Completion means delivering S01-S08 and their existing acceptance criteria. Deferred items are neither implementation
  tasks nor release gates; an unresolved blocker of an in-scope requirement still prevents its completion.

## Capabilities

### New Capabilities

- `backend/streaming-orchestrator`: Saved-flow preparation and document-bound in-memory DAG execution with existing
  operators, isolated attempt state, resource cleanup, and completion/failure signalling without job tracking.
- `backend/event-stream-processing`: Direct event routing, sequential listener execution, bounded retries, terminal
  diagnostics, offset acknowledgement, environment configuration, and shutdown behavior.

### Modified Capabilities

None. `backend/flow-execution-engine` continues to govern `FlowExecutor` and the batch entrypoints;
`backend/flows-api`, `backend/job-runs-api`, `backend/ededup-operator`, and `backend/package-operator-loading` retain
their existing contracts. Streaming uses the existing no-job-context deduplication behavior.

## Non-goals

- Corner-case safeguards, future enhancements, and their associated validation scenarios, as tracked in the
  [deferred backlog](design.md#deferred-backlog).
- Durable streaming run records, job reporting, cancellation APIs, micro-batching, and batch finalization.
- New source-provider reference semantics, event operations, mapping CRUD routes, or sink persistence contracts.

## Impact

**Layer: backend-only.** Primary changes are under `core/orchestration/streaming/`, `core/event_streaming/`, environment
constants, API listener lifecycle integration, tests, and event-streaming deployment documentation.

The runtime reuses `FlowService`, existing mapping storage, `AuthoringCompiler`, `ElyraConverter`, operator discovery,
feature propagation, and stateless operator utilities. Chunking/embedding configurations must disable disk spilling
for this path. Any necessary reuse changes remain narrowly scoped and preserve batch behavior.

`/api/v1/flows` and `/api/v1/event_mappings` remain the authoring and routing APIs. `/api/v1/job_runs` remains available
for explicit batch runs; the listener stops calling it. Existing storage adapters remain behind their ports; configured
sinks still persist results. Remove the dispatcher's `DOCPIPE_API_BASE_URL` dependency and stale sample settings only
where they exist solely for HTTP event submission. No new dependency or storage migration is expected.

There are no changes to `/ui` routing, BFF routes, Redux slices, Carbon components, or SCSS modules.
