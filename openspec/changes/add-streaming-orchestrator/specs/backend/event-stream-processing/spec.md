# Spec Delta

## Purpose

Route validated Kafka file events to synchronous in-process flow execution, with sequential processing,
bounded retries, terminal diagnostics, explicit offset commits, and cooperative shutdown.

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

Each listener SHALL finish an event's execution, allowed retries, terminal reporting, and commit attempt before
polling for the next event. Operators and retries SHALL run synchronously on the listener's processing thread.
The application SHALL NOT accumulate a work queue or start concurrent event workers.

#### Scenario: Several messages are available
- **WHEN** event A is executing or retrying while events B and C are available in Kafka
- **THEN** B and C are not polled for application processing until A reaches a terminal outcome and its commit
  is attempted

### Requirement: Configurable bounded immediate retries

Valid events whose routing, flow preparation, or operator execution fails SHALL retry immediately up to a configured
nonnegative maximum retry count. A maximum of R retries SHALL allow at most R + 1 attempts. Each retry SHALL restart
dispatch and the complete flow with fresh attempt state; no offset commit SHALL occur between attempts.

#### Scenario: Retry succeeds
- **WHEN** an event's first attempt fails and a permitted retry succeeds
- **THEN** the listener stops retrying, reports success, and attempts one offset commit after completion

#### Scenario: Retry budget is exhausted
- **WHEN** all R + 1 attempts fail, including a missing mapping or deleted flow
- **THEN** the listener reports terminal failure, attempts the event's offset commit, and continues to the next event

#### Scenario: Zero retries
- **WHEN** the maximum retry count is zero
- **THEN** the listener makes exactly one processing attempt before reporting the terminal outcome

#### Scenario: Mapping changes before retry
- **WHEN** a failed event's routing mapping changes before its next allowed attempt
- **THEN** that attempt resolves the current mapping and prepares the currently selected saved flow

### Requirement: Invalid events are reported and skipped

Messages that fail deserialization, schema validation, or event validation SHALL be reported and skipped without
flow execution or processing retries. The listener SHALL attempt their offset commits and continue processing
subsequent messages. Kafka error messages without a usable event record SHALL be reported without a record commit.

#### Scenario: Invalid event precedes a valid event
- **WHEN** a malformed event is followed by a valid event
- **THEN** the malformed event is logged with available Kafka context and its commit is attempted before the valid
  event runs

#### Scenario: Unsupported operation
- **WHEN** a record specifies an operation other than create or update
- **THEN** it is rejected as invalid and no flow is invoked

### Requirement: Commit only terminal records

Automatic commits and automatic offset storage SHALL remain disabled. The listener SHALL attempt a synchronous
message-specific offset commit after success, retry exhaustion, or invalid-event rejection. An unfinished attempt
or an event with a pending retry SHALL remain uncommitted, including during shutdown.

#### Scenario: Slow sink is still processing
- **WHEN** a sink has not finished persisting the event's output
- **THEN** the event's offset is not committed

#### Scenario: Attempt has failed with a retry pending
- **WHEN** an attempt fails and another retry is still allowed
- **THEN** the listener does not commit the event before that retry reaches its outcome

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

The listener SHALL log completion or exhausted failure with event ID, routing key, operation, selected flow when
known, and attempt count. Failures SHALL identify their stage, reason, and operator when known. Kafka diagnostics
SHALL include topic, partition, and offset. Failure notification SHALL be an in-process outcome, not a Kafka publication
or durable job record; credentials and document content SHALL NOT be logged.

#### Scenario: Operator retries are exhausted
- **WHEN** an operator fails on the final permitted attempt
- **THEN** terminal diagnostics identify the event, flow, operator, attempts, and failure before the commit is attempted

#### Scenario: Mapping lookup fails
- **WHEN** routing fails before a flow or operator is known
- **THEN** failure diagnostics include the event and routing stage without inventing a flow or operator identifier

#### Scenario: Source filters skip a document
- **WHEN** ingestion intentionally excludes the referenced document and reports no failed document
- **THEN** runtime diagnostics identify the event, selected flow, skip, and available reason before dispatch completes
- **AND** the listener treats the no-op as completed and attempts its offset commit without processing retries

### Requirement: Retry configuration

Event streaming SHALL expose an environment setting for the maximum retry count. Invalid or negative retry counts
SHALL fail listener configuration before consumption starts.

#### Scenario: Retry count is configured
- **WHEN** the listener starts with a valid explicit maximum retry count
- **THEN** the listener applies that retry limit and reports the active setting at startup

#### Scenario: Retry configuration is invalid
- **WHEN** the configured retry count is negative or nonnumeric
- **THEN** listener configuration fails before a consumer begins polling

### Requirement: Cooperative draining shutdown

A stop request SHALL prevent new events from starting and drain the active event through its permitted retries,
cleanup, terminal reporting, and offset-commit attempt before closing the consumer. Shutdown SHALL NOT cancel or
abandon running operators, count a stop request as retry exhaustion, or commit unfinished work.

#### Scenario: Stop arrives during operator or sink processing
- **WHEN** shutdown is requested while an operator or sink is executing
- **THEN** `stop()` remains pending without interrupting that execution, waits for the event's terminal outcome and
  commit attempt, and returns only after consumer closure and thread exit, without polling another event

#### Scenario: Stop arrives with retries remaining
- **WHEN** shutdown is requested for an active event whose failed attempt has a retry remaining
- **THEN** the listener completes the permitted retry sequence until success or exhaustion, performs cleanup and
  terminal reporting, attempts the offset commit, and only then closes the consumer and exits

#### Scenario: Shutdown awaits cleanup and the commit attempt
- **WHEN** shutdown is requested and the active event's cleanup or offset-commit attempt is still in progress
- **THEN** `stop()` remains pending and the consumer remains open until cleanup, terminal reporting, and the commit
  attempt finish, including when the commit attempt reports a failure

#### Scenario: Stop arrives after poll but before execution
- **WHEN** the stop flag is set after a record is polled but before its event begins execution
- **THEN** the listener leaves that record unprocessed and uncommitted, closes the consumer, and exits its processing
  thread before `stop()` returns

### Requirement: Awaitable shutdown completion

`stop()` SHALL be awaitable and return only after the listener's processing thread exits, with the consumer closed.
Waiting SHALL keep the asyncio event loop responsive to unrelated asynchronous tasks. Shutdown SHALL NOT impose a
drain timeout; an operator that never returns can keep `stop()` pending indefinitely.

#### Scenario: Waiting for shutdown keeps the event loop responsive
- **WHEN** the shutdown caller awaits `stop()` while the listener thread is processing an active event
- **THEN** `stop()` remains pending and unrelated asynchronous tasks can run on the asyncio event loop

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
