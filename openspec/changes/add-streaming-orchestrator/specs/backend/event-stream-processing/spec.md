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

A stop request SHALL prevent the listener from starting another event and allow an active event to reach a terminal
outcome, including its allowed retries and cleanup, before committing and closing the consumer. Shutdown SHALL NOT
commit unfinished work or declare the listener stopped while its processing thread is still running.

#### Scenario: Stop arrives during sink processing
- **WHEN** shutdown is requested while a sink is executing
- **THEN** shutdown waits for the event's terminal outcome and commit attempt, closes the consumer, and polls no
  next event

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
