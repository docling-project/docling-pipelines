# backend/flow-execution-engine Specification Delta

## ADDED Requirements

### Requirement: Node-level failure resumption from upstream checkpoints
When a flow executes incrementally, the engine SHALL detect documents that failed in prior runs of the same job. If an intermediate checkpoint table from the immediate upstream predecessor node exists and the document has not exceeded `max_retry_attempts` retries (i.e. consecutive failure count $\le$ `max_retry_attempts`), the engine SHALL resume the document directly at the node where it failed rather than re-executing it from the root Ingest node.

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
When a document fails, the engine SHALL record its source `modification_time`. During subsequent Ingest, if the data source reports a `modified_time` for a previously failed document that is strictly newer than its saved `modification_time`, the engine SHALL invalidate the checkpoint and ingest the modified document as fresh from the root node.

#### Scenario: Newer file version invalidates checkpoint and re-ingests fresh
- **WHEN** a failed document has saved source modification timestamp $T_1$ but the current source file reports modified timestamp $T_2 > T_1$
- **THEN** the checkpoint is discarded, the document is ingested as a fresh document at Node 1, and it is not categorized as deferred

#### Scenario: Unmodified file retains checkpoint and is deferred
- **WHEN** a failed document has current source modified timestamp equal to its saved source modification timestamp $T_1$
- **THEN** the checkpoint is preserved and the document is scheduled as `deferred_execution_docs`

### Requirement: Maximum retry attempts threshold
The engine SHALL track the consecutive failure count per document at each node. A document SHALL be permitted 1 initial execution plus up to `global_config.max_retry_attempts` (default: 3) retries (total `max_retry_attempts + 1` attempts). If a document's consecutive failure count exceeds `max_retry_attempts` (i.e. reaches `max_retry_attempts + 1`), the engine SHALL NOT schedule it for automated resumption and SHALL classify it as non-recoverable until force-ingested.

#### Scenario: Failure count within threshold triggers resumption
- **WHEN** a document has failed 3 consecutive times at Node 4 (1 initial attempt + 2 retries) and `max_retry_attempts` is 3
- **THEN** the document is scheduled for its 3rd retry (4th total attempt) for node-level resumption

#### Scenario: Failure count exceeding threshold halts automatic retry
- **WHEN** a document has failed 4 consecutive times at Node 4 (1 initial attempt + 3 retries, exceeding `max_retry_attempts`) and `max_retry_attempts` is 3
- **THEN** the document is excluded from automatic resumption and marked non-recoverable in incremental metadata

### Requirement: Persistence and reporting of exhausted retry documents
When a document exhausts its configured maximum retry attempts, the engine SHALL persist its failure metadata to the incremental metadata store as a non-recoverable document, retain its intermediate checkpoints, and report its status and failure details in the post-execution job run report.

#### Scenario: Exhausted retry document persisted to incremental metadata
- **WHEN** a document reaches 4 consecutive failures (`max_retry_attempts + 1` total attempts) at Node 4 and `max_retry_attempts` is 3
- **THEN** its metadata record is persisted to the incremental metadata store to prevent future automated retries while its checkpoint is retained

#### Scenario: Exhausted retry document reported in job run report
- **WHEN** a job run report is generated for a run where a document exhausted maximum retries
- **THEN** the report row for that document contains status `Failed` with reason stating maximum retries were exhausted along with the failure node and error detail
