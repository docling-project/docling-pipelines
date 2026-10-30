# Spec Delta

## Purpose

Define incremental document processing, bounded per-run selection, and forced reprocessing, including tracking
source deletions and synchronizing their removal from vector database outputs with retry-safe metadata updates.

## ADDED Requirements

### Requirement: Retention controls discovery independently of processing selection

With `retain_deleted_docs: false`, ingestion SHALL complete source metadata discovery while selecting at most
`max_files` eligible documents. With retention enabled or omitted, ingestion SHALL retain its existing limited
discovery behavior and SHALL NOT perform source-deletion cleanup. Discovery beyond the processing limit MUST NOT
fetch document contents solely for deletion detection.

#### Scenario: Full discovery with limited processing
- **WHEN** the source contains ten million documents, `max_files` is one million, and retention is disabled
- **THEN** ingestion discovers the complete source inventory but emits at most one million documents for processing
- **AND** documents outside the selected group are not treated as missing

#### Scenario: Successive incremental runs
- **WHEN** retention is disabled, forced ingestion is disabled, and previously selected documents completed processing
- **THEN** the next run skips unchanged completed documents and selects the next eligible group up to `max_files`

#### Scenario: Retention enabled
- **WHEN** retention is enabled and the processing selection limit is reached
- **THEN** deletion synchronization does not require further discovery or VectorDB deletion
- **AND** existing adapter behavior for limited discovery is preserved

### Requirement: Forced ingestion preserves source-deletion evidence

With retention disabled, `force_ingest: true` SHALL bypass incremental selection checks while preserving historical
records and pending deletions required for synchronization. The processing selection SHALL remain limited by
`max_files`; forced ingestion SHALL NOT suppress detection of missing documents.

#### Scenario: Forced processing and source deletion
- **WHEN** tracked documents A and B exist in history, only A remains in the source, and forced ingestion is enabled
- **THEN** A is eligible for reprocessing and B is marked for VectorDB deletion after complete successful discovery

#### Scenario: Forced processing with a selection limit
- **WHEN** forced ingestion is enabled and the source contains more than `max_files` documents
- **THEN** no more than `max_files` documents are selected and unselected historical records remain available

### Requirement: Missing status requires authoritative source discovery

Only a successful complete inventory of the configured source scope SHALL establish that a tracked document is
missing. Failed, cancelled, capped, unsupported, or event-scoped discovery MUST NOT establish absence. An unchanged,
unselected, or processing-filtered document known to exist MUST NOT be marked deleted merely because it emits no row.

#### Scenario: Partial listing failure
- **WHEN** discovery fails after returning part of the source inventory
- **THEN** the flow fails before deletion reconciliation or downstream processing
- **AND** unseen tracked documents are not newly marked deleted

#### Scenario: Accessible empty source
- **WHEN** discovery successfully completes for an accessible empty source
- **THEN** all tracked documents belonging to that source scope are eligible for deletion

#### Scenario: Missing root or inaccessible subtree
- **WHEN** a configured root cannot be accessed or a subtree cannot be enumerated reliably
- **THEN** the condition is not treated as a successfully enumerated empty source

#### Scenario: Processing filters hide an existing document
- **WHEN** a tracked document still exists but a processing filter excludes it
- **THEN** its exclusion alone does not mark it deleted

#### Scenario: Single-file event execution
- **WHEN** ingestion is bound to one file event within a larger tracked source
- **THEN** unrelated tracked documents are not marked deleted from that event inventory

### Requirement: Ingestion preserves table and accounting contracts

Ingestion SHALL return `tuple[list[pa.Table], dict]` with selected rows in the existing discovery schema and a typed
empty table when none are selected. Processing metrics SHALL describe selected processing outcomes; discovery and
deletion metrics SHALL distinguish incomplete discovery, newly missing documents, and actual output cleanup.

#### Scenario: Discovery-only documents do not inflate processing counts
- **WHEN** ingestion discovers one hundred source entries and selects ten
- **THEN** the output contains at most ten rows with `id`, `name`, `document_format`, `metadata`, `source_id`, `path`,
  and `modified_time` columns
- **AND** the other ninety entries do not count as processed documents

### Requirement: Vector cleanup resolves source IDs to every stored chunk

When retention is disabled, each configured VectorDB destination SHALL remove all stored chunks belonging to pending
missing source documents, using the same source identity as incremental tracking. Cleanup SHALL support OpenSearch
and Milvus and SHALL distinguish successful absence from failed chunk lookup or failed deletion.

#### Scenario: Chunked document removed
- **WHEN** one pending missing document owns several stored chunks
- **THEN** all its chunk primary keys are removed without removing chunks belonging to other documents

#### Scenario: Chunk lookup fails
- **WHEN** chunk lookup fails for a pending document
- **THEN** cleanup reports failure rather than acknowledging the document as already absent

#### Scenario: Already absent chunks
- **WHEN** a successful complete lookup finds no remaining chunks for a pending document
- **THEN** that destination can acknowledge cleanup idempotently

### Requirement: Pending deletions survive failures and reappearance

Pending deletion evidence SHALL remain durable until all configured VectorDB destinations acknowledge cleanup for
the affected document. A failed or unexecuted destination MUST NOT lose its retry evidence. A source document that
reappears SHALL cease being a deletion candidate before cleanup and SHALL be eligible for reprocessing if its stored
output may already have been removed.

#### Scenario: One destination fails
- **WHEN** cleanup succeeds in one VectorDB destination and fails in another
- **THEN** deletion evidence remains available for retry and the failed cleanup is visible in run results

#### Scenario: No VectorDB destination executes
- **WHEN** a run marks a document missing but no configured VectorDB destination completes cleanup
- **THEN** its pending record is not purged merely because another run begins

#### Scenario: Pending document reappears outside selection
- **WHEN** a pending document reappears but is beyond the current `max_files` selection
- **THEN** it is not deleted on the strength of the old pending record
- **AND** later incremental selection can reprocess it if prior cleanup may have removed its output

#### Scenario: Reappeared document disappears before regeneration
- **WHEN** a pending document reappears outside `max_files` and disappears again before successful reprocessing
- **THEN** its tracking identity remains available and the next complete scan marks it pending deletion again
- **AND** reappearance cancels deletion without falsely retaining a completed-processing timestamp

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

### Requirement: Synchronization history is read in bounded batches

Full-source synchronization SHALL avoid materializing the complete tracking history as Python dictionaries and
candidate sets. Filesystem and PostgreSQL stores SHALL stream tracking records into temporary indexed storage.
Temporary presence evidence MUST NOT alter durable tracking before successful discovery and MUST be removed on
success, failure, and cancellation. Selected rows and actual missing/returned evidence may scale with their counts.

#### Scenario: Large processing history and small selection
- **WHEN** a synchronization run has millions of tracked records and a small `max_files` limit
- **THEN** history is streamed in bounded batches and incremental eligibility remains correct
- **AND** unsuccessful discovery leaves persistent tracking unchanged and removes temporary history
