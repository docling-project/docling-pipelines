# Spec Delta

## ADDED Requirements

### Requirement: Source-deletion cleanup runs independently of selected document batches

With retention disabled and successful complete discovery, the engine SHALL schedule source-deletion cleanup for
each configured VectorDB destination even when ingestion selects zero documents. Concurrent micro-batches SHALL
share one cleanup phase per destination per run; retries SHALL be idempotent. Normal DAG cancellation and failure
policies SHALL remain effective.

#### Scenario: Deletion-only execution
- **WHEN** no new or changed documents are selected and a tracked source document is missing
- **THEN** VectorDB cleanup executes without running unnecessary extraction or embedding work
- **AND** the run does not return early before cleanup

#### Scenario: Concurrent micro-batches
- **WHEN** several document-processing batches execute concurrently with pending deletions
- **THEN** they do not independently consume or acknowledge the same deletion backlog
- **AND** every configured VectorDB destination receives the cleanup work

#### Scenario: Cancellation before cleanup
- **WHEN** the run is cancelled before a destination completes cleanup
- **THEN** cleanup is not falsely acknowledged and pending evidence remains for a later eligible run

#### Scenario: Cleanup failure is visible
- **WHEN** a destination cannot look up or remove pending chunks
- **THEN** its cleanup is reported as failed through existing run reporting
- **AND** the run does not report completely successful synchronization

### Requirement: Incremental tracking uses one execution scope

The engine SHALL use the same resolved tracking scope for reading processing history, reconciling source absence,
loading pending deletions, acknowledging cleanup, and saving successful processing metadata. An explicit
`context_id` SHALL take precedence over the job identifier. Missing authoritative inventory MUST NOT be interpreted
as a successfully scanned empty source.

#### Scenario: Explicit context differs from job ID
- **WHEN** a run specifies a tracking context different from its job ID
- **THEN** ingestion, deletion cleanup, and successful processing update that same context
- **AND** records in other contexts remain unchanged

#### Scenario: Ingestion does not provide reconciliation evidence
- **WHEN** an ingestion result lacks proof of a complete source inventory
- **THEN** the engine does not mark historical documents deleted using a default empty list
