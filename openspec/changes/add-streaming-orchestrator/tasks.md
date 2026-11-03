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
| 5. Failure handling and Kafka acknowledgement | S06; verification/documentation under S08 |
| 6. Listener lifecycle and shutdown | S07; verification/documentation under S08 |
| 7. Integration and final verification | S08, checking only S01-S07 |

## Review audit (2026-11-03)

Reviewed `streaming-209-impl-p3` at `ecdd46f3`. Checked implementation subitems below record code already present;
parent tasks remain unchecked when functionality or their listed verification is still pending. The initial audit did
not change acceptance criteria. The follow-up below records the subsequent scope decisions agreed during review.

- Existing focused streaming, event-streaming, and API-startup suites: **52 passed**.
- Batch Python executor lifecycle suite: **7 passed** after updating the stale NOOP assertion to verify the inherited
  default cleanup hook is invoked and the released operator is rebuilt. Together, the affected suites have **59 passed**.
  Including the existing Elyra converter suite, the routing-fix verification has **99 passed**.
- Read-only runtime probes confirmed create/update single-file binding, forced ingestion, saved-definition isolation,
  custom-loader rejection, cleanup/reference clearing, dispatch/commit ordering, and separate commit-error logging.
  The follow-ups complete completion-only returns, contextual operator failures, and Elyra branch routing.
- [x] Branch routing reads only the downstream node's existing `link_id`, matching batch execution. Real
  branching/NOOP regression tests pass for both authoring compilation and Elyra conversion, including reordered
  nodes, distinct outputs, and saved-definition isolation. Hand-built runtime fixtures also provide `link_id`.
- [x] Compatibility scope agreed during review: built-in operators only, one table per ordinary output, and
  operator-owned empty-content filtering. Custom operators, ordinary multi-table concatenation, and direct
  branching-to-merge support are outside the initial streaming scope.
- [x] Completion/failure implementation is complete: return `None`, preserve operator identity and original exceptions,
  and reuse listener event ID/Kafka coordinates/tracebacks. By agreement, no stage labels, flow ID plumbing, extra
  dispatcher/orchestrator error wrappers, or orchestrator-owned skip reporting are required. Remaining failure-path
  verification stays unchecked below; documentation and verification work remain outside this implementation scope.
- Spec reconciliation is complete: freshness/cleanup scenarios refer to later events, output-table renames are
  distinguished from deferred rename-aware metadata propagation, and consumer-close scenarios follow the bounded
  shutdown wait. Proposal/design wording preserves the agreed closures. Strict OpenSpec validation passes.

## 1. Saved-flow preparation and metadata

- [ ] 1.1 [backend] Add streaming module structure and reuse existing error reporting (45 min); verify imports and
  tests for event/node context with original exception preservation.
  - [x] Streaming module structure is present.
  - [x] Reuse the listener's event ID and traceback; operator failures retain node context and original-cause chaining.
  - [ ] Complete the remaining context/error-path coverage.

- [ ] 1.2 [backend] Load isolated flow definitions through injected `FlowService` and reuse authoring/Elyra conversion
  (90 min); test both formats, missing/unknown formats, saved-flow updates, and definition immutability.
  - [x] Dispatch loads through injected `FlowService` on each event, converts either saved format, and isolates runtime
    configuration. Authoring dispatch and saved-definition immutability have existing test coverage.
  - [x] Elyra branch execution is covered by the real-converter routing regression under 3.2.
  - [ ] Remaining preparation/freshness/error-context coverage remains pending.

- [ ] 1.3 [backend] Add lightweight executable-graph integrity checks and topological ordering (90 min); test cycles,
  empty graphs, invalid node IDs/operator names, duplicate IDs, missing/inconsistent edges, disconnected nodes,
  multiple roots, and a non-ingest root, including when saved configuration disables full validation.
  - [x] Nonempty graph, edge endpoint, branch-link, merge/input-count, UUID parsing, and cycle/order checks are present.
  - [ ] Duplicate identities, consistent input/output edges, one ingest root/reachability, and full listed coverage
    remain pending; graph nodes currently overwrite duplicate IDs.

- [ ] 1.4 [backend] Resolve built-in operators through existing discovery (60 min); test unavailable types and
  no execution during identity checks.
  - [x] Ordinary and branching nodes use the existing Python factory; merge uses the built-in `MergeOperator`.
  - [x] [closed by agreement] Custom operators and custom merge selection are outside initial streaming support.
  - [ ] Up-front availability checks and remaining discovery coverage remain pending.

- [x] 1.5 [closed by agreement] Keep existing per-node feature propagation through the PythonOrchestrator-based
  setup. No constructor redesign, separate propagation mode, or shared metadata-provider/cache plumbing is needed.

## 2. Attempt configuration and operator invocation

- [x] 2.1 [closed by agreement] Keep existing global -> node -> runtime-parameter configuration, flow copy, and Vault
  resolution. Do not add keyed overrides or another copying/resolution layer.
- [ ] 2.2 [backend] Inject `input_event` and forced reprocessing after saved node configuration (60 min); test create/update,
  source filters, provider-native reference binding, unsupported binding, and no expansion to configured collections.
  - [ ] The legacy custom loader still needs an explicit rejection when it cannot bind an event file reference.
  - [x] Set `force_ingest=true` in the effective operator configuration.
  - [x] Inject the actual serialized event after saved node configuration. Review probes confirmed create/update
    binding to one referenced filesystem file, forced ingestion, and saved-definition immutability.
  - [ ] Complete remaining provider/filter binding verification; skip reasons and logging remain operator-owned.
- [x] 2.3 [closed by agreement] The synchronous graph engine does not start batch processing; preserve the configured
  `memmap_threshold` and chunk/embedding spill behavior without additional controls or spill-path tests.
- [ ] 2.4 [backend] Implement direct Arrow transform invocation and result-contract checks (90 min); test ingest input,
  typed table outputs, metadata dictionaries, invalid results, and ordinary multi-row outputs. Verify chunking keeps
  one document row with list-valued `chunked_content`, document IDs, and retained column types.
  - [x] Direct transform invocation and forwarding of document rows/list-valued chunks are present and covered by
    existing mocked-transform flow tests.
  - [ ] Result-contract checks remain pending: a terminal non-Arrow output can escape rejection when no output
    transformation accesses it. Real-operator/invalid-result coverage remains pending.

- [x] 2.5 [closed by agreement] Keep the existing output drop/rename behavior for each table. Rename-aware
  propagated metadata remains deferred because it requires broader shared feature-propagation changes.
- [x] 2.6 [closed by agreement] Empty-content/zero-byte filtering, skip metadata, and skip logging remain operator
  responsibilities. No generic content filtering helper is required in the orchestrator.
- [ ] 2.8 [backend] Convert raised errors and failed-document/status metadata into contextual attempt failure
  (60 min); test ingest's normal-return failure path, partial failures, sink errors, and intentional skips as success.
  - [x] Raised errors propagate and failed-document counts/records or failed statuses stop execution.
  - [x] Add node context with the existing error type and omit failed-document reason text from terminal diagnostics.
  - [ ] Complete the full listed failure/skip coverage.

- [x] 2.9 [complete] Add the default no-op `AbstractOperator.cleanup()` hook and call it from batch release and
  streaming's unconditional `finally` cleanup. Existing cleanup overrides use `cleanup(self) -> None`; no signature
  redesign is needed. The streaming engine tracks constructed instances for cleanup, then clears the list and output
  buffer so the temporary references are released. Cleanup hook failures are logged without preventing other cleanup.

## 3. Sequential DAG execution and route behavior

- [x] 3.1 [backend] Execute linear flows in dependency order and signal completion after sinks finish (90 min); test
  unordered node definitions, no asynchronous work submission, and no returned document data or job-run handle.
  - [x] Dependency ordering and synchronous execution through sinks are present.
  - [x] Public execution returns `None`; existing tests assert sink inputs and exercise reverse node ordering.

- [ ] 3.2 [backend] Resolve branching outputs by declared route and metadata result index (90 min); test two distinct
  tables, reversed branch ordering, nested branches, unknown routes, and invalid indices.
  - [x] The engine selects declared authoring-style routes through branch metadata result indices.
  - [x] Routing implementation complete: read only the downstream node's `link_id`, matching batch execution,
    with no `link_name` fallback or converter/schema changes. Real authoring/Elyra regression tests verify distinct
    branch outputs, IDs different from display labels, and reverse node ordering; all 99 focused tests pass.
  - [ ] Remaining nested/invalid-route coverage and malformed-index safeguards remain pending outside this fix.

- [ ] 3.3 [backend] Supply multi-input merge tables under compiled link names (90 min); test row merges and both
  supported column-merge modes against existing `MergeOperator` behavior.
  - [x] Built-in row merges receive named `input_links` tables and have existing branch/merge flow coverage.
  - [x] [closed by agreement] Direct branching-to-merge wiring and custom merge overrides are outside initial support.
  - [ ] Both column-merge modes still need the listed streaming coverage.

- [ ] 3.4 [backend] Resolve empty routes without suppressing populated siblings or shared merges (90 min); test empty
  ingest, all-empty branches, one populated branch, reconvergence, and no-op completion without sink writes.
  - [x] Empty ordinary/branching inputs resolve without invoking their transforms; existing merge behavior filters
    empty inputs. Empty-linear and empty-branching cases have passing coverage.
  - [ ] Complete all-empty, populated-sibling, shared-merge/reconvergence, and no-sink-write coverage.

- [x] 3.5 [closed by agreement] Ordinary operators produce one output table. Only branching produces route-specific
  tables, and merge consumes named upstream inputs. Generic ordinary multi-table concatenation is not supported.
- [ ] 3.6 [backend] Stop all remaining nodes after attempt failure (60 min); test that pending sibling nodes and sinks
  are not invoked, with cleanup still running and a subsequent attempt able to execute normally.
  - [x] The sequential loop exits on raised/reported failure; `finally` clears buffers and invokes cleanup.
  - [ ] Add pending-sibling/sink, cleanup-failure, and later-event regression coverage.

- [ ] 3.7 [backend] Document runtime compatibility and exclusions in the existing event streaming guide (60 min);
  verify coverage of formats, features, filtering, branch/merge behavior, local deduplication, and in-memory limits.

## 4. Direct dispatch and composition

- [x] 4.1 [backend] Inject the streaming orchestrator into `EventDispatchService` and replace HTTP submission (60 min);
  replace dispatch tests to assert mapping lookup, synchronous completion/failure, and no `httpx.post` calls.
- [ ] 4.2 [backend] Wire configured flow repositories, services, and the runtime in `EventStreamingFactory` (90 min);
  extend factory tests to verify repository selection and absence of job-manager/statistics construction by this wiring.
  - [x] Factory wiring uses `AssetRepositoryFactory`/`FlowService`, mapping service, and streaming runtime directly.
  - [ ] Extend existing mapping-storage coverage to flow repository selection and no-job-service wiring.

- [ ] 4.3 [backend] Add event/operator correlation to in-process outcomes and listener diagnostics (60 min);
  test failures before mapping, after preparation, and inside operators without inventing missing identifiers.
  Verify source-filter skips remain operator-owned while dispatch returns `None` and the listener attempts the offset
  commit without rerunning dispatch or sending external notifications.
  - [x] Listener diagnostics already log event ID, Kafka coordinates, and the failure traceback.
  - [x] Operator errors include node context for the existing listener traceback. Skip reasons and logging remain
    operator-owned; no orchestrator skip-reporting logic is required.
  - [ ] Complete the remaining diagnostic/error-path coverage.

- [x] 4.4 [backend] Remove the dispatch API URL dependency and obsolete event-sample references (45 min); search all
  usages before removal and verify unrelated consumers retain any settings they still require.
- [ ] 4.5 [backend] Update guide and Docker README sections that describe asynchronous jobs and job-run IDs (60 min);
  verify they describe synchronous completion, sink verification, and absence of event job history with valid links.

## 5. Failure handling and Kafka acknowledgement

- [x] 5.1 [backend] Keep one synchronous dispatch for each valid event and no automatic processing retries (60 min);
  verify a flow failure is reported and does not invoke the flow a second time.
- [x] 5.2 [backend] Commit a failed event once and continue to the next event (60 min); verify the failed event's commit
  is attempted before the next application poll.
- [x] 5.3 [backend] Enforce event serialization through terminal reporting and the commit attempt (60 min); use
  ordered listener traces to prove no next poll or second dispatch occurs before the failed event's commit attempt.
- [ ] 5.4 [backend] Retain invalid-event and broker-error handling separately from flow failures (60 min); test
  malformed serialization/schema, unsupported operations, skipped execution, and continuation to a valid record.
  - [x] Broker errors skip record commits; rejected payloads and processing failures are acknowledged without reruns.
  - [ ] Complete malformed-serialization, unsupported-operation, intentional-skip, and later-success coverage.

- [x] 5.5 [backend] Preserve synchronous message commits and separate commit failures from processing outcomes
  (60 min); test manual commit/store flags, success/failure commits, and existing commit error logging.
- [ ] 5.6 [backend] Add terminal success/failure diagnostics with Kafka context (45 min); assert outcome, event ID and known
  operator identity, and distinct processing versus commit errors without document content or secrets.
- [ ] 5.7 [backend] Document one-pass processing, commit-after-failure, and the future need for stage-aware retries with
  persisted-state reconciliation in the streaming guide (60 min).

## 6. Listener lifecycle and shutdown

- [ ] 6.1 [backend] Keep the five-second asynchronous shutdown join and post-poll stop checks (90 min); test stop before
  polling, between poll/dispatch, during active operators/sinks, timeout warning, and repeated start/stop calls.
  Verify a timeout does not cancel the active event or start another event.
  - [x] Five-second asynchronous join, timeout warning, idempotent start, and stop checks before/after polling and
    before dispatch are present. Existing basic lifecycle/timeout tests pass.
  - [ ] Complete active-operator/sink, between-poll-and-dispatch, and repeated lifecycle coverage.

- [ ] 6.2 [backend] Verify API lifespan uses the bounded listener wait and preserves opt-in startup (60 min); update
  `test_event_streaming_startup.py` and listener tests to cover completion within five seconds, timeout warning while
  cleanup or commit remains active, consumer closure after eventual thread exit, and responsiveness of unrelated
  asyncio tasks. Verify unfinished work remains uncommitted if the process exits while the listener is active.
  - [x] API lifespan awaits listener shutdown and explicit opt-in startup has passing coverage.
  - [ ] Active cleanup/commit, eventual closure, event-loop responsiveness, and unfinished-work scenarios remain pending.

- [ ] 6.3 [backend] Document graceful shutdown, cutover, and rollback in the Docker README (45 min); verify the
  procedure describes the five-second wait, timeout warning, continued active listener thread, and uncommitted-work risk
  if the process exits before the listener reaches its normal shutdown path.

## 7. Integration and final verification

- [ ] 7.1 [backend] Add a saved-flow/mapping-to-dispatch integration test with real service/compiler/operator wiring
  and a controlled sink (120 min); cover authoring and Elyra, create/update, sink persistence, and no event job records.
- [ ] 7.2 [backend] Add an integrated branch/merge flow test with real routing and feature propagation (90 min);
  verify empty-sibling behavior, feature transformations, multi-row output, and that a failure stops the flow.
- [ ] 7.3 [backend] Exercise the Docker event-streaming sample and multiple sequential events with configured sinks
  (120 min); record sink results, failure-and-skip behavior, commit ordering, state isolation, and resource release evidence.
- [ ] 7.4 [backend] Run relevant existing REST job-run, CLI, library, flow-engine, operator-loading, deduplication,
  and micro-batching regression suites (90 min); verify batch contracts remain intact and report unrelated failures.
  - [x] Rerun the affected Python operator executor lifecycle suite after correcting the default-cleanup regression:
    all 7 tests pass. The remaining listed batch regression suites are still pending.

- [ ] 7.5 [backend] Run `uv run ruff check --fix .`, `uv run mypy .`, and `uv build` (90 min); verify relevant Python
  lint/type/build checks pass, separating pre-existing failures and avoiding unrelated code changes.
- [ ] 7.6 [backend] Run `openspec validate add-streaming-orchestrator --strict` and inspect the final diff (45 min);
  verify acceptance evidence and S01-S08 coverage for every change, and confirm deferred backlog work was
  not implemented.
  - [x] Strict `add-streaming-orchestrator` validation passes after spec reconciliation; the affected diff has no
    whitespace errors.
  - [ ] Final S01-S08 acceptance evidence and coverage review remain pending until the open implementation and
    verification tasks are complete.
