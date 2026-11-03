# Design

## Table of Contents

- [Context](#context)
- [Goals / Non-Goals](#goals--non-goals)
- [Decisions](#decisions)
- [Risks / Trade-offs](#risks--trade-offs)
- [Migration Plan](#migration-plan)
- [Deferred backlog](#deferred-backlog)

## Context

See [proposal.md](proposal.md) for motivation and scope.
The proposal's [Scope](proposal.md#scope) is authoritative. This design implements that boundary; the
[deferred backlog](#deferred-backlog) records future work and creates no implementation or acceptance obligations.

Observed implementation constraints:

- `core/event_streaming/dispatch_service.py` resolves a mapping, posts to `/api/v1/job_runs` using `httpx`, and returns
  its JSON response. `kafka_listener.py` commits after one dispatch attempt and joins its daemon thread for five seconds
  during shutdown. It already disables automatic commits and automatic offset storage.
- `JobManagementService.create_and_start_job_run()` loads flows through `FlowService`, compiles authoring definitions
  with `AuthoringCompiler`, and converts Elyra definitions with `ElyraConverter`. It also creates tracked jobs and
  submits work to an executor, so the streaming path cannot delegate to that service.
- `FlowExecutor` and `AbstractOrchestrator` own validation, job context, statistics, batching, intermediate data access,
  and finalization. Their contracts remain under `backend/flow-execution-engine`.
- `FlowValidator.propagate_features_per_node()` supports metadata propagation without full validation, using the
  existing `FeaturePropagator` and topological utilities. Its constructor currently requires an orchestrator for logging
  and operator settings. Merge handling includes link-name-based disambiguation.
- `PythonOperatorExecutor` resolves vault references, drops/renames output features, filters empty documents, and
  releases operators. Its surrounding execution path also performs job statistics and incremental writes.
- `IngestSourceOperator` already accepts `input_event`, forces ingestion, and calls the source adapter's
  `bind_file_reference()`. Some ingest failures become failed-document metadata instead of raised exceptions.
- Chunking spills to files when `memmap_threshold > 0` is exceeded. Embeddings use file-backed output when their
  corresponding chunks are file-backed. `ededup` already supports instance-local state when job/run context is absent.

Existing engine, flow API, job-run API, deduplication, and package-loading specs were inspected. No changes to their
requirements are needed: the new contracts apply to a separate streaming entrypoint.

## Goals / Non-Goals

**Goals:**

- Reuse flow formats, operator discovery, feature propagation, and pure table utilities without importing the batch
  lifecycle into streaming execution.
- Make the boundary between flow execution outcome and Kafka acknowledgement explicit.
- Keep mutable state and table lifetimes scoped to an attempt, including failure and cleanup paths.

**Non-Goals:**

- Turn `StreamingOrchestrator` into another `AbstractOrchestrator` implementation or add it to the batch factory.
- Invent job/run identifiers to satisfy operator assumptions, or share deduplication admissions between events.
- Add frontend components or SCSS modules. Carbon layout and token rules have no affected surface here.
- Implement the corner-case safeguards, enhancements, or associated validation scenarios in the
  [deferred backlog](#deferred-backlog). Those items remain future work outside this change.

## Decisions

### 1. Separate synchronous runtime and event outcome owner

Add `core/orchestration/streaming/` with a `StreamingOrchestrator` and small preparation/operator-runner helpers.
The orchestrator exposes `execute(*, flow, params) -> None`: normal return means completion; a contextual execution
exception means attempt failure. It does not return tables or allocate a durable execution identifier.

`EventDispatchService` receives mapping service and orchestrator dependencies. `dispatch(*, event) -> None` resolves
the current mapping and calls `execute()`. `KafkaEventListener` owns terminal reporting and the commit decision. Each
valid record invokes dispatch once; a dispatch failure is reported, its message-specific commit is attempted, and the
listener moves on to the next record.

Let preparation errors propagate unchanged. Operator execution errors include node identity and preserve the original
cause. Metadata-reported failures identify the operator without copying failed-document reasons into the exception.
The existing listener logs event ID, Kafka coordinates, and the exception traceback. No flow ID plumbing or additional
dispatcher/orchestrator exception wrappers are needed.
Failure notification means raising the in-process outcome to the listener; external notifications and Kafka publications
remain deferred.

Operators own skip decisions, reasons, metadata, and logging. The orchestrator preserves empty-input handling without
interpreting skip reasons or adding skip-specific logs. The listener keeps its completion/commit policy; `execute()` and
`dispatch()` return `None`.

Alternative: delegate streaming execution to `JobManagementService`, `FlowExecutor`, or `PythonOrchestrator`.
Rejected because each couples execution to jobs, batch data access, or finalization. An executor pool is unnecessary
for one synchronous active event.

### 2. Use existing application services and storage ports

`EventStreamingFactory` wires `FlowService` using the same generic asset `RepositoryFactory` and `Flow` model selected
by API dependencies, without constructing job-management services. It injects existing `EventMappingService` and
operator discovery into the runtime. Do not import FastAPI dependency functions into core services.

The layer boundaries are:

| Layer | Responsibility |
| --- | --- |
| Domain | Existing `InputEvent`, mappings, flow models, and asset/storage port contracts |
| Application | Mapping resolution, `FlowService` reads, streaming preparation and execution |
| Adapters | Existing asset repositories, key-value mapping stores, source adapters, and configured sink adapters |
| Composition | `EventStreamingFactory` resolves configured adapters and builds the listener service graph |
| Transport | Kafka deserialization, terminal diagnostics, message commits, and lifecycle |

Domain/application code continues to use ports rather than import storage adapter implementations. Operators continue
to use their configured source, LLM, and sink abstractions. No storage schema or REST DTO changes are needed.

Alternative: load saved JSON directly or call the local API. Rejected because either bypasses configured repositories
or restores the HTTP dependency being removed.

### 3. Prepare an isolated executable flow on every attempt

Load and deep-copy `Flow.definition`. Apply the current format dispatch from job management: authoring `flow_name`
uses `AuthoringFlow` and `AuthoringCompiler`; Elyra `doc_type` uses `ElyraConverter`; other formats fail explicitly.
Do not persist the compiled form or mutate the saved model.

Use `sort_dag_topologically()` with explicit checks for duplicate IDs, unresolved/inconsistent edges, one ingest root,
and reachability. Resolve every operator class through the existing Python operator factory, honoring enabled custom
packages and existing discovery priority. No model-bearing operator construction is needed merely to check identity.

Reuse the existing `FlowValidator.propagate_features_per_node()` path. It computes per-node column/feature views and
propagated parameters without processing documents or performing full operator validation. Keep the current
PythonOrchestrator-based discovery and metadata setup; reuse the feature traversal, merge disambiguation, and
propagated global parameters rather than duplicating feature logic.

Alternative: disable all preparation or run full validation per event. The first loses required sink metadata and
integrity checks; the second repeats expensive service/configuration validation on the consumer's critical path.

"Compilation and runtime integrity checks" specifically means saved-format conversion plus the following checks,
all completed before document processing and independently of full validation or `disable_validation`:

- A nonempty executable DAG with valid node IDs and operator names, and no duplicate node IDs.
- Resolvable, consistent input/output edges and an acyclic graph ordered with `sort_dag_topologically()`.
- Exactly one root, whose operator is in the Ingest category, and every node reachable from that root.
- Every referenced operator class resolves through the configured Python factory and discovery priority, without
  constructing model-bearing operators merely to check identity.

Keep `_node_features_cache` instance-local and initially `None`. Each streaming attempt creates a new validator through
the existing PythonOrchestrator path and discards it after preparation. No propagation results are reused across events.

### 4. Build configuration with explicit streaming overrides

Preserve flow configuration precedence: global configuration, then node configuration. Inject node ID/name and
prepared feature metadata into a fresh dictionary.
Resolve vault references using the existing secret provider without logging resolved values.

Apply these execution-owned overrides last, including against per-node values:

- Ingest receives the validated event serialized as `input_event` and `force_ingest=true`. Binding remains inside the
  existing source adapter contract; no path-to-provider-ID conversion or additional credential lookup is introduced.
- Saved batching settings do not activate the batch engine. The runtime uses the synchronous graph engine and preserves
  the configured `memmap_threshold` and existing chunk/embedding spill behavior.

Keep operator-local deduplication isolated by fresh instances for each event.

Alternative: mutate the loaded definition or reuse a previous event's instances. Rejected because ingest binding,
branch metadata, feature state, and deduplication are mutable and could suppress or redirect later work.

### 5. Execute tables and routes without batch data-access wrappers

Maintain an attempt-local map from node IDs to output tables, metadata, and resolved empty-route state. Execute nodes
in topological order on the listener thread. Construct each needed operator once per attempt through the existing
factory; call its ordinary Arrow transform contract directly.

For ordinary nodes, supply the single resolved parent table. Generic ordinary multi-table output is outside initial
streaming support; branching outputs remain separate route-specific tables.
For branching, use the downstream node's `link_id` as in batch execution. Select the table through
`metadata["branches"][route]["result_index"]` rather than list order or output-edge labels. For merges, build `tables`
under the compiled `input_edges`/`input_links` names and invoke the existing merge transform contract.

Track empty output as a resolved route. Skip an ordinary node whose selected input is empty. A merge waits for every
parent route to resolve, then receives the populated inputs and preserves the existing merge behavior of filtering
empty inputs and passing a single populated input through. If all input routes are empty, resolve an empty output.
Do not recursively mark a shared merge or its populated sibling as skipped when one route empties.

Use `OperatorUtils` for configured feature drops/renames on every output table. Preserve existing feature-drop
propagation; rename-aware updates to propagated metadata remain deferred under task 2.5. Empty-content and
zero-byte filtering and skipped metadata remain operator-owned. Do not invoke the batch helper's incremental persistence
side effects. Retain branch metadata
until routing has finished; do not remove internal metrics prematurely.

Validate transform result shape and inspect failed-document counts/records and failure status. Any reported failure
fails the attempt, even if the operator returned normally. Intentional filtering and skips alone remain successful.
Stop all remaining node execution after failure, including other pending branches, and propagate contextual failure.

Alternative: call `PythonOperatorExecutor.execute()` directly. Rejected because that introduces data-access wrapping,
deleted-row tracking, and job/incremental concerns. Only suitable stateless behavior is shared.

### 6. Make resources attempt-scoped and cleanup unconditional

Maintain an ownership list for every constructed operator. Release instances after their work is complete, and use
an outer `finally` to cover preparation/runtime errors and any constructed but skipped operator. Cleanup must be
idempotent, invoke supported `cleanup()` hooks, log hook failures, and continue releasing other instances. Drop table
and instance references before returning or raising.

Declare a no-op `cleanup()` method on `AbstractOperator`; resource-owning operators override it. Both the batch Python
executor and streaming engine call this method directly.

Do not add parquet snapshots, job logs, or batch finalization artifacts. Preserve configured chunk/embedding spill
behavior. Explicit sinks still write their configured outputs. Existing operators that already work without job context use
that mode; unsupported job-dependent behavior fails explicitly with operator context, never a fabricated job.

Fresh instances keep deduplication state isolated between events without adding a shared resource lifecycle.

### 7. Acknowledge one processing outcome per event

Keep one processing loop with no application queue:

1. Poll one record, check the stop flag again before beginning new work, deserialize, and validate it.
2. For a valid event, call dispatch once and wait for the complete flow to return or fail.
3. Report the terminal outcome and attempt the existing message-specific synchronous commit after either success or
   processing failure. Then continue to the next record.
4. Invalid records are reported and committed without flow execution. Broker error records remain diagnostic only.
5. Log commit exceptions and partition errors separately; preserve the processing outcome and continue. Later replay
   remains possible if the commit fails.

Do not automatically retry a failed flow in this change. A retry starts from ingest regardless of the stage that
failed, and earlier operators or sinks may already have persisted state. Without stage-aware failure classification and
reconciliation of persisted writes, blind retries can duplicate or conflict with stored output. Future retry behavior
requires a separate design for stage-specific retry policy and persisted-state reconciliation. Until then, the listener
reports the failure, attempts the message commit, and moves to the next event. No retry-count environment setting is
added.

### 8. Drain the processing thread during shutdown

`stop()` is awaitable: it sets the stop flag to prevent new events from starting and waits for the listener thread for
up to five seconds. Run the join through `asyncio.to_thread` so the asyncio event loop remains responsive.

An active event continues through execution, cleanup, terminal reporting, and its offset-commit attempt before the
listener closes the consumer and exits its processing thread. If the thread remains active after five seconds,
`stop()` logs a timeout warning and returns; the event and consumer thread are not cancelled, and the consumer closes
when that thread later reaches its normal exit path. Running operators are allowed to finish. If stop arrives after poll
but before new event execution, leave that record uncommitted and exit. Preserve idempotent start/stop behavior.

Automatic commits/offset storage remain disabled, so unfinished work is not committed by this shutdown path. If the
process terminates while the daemon listener thread is still active after the wait expires, the active event may remain
uncommitted. The five-second wait bounds the shutdown caller's wait; it does not forcibly terminate an operator.
Forced cancellation and recovery policy remain deferred under [STR-008](#str-008---forced-termination-during-active-processing).

Alternative: cancel the running transform at the timeout. Rejected because existing synchronous operators have no safe
general cancellation contract.

## Risks / Trade-offs

- **In-memory expansion and model load cost** -> Keep one event active, release resources, and test multi-row/chunk
  output and repeated event delivery. Large documents can still exceed memory and reduce throughput.
- **Behavior drift from executor bypass** -> Add focused parity tests for metadata, renames/drops, empty documents,
  branch indices, merge names, vault resolution, custom operators, and sink features. Share only narrow pure helpers.
- **Job-dependent operator assumptions** -> Retain existing no-job-context behavior; test built-in ingest, chunking,
  embeddings, deduplication, and storage/sink paths without creating or attaching jobs. Fail unsupported extensions
  explicitly with operator context.
- **Shutdown integration** -> Wait asynchronously and validate ordinary stop requests during active event processing.

## Migration Plan

1. Add and test the runtime independently, then wire it through `EventStreamingFactory` and replace HTTP dispatch.
   Keep existing REST/CLI/library paths and opt-in listener startup intact; no schema migration is required.
2. Update the streaming guide and Docker sample settings to describe actual completion, failure-and-skip behavior,
   no job history, commit timing, and graceful shutdown. Remove only obsolete
   HTTP-submission-specific API URL settings; retain that variable if another consumer still needs it.
3. Stop the old consumer, drain its previously submitted asynchronous jobs, and deploy the new version with the same
   group/topic configuration. Do not run mixed old/new listener versions in one
   group during cutover because their acknowledgement meanings differ.
4. Run the existing event-streaming sample end to end, verifying sink results, failure handling, commit ordering,
   and absence of newly created event job records. Run REST/CLI/library regressions and the strict change validator.
5. Roll back by draining/stopping the new listener, restoring the prior version and HTTP dispatch configuration, and
   restarting it. Existing committed offsets are not rewound automatically; terminally skipped events require explicit
   operator-managed replay. No database rollback is required.

## Deferred backlog

All entries below are **deferred and unprioritized**. They are outside the current change's requirements, tasks,
acceptance criteria, and release gates. Recording an item does not authorize its implementation. Promotion follows
the proposal's [scope control](proposal.md#scope-control), normally through a separate OpenSpec change.

STR-001 and STR-002 capture known operational problems and their associated failure-reproduction work.
STR-003 through STR-006 capture proposed future enhancements. STR-007 and STR-008 capture additional operational
corner cases for future consideration.

### STR-001 - Processing exceeds the Kafka poll interval

**Type:** Corner case and safeguard. **Status:** Deferred.

Synchronous processing and cleanup can outlast `max.poll.interval.ms`, causing ownership loss and failed
offset commits. Future work can evaluate handling-time budgets, poll-interval configuration, processing deadlines,
and polling/processing separation. Reproducing overruns and checking ownership/commit behavior belongs to that work.
No poll-interval setting, deadline, or overrun safeguard is required by this change.

### STR-002 - Shared dependency outage consumes valid backlog

**Type:** Corner case and safeguard. **Status:** Deferred.

A shared source, model, or sink outage can cause successive valid events to fail and be skipped under the current
commit-after-failure policy. Future work must decide outage classification, consumption pause or circuit breaking,
recovery, and the corresponding offset policy before adding a safeguard. Outage reproduction and backlog-loss
experiments belong to that future change.

### STR-003 - Compiled-flow caching

**Type:** Enhancement. **Status:** Deferred.

Preparing flows for every event repeats compilation and metadata work. Future design must define cache identity and
reliable invalidation when saved definitions, mappings, or operator availability change. Current execution continues
to load and prepare a flow for each event.

### STR-004 - Dead-letter routing and published completion events

**Type:** Enhancement. **Status:** Deferred.

Failed events have no dead-letter destination, and downstream systems receive no published completion event.
Future work needs a shared Kafka producer, payload contracts, publish-failure handling, and an explicit relationship
between publication and offset commits. Current notification remains an in-process outcome and correlated logs.

### STR-005 - Selective model and resource warming

**Type:** Enhancement. **Status:** Deferred.

Fresh operator instances can repeatedly load expensive resources. Future design must establish safe sharing,
event-state isolation, lazy initialization, idle eviction, and cleanup ownership before retaining resources across
attempts. Current operator instances remain fresh and attempt-scoped.

### STR-006 - Concurrent processing and polling separation

**Type:** Enhancement. **Status:** Deferred.

One synchronous event limits throughput. Future work needs bounded workers, backpressure, partition ordering,
correct offset progression, shutdown semantics, and an explicit strategy for per-routing-key scheduling.
Current execution retains one active event per listener with no application queue or worker pool.

### STR-007 - Retry or redelivery after partial sink writes

**Type:** Corner case and delivery guarantees. **Status:** Deferred.

An event can write some sink output before failing, or finish its sink work before an offset commit fails. Redelivery
can repeat those side effects. Automatic processing retries are excluded until failure stages can be classified and
persisted writes can be reconciled. Future work must decide idempotency, stage-specific retry rules, reconciliation,
and any stronger sink/offset guarantees before adding transactional writes, rollback, deduplication across events, or
replay tooling. Current work preserves configured sink behavior and existing commit-error reporting.

### STR-008 - Forced termination during active processing

**Type:** Corner case and recovery. **Status:** Deferred.

An external kill or crash can interrupt an operator or separate sink completion from offset commitment.
Future work can define bounded termination, durable progress, and recovery/resume semantics and validate crash/restart
behavior. Current scope covers cooperative draining shutdown only; it introduces no crash-recovery protocol.

### Capturing new discoveries

Append the next unused `STR-NNN` entry for any additional unplanned requirement, corner case, safeguard, optimization,
or compatibility extension. Record its type/status, problem and impact, source or reproduction context, and decisions
needed for a future change. Link any affected scope ID/task if it blocks current work, and report that blocker.
Do not add backlog entries to the implementation checklist or claim their tests as current acceptance criteria.
