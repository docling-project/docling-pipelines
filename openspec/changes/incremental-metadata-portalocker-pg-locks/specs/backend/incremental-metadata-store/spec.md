## ADDED Requirements

### Requirement: Store contract is identical across backends
Every `IncrementalMetadataStore` backend SHALL implement the same observable contract for `get_processed_docs`, `upsert_records`, `get_soft_deleted_doc_ids`, `mark_missing_docs_as_deleted`, `unmark_soft_deleted_docs`, `purge_soft_deleted_docs`, `delete_docs`, and `clear`, keyed by `(job_id, doc_id)`.

#### Scenario: Upsert replaces an existing record
- **WHEN** `upsert_records` is called with a record whose `(job_id, doc_id)` already exists
- **THEN** the stored `name`, `modified_time`, and `job_run_id` are replaced and `deleted` is `false`

#### Scenario: Duplicate doc ids in one batch
- **WHEN** one `upsert_records` call contains two records with the same `doc_id`
- **THEN** the call succeeds and the last record in the list is stored once, on every backend

#### Scenario: Processed docs exclude soft-deleted records
- **WHEN** a record is soft-deleted
- **THEN** `get_processed_docs` omits it and `get_soft_deleted_doc_ids` includes it

#### Scenario: Missing docs are marked deleted
- **WHEN** `mark_missing_docs_as_deleted` is called with the ids currently present in the source
- **THEN** every non-deleted record for the job whose id is not in that list is marked deleted and its id is returned
- **AND** records already deleted are not returned

#### Scenario: Empty current list marks everything missing
- **WHEN** `mark_missing_docs_as_deleted` is called with an empty list
- **THEN** all non-deleted records for the job are marked deleted

### Requirement: Filesystem backend uses shared and exclusive file locks
The filesystem backend SHALL guard each job's parquet file with a `portalocker` lock on a separate per-job lock file. Read methods SHALL take a shared lock and write methods SHALL take an exclusive lock. The lock SHALL NOT be taken on the parquet file itself.

#### Scenario: Concurrent readers
- **WHEN** two threads or processes call `get_processed_docs` for the same job at the same time
- **THEN** neither waits for the other

#### Scenario: Writer excludes readers and writers
- **WHEN** a write method holds the exclusive lock for a job
- **THEN** other readers and writers for that job wait until it is released
- **AND** writers for a different job are not blocked

#### Scenario: Lock timeout
- **WHEN** a lock cannot be acquired within `lock_timeout` seconds
- **THEN** the store raises `FlowExecutionFailedException` naming the job
- **AND** `upsert_records` retries with exponential backoff before failing

#### Scenario: Atomic file replacement
- **WHEN** a write method updates the parquet file
- **THEN** it writes a temporary file and replaces the original atomically while holding the exclusive lock

### Requirement: Filesystem backend is single-machine only
The filesystem backend SHALL be documented as safe only for processes sharing one host's local POSIX filesystem. Deployments whose workers run on different hosts SHALL use the `postgresql` backend.

#### Scenario: Documentation states the limit
- **WHEN** a reader consults `ADVANCED_CONFIGURATION.md`
- **THEN** it states that the filesystem backend is not supported across hosts or on NFS and object-store mounts

### Requirement: PostgreSQL backend serialises writes per job
Every PostgreSQL write method SHALL execute inside one transaction that first acquires `pg_advisory_xact_lock` for the job, then performs set-based SQL. The lock SHALL be transaction-scoped and released on commit, rollback, or connection loss. Read methods SHALL NOT take the advisory lock.

#### Scenario: Concurrent upserts for one job
- **WHEN** two workers call `upsert_records` for the same job at the same time
- **THEN** both succeed, no unique-violation error is raised, and the stored rows reflect both batches

#### Scenario: Different jobs do not contend
- **WHEN** two workers write to different jobs
- **THEN** neither waits for the other's advisory lock, except on a hash collision, which affects timing only and never correctness

#### Scenario: Upsert is one statement
- **WHEN** `upsert_records` runs
- **THEN** records are written with `INSERT ... ON CONFLICT (job_id, id) DO UPDATE` in batches, ordered by `doc_id`, with no per-record read

#### Scenario: Mark missing is one statement
- **WHEN** `mark_missing_docs_as_deleted` runs
- **THEN** one `UPDATE ... RETURNING` marks and returns the affected ids, without reading rows into Python

#### Scenario: Lock wait is bounded
- **WHEN** the advisory lock is not granted within the configured `lock_timeout`
- **THEN** the store raises `FlowExecutionFailedException`
- **AND** `upsert_records` retries with exponential backoff before failing

### Requirement: PostgreSQL backend targets its configured schema
The PostgreSQL backend SHALL create and query the `inc_update_metadata` table in the configured schema (default `incremental_metadata`), independent of the connection's `search_path`.

#### Scenario: Custom schema
- **WHEN** the store is configured with `schema: custom_schema`
- **THEN** every statement addresses `custom_schema.inc_update_metadata`

#### Scenario: Default schema is queryable
- **WHEN** the store is configured with no explicit schema
- **THEN** reads and writes address `incremental_metadata.inc_update_metadata`, not `public`

### Requirement: PostgreSQL bootstrap is safe under concurrent startup
Schema and table creation SHALL run in one transaction guarded by an advisory lock, so several replicas can initialise the store at the same time.

#### Scenario: Replicas start together
- **WHEN** two processes initialise the store against an empty database at the same time
- **THEN** both initialise without a duplicate-object error
