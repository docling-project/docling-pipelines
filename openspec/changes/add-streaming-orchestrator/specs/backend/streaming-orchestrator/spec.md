# Spec Delta

## Purpose

Execute one event-referenced document through a saved flow's existing operators synchronously, preserving configured
chunk/embedding spill behavior and isolated attempt state without creating a tracked job run.

## ADDED Requirements

### Requirement: Saved flow formats and freshness

Streaming execution SHALL load the selected saved flow for each event and support its authoring and Elyra formats.
It SHALL prepare an isolated runtime definition without modifying the saved flow. Unsupported formats and missing
flows SHALL fail explicitly before document processing.

#### Scenario: Authoring and Elyra flows execute
- **WHEN** events select equivalent saved authoring and Elyra flows
- **THEN** both flows process their referenced documents using the configured operators and sinks

#### Scenario: Saved definition changes between events
- **WHEN** a flow is updated after an event completes and before the next event selects it
- **THEN** the next event uses the updated definition without requiring a listener restart

#### Scenario: Flow cannot be prepared
- **WHEN** the selected flow is absent or its format is unsupported
- **THEN** processing fails before an operator runs and the listener reports the event and preparation failure

### Requirement: Runtime integrity without full per-event validation

Before document processing, streaming preparation SHALL convert the saved format and check a nonempty DAG, valid node
IDs and operator names, unique IDs, consistent/resolvable edges, acyclicity, one ingest root, root reachability, and
operator-class resolution through configured discovery. These checks SHALL run independently of full flow/operator
validation and SHALL NOT be bypassed by `disable_validation`.

#### Scenario: Invalid executable graph
- **WHEN** a saved graph is empty or contains an invalid node ID/operator name, duplicate node identity, inconsistent
  or unresolved edge, cycle, disconnected node, multiple roots, or a non-ingest root
- **THEN** preparation fails before document processing rather than executing a partial graph

#### Scenario: Required operator is unavailable
- **WHEN** a flow references an operator unavailable through configured operator discovery
- **THEN** the attempt reports that operator as unavailable before document processing

#### Scenario: Per-event validation is avoided
- **WHEN** a valid saved flow processes several events
- **THEN** each attempt performs saved-format conversion, graph-integrity checks, operator-class resolution, and
  feature propagation without invoking full flow or operator validation

#### Scenario: Saved validation setting does not disable integrity checks
- **WHEN** a saved flow sets `disable_validation=true` and contains a cycle or unresolved edge
- **THEN** preparation fails before document processing

### Requirement: Feature-propagation preparation

Each attempt SHALL compute per-node feature metadata using the existing PythonOrchestrator-based setup without
running full flow/operator validation. Propagation results SHALL NOT be reused across events.

#### Scenario: Preparation avoids full validation
- **WHEN** streaming prepares a valid saved flow
- **THEN** it computes the downstream feature views and global parameters without processing document tables
  during preparation

#### Scenario: Later event recomputes feature metadata after failure
- **WHEN** an event fails and the saved flow changes its output features before a later event selects it
- **THEN** the later event uses fresh propagation state and computes feature views from the updated definition without
  reusing the failed event's cached results

### Requirement: One document bound through the configured provider

Each event SHALL bind its existing file reference to the ingest provider's single-file binding contract and force
reprocessing for both create and update operations. Source credentials, include/exclude filters, and provider-native
reference meanings SHALL be preserved. The event SHALL NOT expand processing to other configured source documents.
Skip decisions, reasons, and logging SHALL remain operator-owned.

#### Scenario: Create and update bypass incremental exclusion
- **WHEN** create and update events reference a document that was processed previously
- **THEN** each attempt ingests that document again using the configured provider and credentials

#### Scenario: Source filters exclude the document
- **WHEN** the referenced document is excluded by the saved flow's source filters
- **THEN** the ingest operator handles the skip and its reason using its existing metadata and logging
- **AND** downstream routes receive no rows and the attempt completes as a no-op without a failure or sink writes

#### Scenario: Provider cannot bind the reference
- **WHEN** the configured provider rejects or does not support the file-reference binding
- **THEN** the attempt fails explicitly instead of processing the provider's original collection of files

### Requirement: Existing operator discovery and configuration

Streaming execution SHALL support built-in operators and preserve existing flow-level and
node-level configuration precedence. Event binding and streaming execution constraints SHALL take precedence over
saved values that would select another input document or enable batch processing.

#### Scenario: Built-in operator in saved flow
- **WHEN** a saved flow references a built-in operator with node-level configuration
- **THEN** the operator processes the event using its node-level configuration

#### Scenario: Saved batch settings are present
- **WHEN** a saved flow enables micro-batching
- **THEN** the streaming attempt still executes synchronously without starting batch processing

### Requirement: Arrow table and metadata contract

Operator inputs and outputs SHALL retain the existing Arrow table schemas required and produced by the configured
operators. Each transform SHALL yield a list of Arrow tables and a metadata dictionary. Processing SHALL preserve
required document identifiers, branch metadata, and document outcome metadata; malformed results SHALL fail explicitly.

#### Scenario: Chunking preserves one document row
- **WHEN** the chunker successfully splits one document into several chunks
- **THEN** downstream operators receive one document row with its chunks stored as a list in `chunked_content`
- **AND** the document ID and other retained columns keep their configured types, subject to `retain_original_content`
  and configured output feature drops and renames

#### Scenario: Malformed transform result
- **WHEN** an operator returns a non-table output or invalid metadata instead of the transform contract
- **THEN** the attempt fails with operator context before passing that result downstream

### Requirement: Feature metadata and output transformations

Streaming execution SHALL supply the feature metadata required by downstream operators and sinks, including merge
column disambiguation and embedding metadata. Configured output feature drops and renames SHALL apply to all
relevant output tables before downstream processing. Rename-aware updates to propagated feature metadata are
outside this change's scope; existing output-feature drop propagation is retained.

#### Scenario: Sink receives required feature metadata
- **WHEN** extraction, chunking, and embeddings precede a configured vector sink
- **THEN** the sink receives the table columns and feature metadata required to persist the configured fields
  and vectors

#### Scenario: Output features are dropped
- **WHEN** a node drops configured output features
- **THEN** every relevant output table and downstream feature view reflect those drops

#### Scenario: Output features are renamed
- **WHEN** a node renames configured output features
- **THEN** every relevant output table reflects those renames

### Requirement: Sequential dependency order

Operators SHALL execute sequentially after their required upstream routes have resolved. Input node ordering in a saved
definition SHALL NOT cause a dependent operator to execute before its dependencies. An operator failure SHALL stop all
remaining execution in that attempt.

#### Scenario: Nodes stored out of order
- **WHEN** a valid saved graph lists a sink before its upstream transforms
- **THEN** the upstream transforms execute first and the sink runs only after its inputs resolve

#### Scenario: Failure stops the attempt
- **WHEN** an operator fails while other graph nodes remain pending
- **THEN** none of those pending nodes execute in that attempt

### Requirement: Branch and merge route identities

Branch output selection SHALL use the declared route identity and corresponding output metadata. Multi-input merges
SHALL receive resolved inputs under their declared link names. Unknown routes and invalid output indices SHALL fail
explicitly rather than substitute an unrelated table.

#### Scenario: Distinct branch outputs merge
- **WHEN** two branches produce different output tables and feed a merge
- **THEN** each branch consumes its selected table and the merge receives inputs under the saved link identities

#### Scenario: Elyra branch identity follows batch execution
- **WHEN** an Elyra runtime flow stores branch identity as `link_id` on the downstream node
- **THEN** streaming uses that identity to select the branch output, as batch execution does
- **AND** no additional field is required on the runtime output edge

#### Scenario: Branch output metadata is inconsistent
- **WHEN** a requested route has no valid result index or refers outside the operator's output tables
- **THEN** the attempt fails with the branch operator and route context

### Requirement: Empty routes resolve independently

An empty route SHALL skip downstream work that has no populated input without preventing populated sibling routes
from completing. A merge with populated inputs SHALL retain its existing empty-input behavior. An entirely empty
flow with no reported failure SHALL complete as a no-op.

#### Scenario: Empty branch rejoins a populated branch
- **WHEN** one branch is empty and a sibling branch produces rows for their merge
- **THEN** empty-only descendants are skipped, the sibling completes, and the merge processes its populated input

#### Scenario: Ingest produces no eligible rows
- **WHEN** ingestion returns no rows and reports no failed document
- **THEN** downstream operators are skipped and the attempt completes without writing document results

### Requirement: Fresh attempt state and cleanup

Each attempt SHALL use fresh operators and isolated configuration. On success or failure, cleanup SHALL call every
constructed operator's `cleanup()`, release attempt-owned table, route-state, and operator references before returning
or raising and before the next event, and log hook errors without changing the processing outcome or preventing other
cleanup. `AbstractOperator.cleanup()` SHALL default to a no-op; resource-owning operators MAY override it.

#### Scenario: Later event has fresh state
- **WHEN** a later event uses the same saved flow after an earlier event completes or fails
- **THEN** operator mutations and in-memory deduplication state from the earlier event are absent

#### Scenario: Attempt ends on success or failure
- **WHEN** an attempt succeeds or fails, including when an operator cleanup hook raises
- **THEN** resources for all constructed operators are released as far as supported and the processing outcome
  is retained
- **AND** attempt-owned intermediate table, route-state, and operator references are released before the attempt
  returns or raises and before any subsequent event starts

### Requirement: Job-independent execution context

Streaming execution SHALL NOT create jobs, job runs, job snapshots, batch artifacts, or job finalization records.
Operators SHALL retain their configured chunk/embedding spill behavior. Explicitly configured sinks SHALL retain their
persistence behavior.

#### Scenario: Sink completes without a tracked run
- **WHEN** a streaming flow writes its document to a configured sink
- **THEN** the sink result exists and no streaming job-run history is created

### Requirement: Synchronous terminal outcome

Successful completion SHALL be signalled only after all applicable operators and sinks finish. Exceptions and metadata
reporting failed documents or operator failure SHALL signal a failed attempt. Intentional filtering or skipped
documents alone SHALL NOT signal failure. Outcome signalling SHALL NOT return document tables or a durable job handle.

#### Scenario: Operator reports failure without raising
- **WHEN** ingestion or another operator returns normally with failed-document metadata
- **THEN** the attempt signals failure rather than treating an empty or partial result as successful completion

#### Scenario: Sink write fails
- **WHEN** a configured sink fails to persist its output
- **THEN** the attempt signals failure and does not report completion

#### Scenario: All applicable work completes
- **WHEN** every applicable operator and sink completes without a reported failure
- **THEN** the caller receives a completion signal without document data or a job-run identifier
