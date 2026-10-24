# Spec Delta

## Purpose

Execute one event-referenced document through a saved flow's existing operators with in-memory intermediates,
isolated attempt state, and synchronous outcome signalling without creating a tracked job run.

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
- **THEN** processing fails before an operator runs and identifies the flow and preparation failure

### Requirement: Runtime integrity without full per-event validation

Streaming execution SHALL retain compilation and runtime integrity checks without running full operator validation
for each event. A cycle, unresolved edge, duplicate node identity, invalid root, or unavailable operator SHALL fail
explicitly. The executable graph SHALL have exactly one ingest root and be connected to that root.

#### Scenario: Invalid executable graph
- **WHEN** a saved graph contains a cycle, missing edge target, duplicate node identity, disconnected node,
  or multiple roots
- **THEN** preparation fails before document processing rather than executing a partial graph

#### Scenario: Required operator is unavailable
- **WHEN** a flow references an operator unavailable through configured operator discovery
- **THEN** the attempt reports that operator as unavailable before document processing

#### Scenario: Per-event validation is avoided
- **WHEN** a valid saved flow processes several events
- **THEN** execution does not invoke full flow or operator validation for each event, while compilation checks
  remain active

### Requirement: One document bound through the configured provider

Each event SHALL bind its existing file reference to the ingest provider's single-file binding contract and force
reprocessing for both create and update operations. Source credentials, include/exclude filters, and provider-native
reference meanings SHALL be preserved. The event SHALL NOT expand processing to other configured source documents.

#### Scenario: Create and update bypass incremental exclusion
- **WHEN** create and update events reference a document that was processed previously
- **THEN** each attempt ingests that document again using the configured provider and credentials

#### Scenario: Source filters exclude the document
- **WHEN** the referenced document is excluded by the saved flow's source filters
- **THEN** ingestion reports a skip, downstream routes receive no rows, and the attempt completes without a failure

#### Scenario: Provider cannot bind the reference
- **WHEN** the configured provider rejects or does not support the file-reference binding
- **THEN** the attempt fails explicitly instead of processing the provider's original collection of files

### Requirement: Existing operator discovery and configuration

Streaming execution SHALL honor configured built-in and custom operator discovery and existing flow-level and
node-level configuration precedence. Event binding and streaming execution constraints SHALL take precedence over
saved values that would select another input document, enable batching, or persist intermediate data.

#### Scenario: Custom operator in saved flow
- **WHEN** a saved flow references an enabled custom operator with a node-specific override
- **THEN** the discovered operator processes the event using the effective override

#### Scenario: Saved batch settings are present
- **WHEN** a saved flow enables micro-batching or filesystem-backed intermediate storage
- **THEN** the streaming attempt still executes sequentially with in-memory intermediate tables

### Requirement: Arrow table and metadata contract

Operator inputs and outputs SHALL retain the existing Arrow table schemas required and produced by the configured
operators. Each transform SHALL yield a list of Arrow tables and a metadata dictionary. Processing SHALL preserve
required document identifiers, branch metadata, and document outcome metadata; malformed results SHALL fail explicitly.

#### Scenario: Extraction produces multiple chunks
- **WHEN** one source document produces several downstream rows or chunks
- **THEN** all applicable rows reach subsequent operators with their identifiers and configured column types intact

#### Scenario: Malformed transform result
- **WHEN** an operator returns a non-table output or invalid metadata instead of the transform contract
- **THEN** the attempt fails with operator context before passing that result downstream

### Requirement: Feature metadata and output transformations

Streaming execution SHALL supply the feature metadata required by downstream operators and sinks, including merge
column disambiguation and embedding metadata. Configured output feature drops and renames SHALL apply to all
relevant output tables before downstream processing.

#### Scenario: Sink receives required feature metadata
- **WHEN** extraction, chunking, and embeddings precede a configured vector sink
- **THEN** the sink receives the table columns and feature metadata required to persist the configured fields
  and vectors

#### Scenario: Output features are transformed
- **WHEN** a node drops or renames configured output features
- **THEN** every relevant output table and downstream feature view reflect those transformations

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

Each attempt SHALL use fresh operator instances and isolated mutable configuration and session state. All constructed
operators SHALL release resources, calling supported cleanup hooks on success and failure. Cleanup errors SHALL be
logged without replacing the primary processing outcome or preventing other cleanup.

#### Scenario: Retry and later event have fresh state
- **WHEN** an event retries or a later event uses the same saved flow
- **THEN** operator mutations and in-memory deduplication state from the earlier attempt are absent

#### Scenario: Processing or cleanup fails
- **WHEN** a constructed operator fails during execution or its cleanup hook raises
- **THEN** resources for all constructed operators are released as far as supported and the processing outcome
  is retained

### Requirement: In-memory intermediates and job-independent context

Streaming execution SHALL keep intermediate tables, chunks, and embeddings in memory and SHALL NOT create jobs,
job runs, job snapshots, batch artifacts, or job finalization records. Operators SHALL run without inherited job/run
identifiers. Explicitly configured sinks SHALL retain their persistence behavior.

#### Scenario: Sink completes without a tracked run
- **WHEN** a streaming flow writes its document to a configured sink
- **THEN** the sink result exists, no streaming job-run history is created, and no intermediate spill files are written

#### Scenario: Existing session has batch identifiers
- **WHEN** streaming execution begins in a context that previously held job and run identifiers
- **THEN** operators observe no batch job/run identifiers and the prior context is restored after the attempt

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
