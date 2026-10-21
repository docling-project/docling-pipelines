# backend/ededup-operator Specification

## Purpose

The Ededup operator removes duplicate documents from pipeline processing by hashing normalized content and admitting one representative per hash at each operator node within a job run. Shared storage coordinates concurrent batches and workers while keeping admissions independent across jobs, runs, and branch nodes; output preserves accepted rows and reports removed documents in metadata. Admissions record deduplication decisions rather than downstream completion, so a same-node, same-run retry skips previously admitted content while a new run can process it again.

## Requirements

### Requirement: Node-scoped membership within a run
Shared deduplication SHALL admit at most one document for each `(job_id, job_run_id, node_id, hash)` across all batches, threads, and processes executing that node. Workers executing the same flow node MUST use the same node identity.

#### Scenario: Concurrent duplicate batches
- **WHEN** independent workers submit the same hash for the same job, run, and node
- **THEN** exactly one candidate is admitted if registration succeeds, and the others are skipped

### Requirement: Independent branch membership
Ededup nodes in different branches SHALL admit content independently. Admission in one branch MUST NOT suppress the same hash in another branch. Branch-local deduplication MUST NOT imply automatic deduplication of merged branch outputs.

#### Scenario: Branches after extraction
- **WHEN** both branches receive hash H after extraction and each branch has a distinct ededup node
- **THEN** each node can admit one representative of H and skips further H candidates within its own node/run

#### Scenario: Branch outputs merge
- **WHEN** both branches admitted H and their outputs are merged
- **THEN** these admissions do not suppress either branch's output at the merge

### Requirement: Independent runs and jobs
Deduplication SHALL retain independent membership for different runs and jobs. Admitting a hash in another run MUST NOT erase the original run's membership or require runs to execute sequentially.

#### Scenario: Interleaved runs
- **WHEN** node N in run A of job J1 admits H, node N in overlapping run B of J1 admits H, and a later batch at node N in A submits H
- **THEN** B accepts H and the later batch in A skips H

#### Scenario: Different job
- **WHEN** job J2 submits a hash already admitted by job J1, even with the same node identifier
- **THEN** that job can admit the hash independently

### Requirement: Batch representatives and output
The operator SHALL preserve existing content normalization, keep the first row per hash within a batch as its candidate, preserve accepted rows' input order and schema, and report every removed row as skipped.

#### Scenario: Local duplicates and repeated document IDs
- **WHEN** a batch contains duplicate hashes and distinct hashes with repeated document IDs
- **THEN** only the first row of each newly admitted hash passes through, without conflating distinct hashes by document ID

#### Scenario: Empty input
- **WHEN** an empty table is submitted
- **THEN** it returns empty without a registry request

### Requirement: Operator table and metadata contract
The operator SHALL accept a PyArrow table containing its configured content column and document ID/hash column. It SHALL return one output table containing accepted rows in input order with the input schema unchanged, together with metadata reporting processed and removed counts and a skipped-document record for every removed row. A skipped record SHALL include the document ID, name, and reason, and include the source path when available.

#### Scenario: Valid input table
- **WHEN** a table contains the required content and document ID/hash columns
- **THEN** the operator returns a single schema-preserving output table and metadata describing accepted and skipped rows

#### Scenario: Missing required input column
- **WHEN** a non-empty table lacks the configured content column or document ID/hash column
- **THEN** the operator fails explicitly instead of silently admitting rows

### Requirement: Bulk atomic registration
PostgreSQL registration SHALL process sets of candidates rather than issue per-document requests. Only newly committed admissions SHALL pass through. A failed registration MUST propagate an error and MUST NOT leave partial admissions from that call.

#### Scenario: Conflicting candidates
- **WHEN** a bulk call contains previously admitted and unseen hashes
- **THEN** only the unseen hashes are registered and returned as accepted

#### Scenario: Failure after an earlier internal chunk
- **WHEN** registration fails after writing part of a bulk call
- **THEN** the entire call rolls back and produces no successful operator output

### Requirement: Retained admission metadata
Each PostgreSQL admission SHALL retain job ID, run ID, node ID, content hash, and the accepted document's ID. Source deletion MUST NOT remove admission records. Later runs SHALL record their own accepted document IDs without modifying earlier runs.

#### Scenario: Renamed source in a later run
- **WHEN** a document reaching deduplication has the same content under a new ID in a new run
- **THEN** each branch's node can accept it with the new ID and the prior run's records remain unchanged

#### Scenario: Renamed source in the same node and run
- **WHEN** a filename change produces a new document ID but its hash was already admitted by that node in the same job run
- **THEN** the renamed candidate is skipped and the original admission's document ID remains unchanged

#### Scenario: Renamed source in another branch
- **WHEN** a renamed candidate reaches a different branch's node that has not admitted its hash in this run
- **THEN** that node accepts it independently of the first branch's admission

#### Scenario: Source deletion
- **WHEN** an admitted document is deleted from its source
- **THEN** its admission remains and does not prevent acceptance in another run

### Requirement: Admission is distinct from downstream completion
A committed admission SHALL remain registered if downstream processing fails. Replaying that hash at the same node in the same run SHALL skip it; processing in a new run SHALL remain possible.

#### Scenario: Downstream failure and retry
- **WHEN** downstream work fails after H was admitted and H is submitted again to the same node
- **THEN** the same run skips H and a new run can admit H

### Requirement: Supported operator invocation contract
The operator SHALL reject the legacy backend-only `filter` argument and SHALL accept direct transforms as `transform(table)` without a `file_name` keyword. When callers provide job and run context, they MUST also provide the flow node ID; incomplete shared context SHALL fail explicitly. The UI does not expose a `filter` field.

#### Scenario: Legacy filter argument
- **WHEN** a caller configures ededup with the legacy `filter` argument
- **THEN** operator initialization fails with an explicit unsupported-argument error

#### Scenario: Legacy transform filename argument
- **WHEN** a caller invokes `transform(table, file_name=...)`
- **THEN** the call is rejected; callers invoke `transform(table)`

#### Scenario: Job/run context without node ID
- **WHEN** a caller provides job and run context without a node ID
- **THEN** shared admission fails explicitly rather than using an unnamed node

### Requirement: Existing backend compatibility
The existing filesystem backend SHALL use the same job/run/node membership semantics for workers sharing its directory. Standalone operation without job/run context SHALL retain local deduplication. Shared operation MUST require job ID, run ID, and node ID; incomplete context MUST fail explicitly.

#### Scenario: Shared filesystem instances
- **WHEN** two operator instances with the same node ID share a filesystem registry and the same job/run
- **THEN** only one admits a given hash

#### Scenario: Missing node identity
- **WHEN** valid job and run context exists without a node ID
- **THEN** shared deduplication fails explicitly instead of using a shared unnamed node

#### Scenario: Incomplete run identity
- **WHEN** exactly one of job ID and run ID is present
- **THEN** the operator rejects the call instead of silently using local state

### Requirement: Existing registry compatibility
Existing node-scoped admission records SHALL retain their job/run/node/hash membership and representative document IDs. Reinitializing a store MUST NOT merge nodes, reset admissions, or modify unrelated incremental metadata.

#### Scenario: Existing records from multiple nodes
- **WHEN** a registry containing admissions for the same hash at two distinct branch nodes is reopened
- **THEN** both records remain independent and each node continues rejecting that hash only within its own job/run membership

### Requirement: Independent deduplication storage lifecycle
Deduplication SHALL own admission storage independently of incremental source tracking. It MUST operate without initializing or reading incremental metadata storage. Initializing either subsystem MUST NOT create or manage the other subsystem's records.

#### Scenario: Ededup-only PostgreSQL initialization
- **WHEN** deduplication starts in an empty configured schema without incremental processing
- **THEN** it creates its admission table without creating the incremental source-tracking table

#### Scenario: Incremental-only initialization
- **WHEN** incremental source tracking starts without deduplication
- **THEN** it does not create or initialize an admission registry

### Requirement: Independent deduplication configuration
Deduplication SHALL resolve storage from `ededup.storage`, shared `global_storage` defaults, then filesystem defaults. Incremental service-specific settings MUST NOT select ededup storage. Invalid ededup backend settings MUST fail explicitly rather than silently use another backend.

#### Scenario: Independent service overrides
- **WHEN** deduplication selects PostgreSQL and incremental metadata selects filesystem
- **THEN** deduplication uses PostgreSQL independently of the incremental setting

#### Scenario: Incremental configuration changes
- **WHEN** incremental service-specific settings change while ededup and global storage settings remain unchanged
- **THEN** deduplication continues using the same registry

#### Scenario: Existing registry location
- **WHEN** dedicated ededup settings point to an existing node-scoped admission table or filesystem directory
- **THEN** all recorded memberships and document IDs remain available without resetting admission history

#### Scenario: Invalid ededup backend
- **WHEN** an unknown backend is explicitly configured for deduplication
- **THEN** initialization fails with a configuration error

### Requirement: Persistent default registry
Pipeline execution with complete job, run, and node context SHALL use persistent registry storage by default. The filesystem default SHALL retain admissions across operator instances sharing the same data directory. Standalone operation without job/run context MAY retain only per-instance in-memory state.

#### Scenario: Persistent default registry
- **WHEN** pipeline execution runs with complete job, run, and node context without an explicit ededup backend
- **THEN** the filesystem default persists admissions across operator instances using the same data directory
