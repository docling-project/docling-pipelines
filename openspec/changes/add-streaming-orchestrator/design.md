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
- Make the boundary between attempt execution, event retry policy, and Kafka acknowledgement explicit.
- Keep mutable state and table lifetimes scoped to an attempt, including failure and cleanup paths.

**Non-Goals:**

- Turn `StreamingOrchestrator` into another `AbstractOrchestrator` implementation or add it to the batch factory.
- Invent job/run identifiers to satisfy operator assumptions, or share deduplication admissions between events.
- Add frontend components or SCSS modules. Carbon layout and token rules have no affected surface here.
- Implement the corner-case safeguards, enhancements, or associated validation scenarios in the
  [deferred backlog](#deferred-backlog). Those items remain future work outside this change.

## Decisions

### 1. Separate synchronous runtime and retry owner

Add `core/orchestration/streaming/` with a `StreamingOrchestrator` and small preparation/operator-runner helpers.
The orchestrator exposes `execute(*, flow_id, event) -> None`: normal return means completion; a contextual execution
exception means attempt failure. It does not return tables or allocate a durable execution identifier.

`EventDispatchService` receives mapping service and orchestrator dependencies. `dispatch(*, event) -> None` resolves
the current mapping and calls `execute()`. `KafkaEventListener` owns the entire event retry loop, terminal reporting,
and commit decision. Every retry invokes dispatch again and re-fetches/recompiles the selected flow.

Use a typed streaming execution error containing stage, flow ID when known, and node identity when known, preserving
the original cause. Routing failures before orchestration are labelled by the dispatcher/listener. This gives useful
diagnostics without job statistics. Failure notification means raising the in-process outcome to the listener; external
notifications and Kafka publications remain deferred. Dispatch emits correlated completion diagnostics with the selected
flow ID before returning; listener diagnostics add attempt count and Kafka record context.

The streaming runtime logs source-filter skips as no-op completions with event/flow correlation and the available reason
before normal return. The listener keeps its completion/commit policy; `execute()` and `dispatch()` return `None`.

Alternative: reuse `JobManagementService`, `FlowExecutor`, or `PythonOrchestrator`. Rejected because each couples
execution to jobs, batch data access, or finalization. An executor pool is unnecessary for one synchronous active event.

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
| Transport | Kafka deserialization, retries, terminal diagnostics, message commits, and lifecycle |

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

Reuse `FlowValidator.propagate_features_per_node()` in feature-propagation mode as defined in Decision 3a. This mode
computes per-node column/feature views and propagated parameters without processing documents or performing full
operator validation. Reuse the existing feature traversal, merge disambiguation, and propagated global parameters
rather than duplicating feature logic.

Alternative: disable all preparation or run full validation per event. The first loses required sink metadata and
integrity checks; the second repeats expensive service/configuration validation on the consumer's critical path.

### 3a. Define the feature-propagation construction and lifetime contract

Extend the existing constructor with this keyword-only surface:

```python
def __init__(
    self, *, orchestrator: AbstractOrchestrator | None = None,
    custom_operator_packages: list[str] | None = None, enable_custom_operators: bool | None = None,
    feature_propagator: FeaturePropagator | None = None,
) -> None:
```

- With an orchestrator, retain the existing validation mode, logging context, and optional propagator injection.
  Discovery settings come from the orchestrator. Explicit discovery arguments in this mode raise `ValueError` rather
  than silently overriding or conflicting with orchestrator settings.
- Without an orchestrator, select feature-propagation mode. Require an explicit boolean `enable_custom_operators`;
  omission raises `ValueError`. `custom_operator_packages=None` retains the existing factory meaning for that value.
  Read logging context from the current `SessionInfo`, including flow/event correlation, without creating job/run IDs.
- Streaming constructs a fresh validator and propagator for each attempt and leaves `feature_propagator` unset.
  Snapshot the effective discovery settings at construction, preserving an explicit `False` enablement value.
  Add explicit discovery inputs to `OperatorMetadata` and optional metadata-provider injection to `FeaturePropagator`.
  In feature-propagation mode, load internal feature metadata once and supply the same attempt-local metadata provider
  to both the validator and propagator. Do not let the propagator independently fall back to default discovery.
  Existing orchestrator-based callers retain their current construction and validation behavior.

The streaming preparation path has the following method contract:

| Method | Streaming preparation |
| --- | --- |
| `propagate_features_per_node()` | Call once after compilation, graph checks, and operator-class resolution |
| `validate()` | Skip |
| `validate_dag()` | Skip |
| `validate_dag_with_features()` | Skip |
| `validate_last_operator()` | Skip |
| Operator `validate()` | Never invoke during preparation |

The four skipped `FlowValidator` validation entrypoints raise `RuntimeError` before validation work if called on a
feature-propagation-mode instance. Per-node metadata computation continues to use the existing propagation helpers.

"Compilation and runtime integrity checks" specifically means saved-format conversion plus the following checks,
all completed before document processing and independently of full validation or `disable_validation`:

- A nonempty executable DAG with valid node IDs and operator names, and no duplicate node IDs.
- Resolvable, consistent input/output edges and an acyclic graph ordered with `sort_dag_topologically()`.
- Exactly one root, whose operator is in the Ingest category, and every node reachable from that root.
- Every referenced operator class resolves through the configured Python factory and discovery priority, without
  constructing model-bearing operators merely to check identity.

Keep `_node_features_cache` instance-local and initially `None`. A validator is bound by contract to one fixed prepared
definition, effective global configuration, and discovery snapshot for its entire lifetime. Streaming computes the
cache once; repeated access for that same definition can reuse it. Discard the validator, metadata provider, propagator,
and cached results when the attempt ends, including failures. A retry or later event creates fresh instances and
recomputes metadata. Instances remain non-thread-safe and must never be shared between attempts or concurrent callers;
no cross-attempt cache, cache invalidation mechanism, or synchronization is introduced.

### 4. Build configuration with explicit streaming overrides

Preserve current precedence: global configuration, node configuration, then the existing global override keyed by
node name, node ID, or operator type. Inject node ID/name and prepared feature metadata into a fresh dictionary.
Resolve vault references using the existing secret provider without logging resolved values.

Apply these execution-owned overrides last, including against per-node values:

- Ingest receives the validated event serialized as `input_event` and `force_ingest=true`. Binding remains inside the
  existing source adapter contract; no path-to-provider-ID conversion or additional credential lookup is introduced.
- Batching and batch-only execution settings do not activate the batch engine. The runtime always uses in-memory
  tables and forces `memmap_threshold=0`, the chunker's existing no-spill behavior; embeddings then remain in memory.
- Remove stale job/run identifiers and batch bookkeeping fields from effective operator configuration.

Temporarily install a fresh `SessionInfo` with `flow_id` and `transaction_id=str(event.event_id)` and unset job/run IDs.
Read and restore the previous context through existing session accessors in a `finally` block. Do not pass session or
job identifiers through method arguments. Keep operator-local deduplication isolated by fresh instances on each retry.

Alternative: mutate the loaded definition or reuse a previous event's instances. Rejected because ingest binding,
branch metadata, feature state, and deduplication are mutable and could suppress or redirect later work.

### 5. Execute tables and routes without batch data-access wrappers

Maintain an attempt-local map from node IDs to output tables, metadata, and resolved empty-route state. Execute nodes
in topological order on the listener thread. Construct each needed operator once per attempt through the existing
factory; call its ordinary Arrow transform contract directly.

For ordinary nodes, supply the resolved parent table. Preserve all rows from applicable ordinary multi-table output
using ordered Arrow concatenation where the output schema permits it; fail incompatible ambiguous output explicitly.
For branching, resolve the selected table through `metadata["branches"][route]["result_index"]`, validating bounds and
route identity rather than inferring the route from list order. For merges, build `tables` under the compiled
`input_edges`/`input_links` names and invoke the existing merge transform contract.

Track empty output as a resolved route. Skip an ordinary node whose selected input is empty. A merge waits for every
parent route to resolve, then receives the populated inputs and preserves the existing merge behavior of filtering
empty inputs and passing a single populated input through. If all input routes are empty, resolve an empty output.
Do not recursively mark a shared merge or its populated sibling as skipped when one route empties.

Use `OperatorUtils` for configured feature drops/renames on every output table. Preserve existing empty-content and
zero-byte filtering and skipped metadata through a narrowly shared pure table helper or a streaming helper using
existing utilities. Do not invoke the batch helper's incremental persistence side effects. Retain branch metadata
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
and instance references and restore session state before returning or raising.

Keep intermediates in memory without parquet snapshots, chunk spill files, job logs, or batch finalization artifacts.
Explicit sinks still write their configured outputs. Existing operators that already work without job context use
that mode; unsupported job-dependent behavior fails explicitly with operator context, never a fabricated job.

Fresh instances make retries and deduplication behavior predictable without adding a shared resource lifecycle.

### 7. Define retry, acknowledgement, and configuration together

Keep one processing loop with no application queue:

1. Poll one record, check the stop flag again before beginning new work, deserialize, and validate it.
2. For a valid event, attempt full dispatch up to `1 + max_retries` times with no delay or intermediate commit.
3. On completion or exhaustion, emit the terminal outcome, then call the existing message-specific synchronous commit.
4. Invalid records are reported and committed without execution retries. Broker error records remain diagnostic only.
5. Log commit exceptions and partition errors separately; preserve processing outcome and continue without an immediate
   pipeline rerun. Later replay is possible and no transactional sink/offset guarantee is introduced.

Add `DOCPIPE_EVENT_MAX_RETRIES` with proposed default `0` to preserve the existing single-attempt default while allowing
bounded retries. Parse it before listener startup as a nonnegative integer and log the active value. This change adds
no poll-interval configuration or special handling for the deferred corner cases.

### 8. Drain the processing thread during shutdown

`stop()` is awaitable: it sets the stop flag to prevent new events from starting and returns only after the listener
thread exits. Waiting for thread exit must keep the asyncio event loop responsive; the shutdown caller continues
awaiting completion while unrelated asynchronous tasks can run. Replace the current five-second join with this wait.

An active event finishes its configured retry sequence, cleanup, terminal reporting, and offset-commit attempt before
the listener closes the consumer and exits its processing thread. `stop()` remains pending throughout that work,
including sink writes and the commit attempt. Running operators are allowed to finish; a stop request neither cancels
nor abandons them and does not count as retry exhaustion. If stop arrives after poll but before new event execution,
leave that record uncommitted and exit. Preserve idempotent start/stop behavior.

Automatic commits/offset storage remain disabled, so unfinished work is not committed by this shutdown path. There is
no drain timeout in this change: an operator that never returns can keep shutdown pending indefinitely. Bounded
termination and forced-cancellation policy remain deferred under
[STR-008](#str-008---forced-termination-during-active-processing).

Alternative: bound the join at five seconds or cancel the running transform. The former falsely completes shutdown;
the latter has no safe general contract across existing synchronous operators.

## Risks / Trade-offs

- **In-memory expansion and model load cost** -> Keep one event active, release resources, and test multi-row/chunk
  output and repeated attempts. Large documents can still exceed memory and reduce throughput.
- **Behavior drift from executor bypass** -> Add focused parity tests for metadata, renames/drops, empty documents,
  branch indices, merge names, vault resolution, custom operators, and sink features. Share only narrow pure helpers.
- **Job-dependent operator assumptions** -> Clear job/run context explicitly; test built-in ingest, chunking,
  embeddings, deduplication, and storage/sink paths without jobs. Fail unsupported extensions explicitly.
- **Shutdown integration** -> Drain asynchronously and validate ordinary stop requests during retries and sink writes.

## Migration Plan

1. Add and test the runtime independently, then wire it through `EventStreamingFactory` and replace HTTP dispatch.
   Keep existing REST/CLI/library paths and opt-in listener startup intact; no schema migration is required.
2. Update the streaming guide and Docker sample settings to describe actual completion, retries, no job history,
   commit timing, and graceful shutdown. Remove only obsolete
   HTTP-submission-specific API URL settings; retain that variable if another consumer still needs it.
3. Stop the old consumer, drain its previously submitted asynchronous jobs, and deploy the new version with the same
   group/topic configuration and the chosen retry setting. Do not run mixed old/new listener versions in one
   group during cutover because their acknowledgement meanings differ.
4. Run the existing event-streaming sample end to end, verifying sink results, sequential retries, commit ordering,
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

Synchronous processing, retries, and cleanup can outlast `max.poll.interval.ms`, causing ownership loss and failed
offset commits. Future work can evaluate handling-time budgets, poll-interval configuration, processing deadlines,
and polling/processing separation. Reproducing overruns and checking ownership/commit behavior belongs to that work.
No poll-interval setting, deadline, or overrun safeguard is required by this change.

### STR-002 - Shared dependency outage consumes valid backlog

**Type:** Corner case and safeguard. **Status:** Deferred.

A shared source, model, or sink outage can exhaust retries for successive valid events. The initial commit-after-
exhaustion policy can then skip those events. Future work must decide outage classification, consumption pause or
circuit breaking, recovery, and the corresponding offset policy before adding a safeguard. Outage reproduction and
backlog-loss experiments belong to that future change; the current generic retry/commit policy remains as specified.

### STR-003 - Compiled-flow caching

**Type:** Enhancement. **Status:** Deferred.

Preparing flows for every event repeats compilation and metadata work. Future design must define cache identity and
reliable invalidation when saved definitions, mappings, or operator availability change. Current execution continues
to load and prepare a flow for each attempt.

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

An attempt can write some sink output before failing, or finish its sink work before an offset commit fails.
Retry/redelivery can repeat those side effects. Future work must decide idempotency, reconciliation, and any stronger
sink/offset guarantees before adding transactional writes, rollback, deduplication across events, or replay tooling.
Current work preserves configured sink behavior and existing commit-error reporting.

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
