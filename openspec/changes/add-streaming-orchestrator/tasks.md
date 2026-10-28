# Tasks

Each task is scoped to at most two hours; estimates include its focused verification. Activate `.venv` before Python
commands. Read the proposal, design, and both capability deltas before implementation. All work is backend-only.
The proposal's [Scope](proposal.md#scope) is the sole scope authority. The
[deferred backlog](design.md#deferred-backlog) is tracking only and is excluded from this checklist and acceptance.
Record new unplanned work there; report blockers instead of expanding tasks or weakening requirements.

| Task group | Scope coverage |
| --- | --- |
| 1. Saved-flow preparation and metadata | S01; verification under S08 |
| 2. Attempt configuration and operator invocation | S02-S04; verification under S08 |
| 3. Sequential DAG execution and route behavior | S03; verification/documentation under S08 |
| 4. Direct dispatch and composition | S05; verification/documentation under S08 |
| 5. Retry policy and Kafka acknowledgement | S06; verification/documentation under S08 |
| 6. Listener lifecycle and shutdown | S07; verification/documentation under S08 |
| 7. Integration and final verification | S08, checking only S01-S07 |

## 1. Saved-flow preparation and metadata

- [ ] 1.1 [backend] Add streaming module structure and contextual attempt-error types (45 min); verify imports and
  tests for stage/flow/node context with original exception preservation.
- [ ] 1.2 [backend] Load isolated flow definitions through injected `FlowService` and reuse authoring/Elyra conversion
  (90 min); test both formats, missing/unknown formats, saved-flow updates, and definition immutability.
- [ ] 1.3 [backend] Add lightweight executable-graph integrity checks and topological ordering (90 min); test cycles,
  empty graphs, invalid node IDs/operator names, duplicate IDs, missing/inconsistent edges, disconnected nodes,
  multiple roots, and a non-ingest root, including when saved configuration disables full validation.
- [ ] 1.4 [backend] Resolve built-in/custom operators through the existing Python factory (60 min); test custom
  discovery priority, disabled custom operators, unavailable types, and no execution during identity checks.
- [ ] 1.5 [backend] Add the feature-propagation constructor and method guards from Decision 3a (120 min); test required
  explicit enablement, conflicting discovery arguments, session logging context, and preservation of orchestrator-based
  construction. Verify all four full-validation entrypoints reject propagation-mode use before side effects, and the
  streaming path calls only per-node propagation without operator validation or a batch orchestrator.
- [ ] 1.6 [backend] Inject prepared feature views and global metadata into isolated node configurations (90 min); test
  extraction, embedding metadata, and merge link-name disambiguation with `test_features_propagator.py` regressions.
  Share one attempt-local metadata provider between validator and propagator using identical discovery settings; test
  custom priority, explicit disablement, one metadata load, instance-local cache reuse for a fixed definition, and fresh
  state after success/failure and on retries or later events with changed definitions/configuration.

## 2. Attempt configuration and operator invocation

- [ ] 2.1 [backend] Preserve global/node/override precedence and resolve vault references in fresh dictionaries
  (90 min); test precedence, mutation isolation, and that logs contain no resolved credential values.
- [ ] 2.2 [backend] Inject `input_event` and forced reprocessing after saved overrides (60 min); test create/update,
  source filters, provider-native reference binding, unsupported binding, and no expansion to configured collections.
- [ ] 2.3 [backend] Apply streaming-only in-memory settings, including `memmap_threshold=0`, after all overrides
  (60 min); test that node overrides cannot enable batching or chunk/embedding intermediate spill files.
- [ ] 2.4 [backend] Scope and restore `SessionInfo` with event transaction/flow correlation and no job/run identifiers
  (60 min); test success, failure, stale config IDs, and restoration of a pre-existing batch session.
- [ ] 2.5 [backend] Implement direct Arrow transform invocation and result-contract checks (90 min); test ingest input,
  typed table outputs, metadata dictionaries, invalid results, and ordinary multi-row outputs. Verify chunking keeps
  one document row with list-valued `chunked_content`, document IDs, and retained column types.
- [ ] 2.6 [backend] Apply existing output drop/rename utilities to every output table (60 min); port relevant assertions
  from `test_python_operator_executor_features.py` and verify metadata/table consistency downstream.
- [ ] 2.7 [backend] Preserve empty-content/zero-byte filtering and skipped metadata through a pure table helper
  (90 min); test existing filtering semantics without incremental persistence or job-statistics writes.
- [ ] 2.8 [backend] Convert raised errors and failed-document/status metadata into contextual attempt failure
  (60 min); test ingest's normal-return failure path, partial failures, sink errors, and intentional skips as success.
- [ ] 2.9 [backend] Release all constructed operators in unconditional cleanup and restore attempt state (90 min);
  test success, transform failure, cleanup failure, idempotent release, and fresh local deduplication on retry.

## 3. Sequential DAG execution and route behavior

- [ ] 3.1 [backend] Execute linear flows in dependency order and signal completion after sinks finish (90 min); test
  unordered node definitions, no asynchronous work submission, and no returned document data or job-run handle.
- [ ] 3.2 [backend] Resolve branching outputs by declared route and metadata result index (90 min); test two distinct
  tables, reversed branch ordering, nested branches, unknown routes, and invalid indices.
- [ ] 3.3 [backend] Supply multi-input merge tables under compiled link names (90 min); test row merges and both
  supported column-merge modes against existing `MergeOperator` behavior.
- [ ] 3.4 [backend] Resolve empty routes without suppressing populated siblings or shared merges (90 min); test empty
  ingest, all-empty branches, one populated branch, reconvergence, and no-op completion without sink writes.
- [ ] 3.5 [backend] Preserve applicable ordinary multi-table outputs without silent data loss (60 min); test ordered
  schema-compatible concatenation and explicit failure for incompatible ambiguous output.
- [ ] 3.6 [backend] Stop all remaining nodes after attempt failure (60 min); test that pending sibling nodes and sinks
  are not invoked, with cleanup still running and a subsequent attempt able to execute normally.
- [ ] 3.7 [backend] Document runtime compatibility and exclusions in the existing event streaming guide (60 min);
  verify coverage of formats, features, filtering, branch/merge behavior, local deduplication, and in-memory limits.

## 4. Direct dispatch and composition

- [ ] 4.1 [backend] Inject the streaming orchestrator into `EventDispatchService` and replace HTTP submission (60 min);
  replace dispatch tests to assert mapping lookup, synchronous completion/failure, and no `httpx.post` calls.
- [ ] 4.2 [backend] Wire configured flow repositories, services, and the runtime in `EventStreamingFactory` (90 min);
  extend factory tests to verify repository selection and absence of job-manager/statistics construction by this wiring.
- [ ] 4.3 [backend] Add event/stage/flow/operator correlation to in-process outcomes and listener diagnostics (60 min);
  test failures before mapping, after preparation, and inside operators without inventing missing identifiers.
- [ ] 4.4 [backend] Remove the dispatch API URL dependency and obsolete event-sample references (45 min); search all
  usages before removal and verify unrelated consumers retain any settings they still require.
- [ ] 4.5 [backend] Update guide and Docker README sections that describe asynchronous jobs and job-run IDs (60 min);
  verify they describe synchronous completion, sink verification, and absence of event job history with valid links.

## 5. Retry policy and Kafka acknowledgement

- [ ] 5.1 [backend] Add validated `DOCPIPE_EVENT_MAX_RETRIES` with the default from the design and log its active value
  (60 min); test the default, explicit values, invalid input, and disabled mode.
- [ ] 5.2 [backend] Add immediate bounded retries around complete dispatch (90 min); test zero retries, success after
  failure, exhaustion, missing mappings/flows, re-resolution between attempts, and fresh per-attempt operator state.
- [ ] 5.3 [backend] Enforce event serialization through terminal reporting and the commit attempt (90 min); use
  ordered listener traces to prove no next poll, queued application task, or intermediate commit during retries.
- [ ] 5.4 [backend] Retain invalid-event and broker-error handling separately from processing retries (60 min); test
  malformed serialization/schema, unsupported operations, skipped execution, and continuation to a valid record.
- [ ] 5.5 [backend] Preserve synchronous message commits and separate commit failures from processing outcomes
  (60 min); test manual commit/store flags, terminal success/exhaustion commits, and existing commit error logging.
- [ ] 5.6 [backend] Add terminal retry/failure diagnostics with Kafka context (45 min); assert outcome, attempt count,
  stage, known flow/operator IDs, and distinct processing versus commit errors without document content or secrets.
- [ ] 5.7 [backend] Document retry configuration and commit-after-exhaustion in the guide and Docker sample
  environment/Compose configuration (60 min); verify the documented retry default matches code.

## 6. Listener lifecycle and shutdown

- [ ] 6.1 [backend] Replace the five-second shutdown join with an awaitable drain until thread exit and post-poll stop
  checks (90 min); test stop before polling, between poll/dispatch, during active operators/sinks/retries, and repeated
  start/stop calls. Verify no running operator is cancelled and no next event starts after the stop request.
- [ ] 6.2 [backend] Verify API lifespan waits for real listener exit and preserves opt-in startup (60 min); update
  `test_event_streaming_startup.py` and listener tests to prove `stop()` stays pending through retries, cleanup,
  terminal reporting, and the commit attempt, including commit failure, with consumer closure before thread exit.
  Verify unrelated asyncio tasks run while shutdown awaits thread exit and unfinished work remains uncommitted.
- [ ] 6.3 [backend] Document graceful shutdown, cutover, and rollback in the Docker README (45 min); verify the
  procedure drains active processing and previously submitted asynchronous jobs before switching versions, and states
  that draining has no timeout and an operator that never returns can keep shutdown pending indefinitely.

## 7. Integration and final verification

- [ ] 7.1 [backend] Add a saved-flow/mapping-to-dispatch integration test with real service/compiler/operator wiring
  and a controlled sink (120 min); cover authoring and Elyra, create/update, sink persistence, and no event job records.
- [ ] 7.2 [backend] Add an integrated branch/merge flow test with real routing and feature propagation (90 min);
  verify empty-sibling behavior, feature transformations, multi-row output, and failure-triggered full retry.
- [ ] 7.3 [backend] Exercise the Docker event-streaming sample and multiple sequential events with configured sinks
  (120 min); record sink results, commit ordering, retry counts, state isolation, and resource release evidence.
- [ ] 7.4 [backend] Run relevant existing REST job-run, CLI, library, flow-engine, operator-loading, deduplication,
  and micro-batching regression suites (90 min); verify batch contracts remain intact and report unrelated failures.
- [ ] 7.5 [backend] Run `uv run ruff check --fix .`, `uv run mypy .`, and `uv build` (90 min); verify relevant Python
  lint/type/build checks pass, separating pre-existing failures and avoiding unrelated code changes.
- [ ] 7.6 [backend] Run `openspec validate add-streaming-orchestrator --strict` and inspect the final diff (45 min);
  verify acceptance evidence and S01-S08 coverage for every change, and confirm deferred backlog work was
  not implemented.
