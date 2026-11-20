# Spec Delta

## Purpose

The document-set-data-card capability gives every document set a provenance record. It states which flows, jobs, and job runs wrote the document set, what each run read, and how it chunked, embedded, and indexed the content, without recording secrets. The card is maintained automatically by pipeline runs and is readable and partly editable through the REST API.

## ADDED Requirements

### Requirement: Data card structure
A data card SHALL hold the descriptive fields `purpose`, `summary`, `curator` (`id` and `type`), `language`, `collection_criteria`, and `propagate_source_acls`, and a `flows` list. Each flow SHALL hold `type` and `details` (`id`, `name`, `jobs`). Each job SHALL hold `id`, `name`, `documents`, and `runs`. Each run SHALL hold `id`, `executed_at`, `duration`, and `operators`. All descriptive fields SHALL be optional.

#### Scenario: Empty card
- **WHEN** a data card is created with no values
- **THEN** every descriptive field is null and `flows` is an empty list

#### Scenario: Nested provenance
- **WHEN** a card records one run of one job of one flow
- **THEN** the run is reachable as `flows[0].details.jobs[0].runs[0]` with its `operators` list

#### Scenario: Job name is null
- **WHEN** a pipeline run records itself
- **THEN** the job entry has its job ID as `id` and a null `name`

### Requirement: Enterprise-shaped cards load without loss
Loading a card from a dictionary SHALL accept every field of the enterprise data card schema that this capability documents, SHALL ignore unknown keys, and SHALL tolerate missing keys. Serializing a loaded card SHALL reproduce every documented field it was given.

#### Scenario: Enterprise card round trip
- **WHEN** a sample enterprise card containing flows of type `ibm_udp_flow`, jobs, runs, sources, embeddings, chunk details, and a derivative store is loaded and serialized
- **THEN** every documented field of the input is present and equal in the output

#### Scenario: Fields absent from an enterprise card load as null
- **WHEN** an enterprise card has embeddings without `provider` and a derivative store without `add_sparse_vector` and `table_prefix`
- **THEN** loading succeeds, `provider`, `add_sparse_vector`, and `table_prefix` are null

#### Scenario: Feature mappings survive a round trip
- **WHEN** an enterprise card whose derivative store carries `feature_mappings` with `feature_name` and `mapped_column_name` items is loaded and serialized
- **THEN** the serialized derivative store holds the same items

#### Scenario: Malformed feature mappings load leniently
- **WHEN** a derivative store holds `feature_mappings` that is not a list, or a list with items that are not objects
- **THEN** loading succeeds, a non-list value loads as null, and the non-object items are dropped

#### Scenario: Unknown keys ignored
- **WHEN** a card dictionary contains a key that the schema does not define
- **THEN** loading succeeds and the key is absent from the serialized card

#### Scenario: Legacy flat card tolerated
- **WHEN** a stored card holds only the former flat keys `flow_id`, `flow_name`, `job_id`, `job_run_id`, `operators`, and `lineage_metadata`
- **THEN** loading succeeds and yields a card with no flows

### Requirement: Card persists with the document set
The data card SHALL be stored and returned together with its document set by every supported metadata repository (DuckDB, Postgres, and local). A document set without a card SHALL serialize its card as null. Updating the document set description or metadata SHALL NOT alter the card.

#### Scenario: Card survives reload
- **WHEN** a document set with a card is saved and loaded again
- **THEN** the loaded card equals the saved card

#### Scenario: Description update keeps card
- **WHEN** the description of a document set that has a card is updated
- **THEN** the card is unchanged

#### Scenario: Deleting the document set deletes the card
- **WHEN** a document set is deleted
- **THEN** its card is no longer retrievable

### Requirement: Run recorded after rows are stored
After the `document_set` operator has stored rows in its document set, it SHALL record the current job run in the card of that document set. This SHALL apply both when the operator creates the document set and when it updates an existing one by `document_set_id`.

#### Scenario: First run creates the flow entry
- **WHEN** a flow run stores rows in a document set whose card has no flows
- **THEN** the card gains one flow entry holding one job with one run whose `id` is the job run ID

#### Scenario: Update by identifier records the run
- **WHEN** the operator is configured with an existing `document_set_id` and stores rows
- **THEN** the run is recorded in that document set's card

### Requirement: No run recorded when nothing was stored
The operator SHALL NOT record a run when it received no rows or when storing the rows failed.

#### Scenario: Empty table
- **WHEN** the operator receives a table with zero rows
- **THEN** the document set's card is unchanged

#### Scenario: Store failure
- **WHEN** storing the rows raises an error
- **THEN** the document set's card is unchanged

### Requirement: Flows, jobs, and runs are keyed by identifier
A flow entry SHALL be identified by the flow ID, a job by the job ID within its flow, and a run by the job run ID within its job. Recording a run SHALL add the missing flow, job, or run entries and SHALL NOT change entries for other identifiers. A new flow entry SHALL use `type` `docpipe_flow` and the flow name recorded at run time.

#### Scenario: Second flow appended
- **WHEN** a different flow writes to a document set whose card already lists another flow
- **THEN** the card lists both flows and the first is unchanged

#### Scenario: New run added to existing job
- **WHEN** a new job run of a known job is recorded
- **THEN** the job holds the earlier runs and the new run

#### Scenario: Run without a flow ID
- **WHEN** a flow without a flow ID (an inline run) is named `adhoc-docs` and records a run
- **THEN** the flow entry uses `adhoc-docs` as its `id` and `name`, and a later run of the same inline flow joins that entry

### Requirement: Recording is idempotent per job run
Recording the same job run again SHALL replace that run's entry instead of adding another. The replaced entry SHALL keep its original `executed_at`. This SHALL hold when micro-batches of one run record in sequence or concurrently within one process.

#### Scenario: Micro-batches of one run
- **WHEN** three micro-batches of one job run each store rows and record the run
- **THEN** the job holds exactly one run entry for that job run ID

#### Scenario: Start time preserved
- **WHEN** a run entry is replaced by a later recording of the same run
- **THEN** its `executed_at` equals the value of the first recording

### Requirement: Run history is bounded
The card SHALL keep at most 50 runs per flow entry across all of its jobs. When a recording would exceed the limit, the oldest runs by `executed_at` SHALL be removed, and a job left without runs SHALL be removed.

#### Scenario: Oldest run dropped
- **WHEN** a flow entry holds 50 runs and a new run is recorded
- **THEN** the flow entry holds 50 runs, the new run is present, and the oldest run is gone

#### Scenario: Empty job removed
- **WHEN** retention removes the last run of a job
- **THEN** that job is no longer listed

### Requirement: Run timing and document counts
A recorded run SHALL carry `executed_at` as an RFC 3339 UTC timestamp of the job run start and `duration` as whole seconds elapsed at the time of recording. When job statistics for the run are available, the job's `documents.input_count` and `documents.processed_count` SHALL come from the run's total and completed document counters, and otherwise SHALL be null. `input_size` and `processed_size` SHALL be null.

#### Scenario: Statistics available
- **WHEN** a run is recorded and job statistics report 10 total and 8 completed documents
- **THEN** the job shows `input_count` 10 and `processed_count` 8

#### Scenario: Statistics unavailable
- **WHEN** a run is recorded and no job statistics exist for it
- **THEN** `executed_at` is the recording time, `documents` counts are null, and recording succeeds

### Requirement: Upstream operators are listed
A recorded run's `operators` SHALL list every node in the flow definition from which the `document_set` node is reachable through its input edges, including all branches feeding a merge node, ordered from upstream to downstream. Each entry SHALL carry `type` (the operator short name), `node_id`, and `name`. The `document_set` node itself SHALL NOT be listed.

#### Scenario: Linear flow
- **WHEN** the flow is ingest, extract, chunker, then document set
- **THEN** the run lists the ingest, extract, and chunker operators in that order and not the document set node

#### Scenario: Branched flow
- **WHEN** two branches merge before the document set node
- **THEN** operators of both branches and the merge node are listed

#### Scenario: Unrelated node excluded
- **WHEN** a node in the flow is neither an ancestor of the document set node nor a downstream `vectordb` or `entity_store` node
- **THEN** it is not listed

### Requirement: Downstream derivative sinks are listed
A recorded run's `operators` SHALL also list every `vectordb` and `entity_store` node of the flow definition that is reachable from the `document_set` node through the input edges of other nodes (a node downstream of it). No other downstream node SHALL be listed. The whole list SHALL be ordered from upstream to downstream, so that an `embeddings` entry that feeds a `vectordb` entry precedes it. The entry SHALL carry the same details as an upstream node of the same type.

#### Scenario: Vector index written after the document set
- **WHEN** the flow is ingest, extract, chunker, embeddings, document set, then vectordb
- **THEN** the run lists the ingest, extract, chunker, embeddings, and vectordb operators in that order, with the vectordb entry carrying its derivative store

#### Scenario: Other downstream node not listed
- **WHEN** a `noop` node follows the document set node
- **THEN** it is not listed

#### Scenario: Sibling sink not listed
- **WHEN** a `vectordb` node hangs off the embeddings node on a branch that does not include the document set node
- **THEN** it is not listed

### Requirement: Missing flow definition
When the flow definition is not available to the operator, the run SHALL still be recorded with an empty `operators` list.

#### Scenario: Definition absent
- **WHEN** the operator runs without a flow definition in its configuration
- **THEN** the run is recorded with `operators` equal to an empty list and the flow's identifiers

### Requirement: Ingest source details
For an upstream `ingest_source` node, the operator entry SHALL carry one `sources` item whose `input` is the provider name, with a `name` and `paths` built only from the provider's location fields: filesystem `paths`; S3 and IBM COS `bucket` and `prefix`; SharePoint, OneDrive, and Dropbox `folder_path` and `file_path`; Google Drive and Box folder and file identifiers; web `urls` reduced to scheme, host, port, and path.

#### Scenario: S3 source
- **WHEN** an ingest node uses provider `s3` with bucket `docs` and prefix `incoming/`
- **THEN** the source has `input` `s3`, `name` `docs`, and `paths` containing `incoming/`

#### Scenario: Web URL reduced
- **WHEN** a web ingest node lists the URL `https://example.com/a/b` with user information, a query string, and a fragment added
- **THEN** the recorded path is `https://example.com/a/b`

### Requirement: Chunking details
For an upstream `chunker` node, the entry SHALL carry `chunk_details` with `type` set to the chunk type and `size` set to the configured chunk size or null.

#### Scenario: Chunker details
- **WHEN** a chunker node is configured with type `hybrid` and size 512
- **THEN** its entry shows `chunk_details` with type `hybrid` and size 512

### Requirement: Embedding details
For an upstream `embeddings` node, the entry SHALL carry one `embeddings` item with `type` `dense`, `provider` set to the node's embedding provider (`litellm` when the node does not set one), `model_id` from the provider configuration, `feature` set to the embeddings column name, and `dimension_size` set to the length of the first non-null vector in that column of the stored table, or null. A provider value that is a `vault://` reference SHALL be omitted.

#### Scenario: Provider recorded
- **WHEN** an embeddings node sets provider `watsonx` and model `ibm/slate-125m-english-rtrvr`
- **THEN** its entry shows `provider` `watsonx` and that `model_id`

#### Scenario: Default provider recorded
- **WHEN** an embeddings node sets no provider
- **THEN** its entry shows `provider` `litellm`

#### Scenario: Embedding dimension from data
- **WHEN** an embeddings node writes the `embeddings` column and the stored vectors have 384 values
- **THEN** its entry shows `dimension_size` 384 and `feature` `embeddings`

### Requirement: Vector database derivative store
For a listed `vectordb` node (upstream or downstream of the document set), the entry SHALL carry a `derivative_store` whose `name` is the provider and whose `path` is the index or collection name. The entry SHALL NOT record hosts, URIs, ports, or any connection parameter.

#### Scenario: OpenSearch index
- **WHEN** a vectordb node uses provider `opensearch` with index `docs_v1`
- **THEN** its entry shows a derivative store with name `opensearch` and path `docs_v1`

#### Scenario: Connection parameters excluded
- **WHEN** the vectordb node sets `host`, `port`, and `uri`
- **THEN** none of those values appears in the card

### Requirement: Vector database sparse mode
The `derivative_store` of a listed `vectordb` node SHALL carry `add_sparse_vector` true when the node runs in sparse mode and false otherwise. Sparse mode is set by the node's `add_sparse_vector` when present, otherwise by `provider_config.add_sparse_vector`, or by `provider_config.vector_mode` equal to `sparse`.

#### Scenario: Sparse vectors enabled
- **WHEN** a vectordb node sets `add_sparse_vector` to true
- **THEN** its derivative store shows `add_sparse_vector` true

#### Scenario: Sparse flag in provider configuration
- **WHEN** a vectordb node sets `add_sparse_vector` to true only inside `provider_config`
- **THEN** its derivative store shows `add_sparse_vector` true

#### Scenario: Node setting wins
- **WHEN** a vectordb node sets `add_sparse_vector` to false and `provider_config.add_sparse_vector` to true
- **THEN** its derivative store shows `add_sparse_vector` false

#### Scenario: Sparse vector mode
- **WHEN** a Milvus vectordb node sets `provider_config.vector_mode` to `sparse` and no `add_sparse_vector`
- **THEN** its derivative store shows `add_sparse_vector` true

#### Scenario: Sparse vectors default
- **WHEN** no sparse setting is present
- **THEN** its derivative store shows `add_sparse_vector` false

### Requirement: Vector database feature mappings
For a `vectordb` node that sets a non-empty `feature_mappings` parameter, the derivative store SHALL carry `feature_mappings` as the list of its items that have string `feature_name` and string `mapped_column_name`, in the configured order. When the node sets no mappings, `feature_mappings` SHALL be null and SHALL NOT be computed from defaults. The embedding `feature` of an `embeddings` entry SHALL remain the name of the source table column.

#### Scenario: Explicit mappings recorded
- **WHEN** a vectordb node maps the feature `embeddings` to the column `vec`, `id` to `doc_id`, and `allowed_users` to `allowed_users`
- **THEN** its derivative store lists those three items with their feature and column names

#### Scenario: No mappings recorded as null
- **WHEN** a vectordb node sets no `feature_mappings`
- **THEN** its derivative store shows `feature_mappings` null

#### Scenario: Malformed mapping items dropped
- **WHEN** a vectordb node's `feature_mappings` holds an item without `mapped_column_name`
- **THEN** that item is not recorded and the valid items are

#### Scenario: Embedding feature is the source column
- **WHEN** an embeddings node writes the column `embeddings` and a vectordb node maps it to `vector_embeddings`
- **THEN** the embeddings entry shows `feature` `embeddings` and the derivative store maps that feature to `vector_embeddings`

### Requirement: Entity store derivative store
For an `entity_store` node listed in a run, the entry SHALL carry a `derivative_store` whose `name` is the node's `data_backend` (`duckdb` when not set), whose `path` is its `database_path` for `duckdb` (`:memory:` when not set) and its `schema` for `postgres`, and whose `table_prefix` is the node's `table_prefix` (`entity_` when not set). The entry SHALL NOT record table names, hosts, ports, users, passwords, or any other connection parameter.

#### Scenario: File-backed DuckDB entity store
- **WHEN** an entity store node uses `data_backend` `duckdb` with `database_path` `data/duckdb/entities.duckdb`
- **THEN** its derivative store shows name `duckdb`, that path, and prefix `entity_`

#### Scenario: Defaults
- **WHEN** an entity store node sets no storage parameters
- **THEN** its derivative store shows name `duckdb`, path `:memory:`, and prefix `entity_`

#### Scenario: Postgres entity store
- **WHEN** an entity store node uses `data_backend` `postgres` with schema `docpipe_entities` and connection parameters
- **THEN** its derivative store shows name `postgres`, path `docpipe_entities`, and the prefix, and none of the connection parameters appears in the card

### Requirement: Derived descriptive fields
When the flow has an upstream `lang_detect` node and the stored table has a `lang_name` column, recording SHALL set the card's `language` to the most frequent value other than `UNKNOWN`, only when `language` is currently null.

#### Scenario: Language derived
- **WHEN** a run records with `lang_name` values `en`, `en`, and `fr` and the card language is null
- **THEN** the card language becomes `en`

#### Scenario: Existing value kept
- **WHEN** the card language is already `de` and a run derives `en`
- **THEN** the card language stays `de`

### Requirement: ACL propagation flag
Recording SHALL derive `propagate_source_acls` from the whole flow definition: true when any node is an `acl_operator`, otherwise false. The stored value SHALL be merged so that true replaces null and false, false replaces null, and true is never replaced by false. `propagate_source_acls` SHALL be null only while no run has been recorded.

#### Scenario: ACL propagation derived
- **WHEN** the flow contains an upstream ACL operator and `propagate_source_acls` is null
- **THEN** `propagate_source_acls` becomes true

#### Scenario: ACL operator on another branch still counts
- **WHEN** the flow contains an `acl_operator` node that is not an ancestor of the document set node
- **THEN** `propagate_source_acls` becomes true

#### Scenario: Flow without an ACL operator records false
- **WHEN** a run is recorded for a flow with no `acl_operator` node and `propagate_source_acls` is null
- **THEN** `propagate_source_acls` becomes false

#### Scenario: True is never lowered
- **WHEN** `propagate_source_acls` is true and a later run of a flow without an ACL operator is recorded
- **THEN** `propagate_source_acls` stays true

#### Scenario: False is raised
- **WHEN** `propagate_source_acls` is false and a later run of a flow with an ACL operator is recorded
- **THEN** `propagate_source_acls` becomes true

#### Scenario: Unrecorded card stays unknown
- **WHEN** recording the first run fails
- **THEN** `propagate_source_acls` remains null, not false

### Requirement: Recording does not overwrite user-managed fields
Recording a run SHALL change only the `flows` section, a null `language`, and `propagate_source_acls` as merged by the derived-fields requirement. It SHALL NOT change `purpose`, `summary`, `curator`, or `collection_criteria`, and SHALL NOT change a non-null `language`.

#### Scenario: User fields intact
- **WHEN** a run is recorded for a card whose `purpose`, `summary`, `curator`, and `collection_criteria` were set through the API
- **THEN** those four fields are unchanged

### Requirement: No secrets in the card
The card SHALL be built only from the allowlisted fields named in this capability. Credentials, tokens, keys, passwords, `vault://` references, URL user information, query strings, and fragments SHALL NOT appear in the card. A location field whose configured value is a `vault://` reference SHALL be omitted.

#### Scenario: Credentials never recorded
- **WHEN** upstream nodes configure `access_key`, `secret_key`, `api_key`, and `client_secret` values
- **THEN** none of those values appears anywhere in the serialized card

#### Scenario: Vault reference omitted
- **WHEN** an S3 node sets `bucket` to a `vault://` reference
- **THEN** the source carries no bucket-derived name or path

#### Scenario: Resolved secret never reaches the card
- **WHEN** a flow runs through the executor, an upstream node sets a location field to a `vault://` reference, and the provider can resolve it to a canary value
- **THEN** neither the reference nor the canary value appears in the serialized card

### Requirement: Recording failures are isolated
A failure while building or saving the card SHALL be logged and SHALL NOT fail the node, the flow, or the stored data. The node metadata SHALL report `data_card_status` as `recorded` or `failed`, and on failure SHALL add `data_card_error` holding the exception class name only.

#### Scenario: Save fails
- **WHEN** saving the card raises an error after rows were stored
- **THEN** the node completes, the table passes through, `data_card_status` is `failed`, and `data_card_error` names the exception class

#### Scenario: Success reported
- **WHEN** the card is saved
- **THEN** `data_card_status` is `recorded` and `data_card_error` is absent

### Requirement: Concurrent recording keeps every run
Within one process, every update of a document set (recording a run, storing rows and refreshing statistics, updating the description or metadata, and updating the card through the API) SHALL be serialized per document set, so that concurrent micro-batches, flows, or requests do not discard each other's card entries.

#### Scenario: Parallel runs of different flows
- **WHEN** two flows record runs into the same document set at the same time
- **THEN** the card holds the entries of both flows

#### Scenario: Store racing with recording
- **WHEN** one micro-batch stores rows and refreshes statistics while another records its run
- **THEN** the card still holds the recorded run after both finish

### Requirement: Operator table contract unchanged
Recording SHALL NOT alter the operator's pyarrow Table input or output. The operator SHALL still require an `id` column, SHALL return the input table unchanged, and SHALL keep every existing transform metadata key.

#### Scenario: Pass-through
- **WHEN** the operator stores rows and records the card
- **THEN** the returned table equals the input table and the existing metadata keys are present with their previous values
