# backend/flow-execution-engine Specification Delta

## ADDED Requirements

### Requirement: Node-level failure resumption from stored node output
When a flow executes incrementally, the engine SHALL resume a previously failed document at every node where it failed, within `max_retry_attempts`, instead of re-executing it from the root Ingest operator. The rows to resume are read from the intermediate output that the immediate predecessor of the failed node stored in the job run where the failure happened. The engine SHALL NOT persist a separate checkpoint copy of the document data.

#### Scenario: Failed document resumes at failure node from stored predecessor output
- **WHEN** a document failed at Node $K$ in a previous job run and Node $K-1$'s stored output of that job run holds the document
- **THEN** that row is read from the stored output of Node $K-1$ (located from the `job_id` and the `job_run_id` of the failure), injected into Node $K$'s input table, and earlier nodes (1 through $K-1$) are bypassed for that document

#### Scenario: Document failed at several nodes is resumed at each of them
- **WHEN** a document processed by several branches failed at Node $A$ and Node $B$
- **THEN** both failed nodes are recorded for the document, and the document is injected at Node $A$ and at Node $B$

#### Scenario: Document without usable stored output falls back to root ingestion
- **WHEN** a document failed in a previous run but the stored output of the predecessor node is unavailable, the failed node cannot be found in the flow, or the failed node has several inputs
- **THEN** the document is re-ingested from the root Ingest operator and processed through the entire pipeline

### Requirement: Resumption requires persisted node output
The engine SHALL resume failed documents only when `data_storage_type` is not `memory`, because resumption reads the persisted intermediate node output.

#### Scenario: Memory storage disables resumption
- **WHEN** `data_storage_type` is `memory`
- **THEN** failed documents are not resumed and are re-ingested from the root Ingest operator

### Requirement: Failure record content
For each failed document the engine SHALL store the source `modification_time`, and for every node at which the document failed: the node identity, the `job_run_id` of the job run in which it failed, the consecutive failure count, and the original error message. The engine SHALL NOT store the location of any intermediate data; that location is derived from the `job_id` and the `job_run_id`.

#### Scenario: Failure record identifies the failed job run and error
- **WHEN** a document fails at Node 4 in job run $R$ with error $E$
- **THEN** its record holds Node 4, `job_run_id` $R$, failure count 1 and error message $E$

#### Scenario: Repeated failure at the same node
- **WHEN** a resumed document fails again at the node where it already failed
- **THEN** the failure count is incremented, the error message is replaced by the latest error, and the `job_run_id` of the first failure at that node is kept because that run holds the stored predecessor output

### Requirement: Deferred execution accounting across pipeline nodes
Documents scheduled for resumption at downstream nodes SHALL be included in `documents_in_scope` at the Ingest operator and categorized as `deferred_execution_docs`. Each upstream node prior to the resumption target SHALL carry forward the `deferred_execution_docs` in its execution metadata without processing them. When execution reaches the target failure node, the documents SHALL be transferred from `deferred_execution_docs` into the node's active input table.

#### Scenario: Deferred docs counted in scope at Ingest and upstream nodes
- **WHEN** Ingest identifies 10 fresh documents and 2 documents deferred for resumption at Node 4
- **THEN** Ingest and intermediate nodes (Nodes 2 and 3) report `documents_in_scope: 12`, `processed_docs: 10`, and `deferred_execution_docs: [doc_11, doc_12]`

#### Scenario: Deferred docs removed from deferred list at resumption node
- **WHEN** execution reaches Node 4 where the 2 deferred documents are injected
- **THEN** Node 4 reports `documents_in_scope: 12`, `processed_docs: 12`, and `deferred_execution_docs: []`

### Requirement: Source file modification invalidates stale failure state
When a document fails, the engine SHALL record its source `modification_time`. During subsequent Ingest, if the data source reports a `modified_time` for a previously failed document that is strictly newer than its saved `modification_time`, the engine SHALL discard the failure record and ingest the modified document as fresh from the root node.

#### Scenario: Newer file version discards failure state and re-ingests fresh
- **WHEN** a failed document has saved source modification timestamp $T_1$ but the current source file reports modified timestamp $T_2 > T_1$
- **THEN** the failure record is discarded, the document is ingested as a fresh document at Node 1, and it is not categorized as deferred

#### Scenario: Unmodified file retains failure state and is deferred
- **WHEN** a failed document has current source modified timestamp equal to its saved source modification timestamp $T_1$
- **THEN** the failure record is preserved and the document is scheduled as `deferred_execution_docs`

### Requirement: Maximum retry attempts threshold
The engine SHALL track the consecutive failure count per document at each node. A document SHALL be permitted 1 initial execution plus up to `global_config.max_retry_attempts` (default: 3) retries (total `max_retry_attempts + 1` attempts). If a document's consecutive failure count at any node exceeds `max_retry_attempts` (i.e. reaches `max_retry_attempts + 1`), the engine SHALL NOT schedule it for automated resumption and SHALL classify it as non-recoverable until force-ingested.

#### Scenario: Failure count within threshold triggers resumption
- **WHEN** a document has failed 3 consecutive times at Node 4 (1 initial attempt + 2 retries) and `max_retry_attempts` is 3
- **THEN** the document is scheduled for its 3rd retry (4th total attempt) for node-level resumption

#### Scenario: Failure count exceeding threshold halts automatic retry
- **WHEN** a document has failed 4 consecutive times at Node 4 (1 initial attempt + 3 retries, exceeding `max_retry_attempts`) and `max_retry_attempts` is 3
- **THEN** the document is excluded from automatic resumption and marked non-recoverable in incremental metadata

### Requirement: Persistence and reporting of exhausted retry documents
When a document exhausts its configured maximum retry attempts, the engine SHALL persist its failure metadata to the incremental metadata store as a non-recoverable document, and report its status and failure details, including the original error message of each node that exhausted its retries, in the post-execution job run report.

#### Scenario: Exhausted retry document persisted to incremental metadata
- **WHEN** a document reaches 4 consecutive failures (`max_retry_attempts + 1` total attempts) at Node 4 and `max_retry_attempts` is 3
- **THEN** its metadata record is persisted to the incremental metadata store to prevent future automated retries

#### Scenario: Exhausted retry document reported in job run report
- **WHEN** a job run report is generated for a run where a document exhausted maximum retries
- **THEN** the report row for that document contains status `Failed` with reason stating maximum retries were exhausted along with the failure node and the original error message
