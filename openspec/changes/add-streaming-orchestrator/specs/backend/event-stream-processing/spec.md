# Spec Delta

## Purpose

Route validated Kafka file events to synchronous in-process flow execution, with single-pass processing,
terminal diagnostics, explicit offset commits, and cooperative shutdown.

## ADDED Requirements

### Requirement: Existing event contract and direct routing

The listener SHALL retain the existing five-field create/update file-event contract and schema validation.
Dispatch SHALL resolve routing keys case-insensitively through saved mappings and invoke the mapped flow in process.
Event execution SHALL NOT require an API base URL, submit an HTTP job run, or interpret a job-run response.

#### Scenario: Case-insensitive mapping dispatches directly
- **WHEN** a valid event selects an existing mapping using a different letter case
- **THEN** its mapped saved flow executes in process without an HTTP submission

#### Scenario: API URL is absent
- **WHEN** event streaming is enabled with valid Kafka, mapping, flow, and sink configuration but no API base URL
- **THEN** file events execute successfully without an API URL dependency

### Requirement: One active event per listener

Each listener SHALL finish an event's single synchronous dispatch, terminal reporting, and commit attempt before
polling for the next event. Operators SHALL run synchronously on the listener's processing thread. The application
SHALL NOT accumulate a work queue or start concurrent event workers.

#### Scenario: Several messages are available
- **WHEN** event A is executing while events B and C are available in Kafka
- **THEN** B and C are not polled for application processing until A reaches a terminal outcome and its commit
  is attempted

### Requirement: Single dispatch and skip on processing failure

The listener SHALL dispatch each valid event once. If routing, flow preparation, or operator execution fails, it SHALL
report the failure, attempt one synchronous message-specific offset commit, and continue to the next event without
rerunning the flow. Automatic processing retries and retry configuration SHALL remain excluded.

#### Scenario: Flow dispatch fails
- **WHEN** a valid event fails during routing, flow preparation, or operator execution
- **THEN** the listener reports the failure, attempts one offset commit, and polls the next event without rerunning the flow

### Requirement: Invalid events are reported and skipped

Messages that fail deserialization, schema validation, or event validation SHALL be reported and skipped without
flow execution. The listener SHALL attempt their offset commits and continue processing subsequent messages. Kafka
error messages without a usable event record SHALL be reported without a record commit.

#### Scenario: Invalid event precedes a valid event
- **WHEN** a malformed event is followed by a valid event
- **THEN** the malformed event is logged with available Kafka context and its commit is attempted before the valid
  event runs

#### Scenario: Unsupported operation
- **WHEN** a record specifies an operation other than create or update
- **THEN** it is rejected as invalid and no flow is invoked

### Requirement: Commit only terminal records

Automatic commits and automatic offset storage SHALL remain disabled. The listener SHALL attempt a synchronous
message-specific offset commit after success, processing failure, or invalid-event rejection. It SHALL NOT rerun a
failed flow before that commit attempt. An unfinished event execution SHALL remain uncommitted, including during
shutdown.

#### Scenario: Slow sink is still processing
- **WHEN** a sink has not finished persisting the event's output
- **THEN** the event's offset is not committed

#### Scenario: Dispatch failure is acknowledged before the next poll
- **WHEN** a valid event's dispatch fails
- **THEN** the listener attempts its message-specific commit before polling the next event, without rerunning dispatch

### Requirement: Commit failures remain visible and separate from processing

Commit exceptions and partition-level commit errors SHALL be logged with event and Kafka record context. A commit
failure SHALL NOT be reported as a processing success or trigger an immediate pipeline rerun for that record.
The listener SHALL continue consuming; replay after restart or reassignment SHALL be documented as possible.

#### Scenario: Commit fails after sink success
- **WHEN** pipeline processing succeeds but its offset commit fails
- **THEN** processing completion and commit failure are reported separately and the pipeline is not immediately rerun

#### Scenario: Commit response contains a partition error
- **WHEN** the commit operation returns an error for the record's partition
- **THEN** the listener logs the failed partition and attempted offset before continuing

### Requirement: Terminal diagnostics and failure notification

The listener SHALL log completion or failure with the event ID when known. Flow ID correlation is not required.
Failures SHALL identify the operator and the reason for raised errors when known. Kafka diagnostics SHALL include
topic, partition, and offset. Failure notification SHALL be an in-process outcome. It SHALL NOT publish a Kafka
message or create a durable job record. Credentials and document content SHALL NOT be logged.

#### Scenario: Operator fails
- **WHEN** an operator fails during the event's single dispatch
- **THEN** terminal diagnostics identify the event, operator, and failure before the commit is attempted

#### Scenario: Operator reports failed documents in metadata
- **WHEN** an operator returns failed-document metadata
- **THEN** terminal diagnostics report the operator failure without copying failed-document reason text

#### Scenario: Mapping lookup fails
- **WHEN** routing fails before a flow or operator is known
- **THEN** failure diagnostics include the event and routing failure reason without inventing a flow or operator identifier

#### Scenario: Source filters skip a document
- **WHEN** ingestion intentionally excludes the referenced document and reports no failed document
- **THEN** skip reasons and logging remain the ingest operator's responsibility
- **AND** the listener treats the no-op as completed and attempts its offset commit without rerunning dispatch

### Requirement: Cooperative draining shutdown

A stop request SHALL prevent new events from starting and allow the active event's single dispatch, cleanup, terminal
reporting, and offset-commit attempt to finish before the listener closes the consumer. Shutdown SHALL NOT cancel
running operators or commit unfinished work.

#### Scenario: Stop arrives during operator or sink processing
- **WHEN** shutdown is requested while an operator or sink is executing
- **THEN** `stop()` waits without interrupting that execution for up to five seconds
- **AND** if the event and consumer shutdown finish within that period, it returns after the listener thread exits
- **AND** otherwise it logs a shutdown-timeout warning and returns while the listener thread continues

#### Scenario: Stop arrives during a failed event
- **WHEN** shutdown is requested while the active event's dispatch is failing
- **THEN** the listener reports the failure, attempts its offset commit once, and closes the consumer without rerunning
  the flow, even if `stop()` already returned after its five-second wait

#### Scenario: Shutdown awaits cleanup and the commit attempt
- **WHEN** shutdown is requested and the active event's cleanup or offset-commit attempt is still in progress
- **THEN** `stop()` waits for up to five seconds without blocking the asyncio event loop
- **AND** if cleanup, terminal reporting, commit attempt, and consumer closure exceed that period, `stop()` logs a
  timeout warning and returns while the listener thread continues

#### Scenario: Stop arrives after poll but before execution
- **WHEN** the stop flag is set after a record is polled but before its event begins execution
- **THEN** the listener leaves that record unprocessed and uncommitted and exits through its consumer-close path
- **AND** `stop()` follows the five-second wait and timeout behavior even if consumer closure is still in progress

### Requirement: Timed awaitable shutdown

`stop()` SHALL await the listener thread's exit for up to five seconds without blocking the asyncio event loop. If the
thread remains alive after five seconds, `stop()` SHALL log a timeout warning and return without cancelling the thread.
The listener thread SHALL keep the consumer open until active processing reaches a terminal outcome and its cleanup,
reporting, and commit attempt finish. If the process terminates first, unfinished work can remain uncommitted.

#### Scenario: Waiting for shutdown keeps the event loop responsive
- **WHEN** the shutdown caller awaits `stop()` while the listener thread is processing an active event
- **THEN** unrelated asynchronous tasks can run while `stop()` waits, and the wait ends when the thread exits or five
  seconds elapse

#### Scenario: Listener remains active after the shutdown wait expires
- **WHEN** the listener thread has not exited five seconds after shutdown is requested
- **THEN** `stop()` logs a timeout warning and returns without cancelling the active event or closing its consumer
- **AND** the listener thread continues until it reaches its normal terminal cleanup and consumer-close path

### Requirement: Existing application and batch execution compatibility

Event streaming SHALL remain opt-in through its existing enable setting and optional dependency extra. Flow and
mapping APIs SHALL retain their contracts. Explicit REST, CLI, and library runs SHALL retain job tracking, validation,
orchestrator selection, and micro-batching behavior independently of the streaming execution path.

#### Scenario: Event streaming is disabled
- **WHEN** the application starts without event streaming enabled
- **THEN** no event consumer starts and Kafka settings and dependencies are not required

#### Scenario: Batch and streaming use the same saved flow
- **WHEN** a flow runs once through streaming and once through an explicit REST, CLI, or library invocation
- **THEN** only the explicit batch execution creates its normal run records and applies its existing batch settings
