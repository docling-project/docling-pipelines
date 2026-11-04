# backend/flow-execution-engine Specification Delta

## ADDED Requirements

### Requirement: Node-level failure resumption from upstream checkpoints
When a flow executes incrementally, the engine SHALL detect documents that failed in prior runs of the same job. If an intermediate checkpoint table from the immediate upstream predecessor node exists and the failure count does not exceed `max_retry_attempts`, the engine SHALL resume the document directly at the node where it failed rather than re-executing it from the root Ingest node.

#### Scenario: Failed document resumes at failure node from upstream checkpoint
- **WHEN** a document failed at Node $K$ in a previous execution and Node $K-1$'s checkpoint table exists
- **THEN** Node $K-1$'s checkpoint row for that document is injected directly into Node $K$'s input table and earlier nodes (1 through $K-1$) are bypassed for that document

#### Scenario: Document without valid upstream checkpoint falls back to root ingestion
- **WHEN** a document failed in a previous run but no upstream checkpoint table is available
- **THEN** the document is re-ingested from the root Ingest operator and processed through the entire pipeline

### Requirement: Deferred execution accounting across pipeline nodes
Documents scheduled for resumption at downstream nodes SHALL be included in `documents_in_scope` at the Ingest operator and categorized as `deferred_execution_docs`. Each upstream node prior to the resumption target SHALL carry forward the `deferred_execution_docs` in its execution metadata without processing them. When execution reaches the target failure node, the documents SHALL be transferred from `deferred_execution_docs` into the node's active input table.

#### Scenario: Deferred docs counted in scope at Ingest and upstream nodes
- **WHEN** Ingest identifies 10 fresh documents and 2 documents deferred for resumption at Node 4
- **THEN** Ingest and intermediate nodes (Nodes 2 and 3) report `documents_in_scope: 12`, `processed_docs: 10`, and `deferred_execution_docs: [doc_11, doc_12]`

#### Scenario: Deferred docs removed from deferred list at resumption node
- **WHEN** execution reaches Node 4 where the 2 deferred documents are injected
- **THEN** Node 4 reports `documents_in_scope: 12`, `processed_docs: 12`, and `deferred_execution_docs: []`

### Requirement: Source file modification invalidates stale checkpoints
During Ingest, if the data source reports a `modified_time` for a previously failed document that is strictly newer than its saved checkpoint timestamp, the engine SHALL invalidate the checkpoint and ingest the modified document as fresh from the root node.

#### Scenario: Newer file version invalidates checkpoint and re-ingests fresh
- **WHEN** a failed document has a checkpoint timestamp $T_1$ but the source file has modified timestamp $T_2 > T_1$
- **THEN** the checkpoint is discarded, the document is ingested as a fresh document at Node 1, and it is not categorized as deferred

#### Scenario: Unmodified file retains checkpoint and is deferred
- **WHEN** a failed document has source modified timestamp equal to or older than the checkpoint timestamp
- **THEN** the checkpoint is preserved and the document is scheduled as `deferred_execution_docs`

### Requirement: Maximum retry attempts threshold
The engine SHALL track the consecutive failure count per document at each node. If a document's failure count exceeds `global_config.max_retry_attempts` (default: 3), the engine SHALL NOT schedule it for automated resumption and SHALL classify it as non-recoverable until force-ingested.

#### Scenario: Failure count within threshold triggers resumption
- **WHEN** a document has failed 2 consecutive times at Node 4 and `max_retry_attempts` is 3
- **THEN** the document is scheduled for node-level resumption on the 3rd run

#### Scenario: Failure count exceeding threshold halts automatic retry
- **WHEN** a document has failed 3 consecutive times at Node 4 and `max_retry_attempts` is 3
- **THEN** the document is excluded from automatic resumption and marked non-recoverable in incremental metadata
