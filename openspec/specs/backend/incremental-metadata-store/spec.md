# backend/incremental-metadata-store Specification

## Purpose
Defines the observable contract and concurrency semantics for incremental metadata storage backends, covering per-job record tracking, soft-delete lifecycles, and backend locking guarantees.

## Requirements

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
- **AND** callers are expected to guard against unintentional empty source listings before invoking missing-doc diffing

### Requirement: Lock timeouts raise a unified error
Both backends SHALL raise `LockTimeoutError`, a subclass of `FlowExecutionFailedException`, when a lock cannot be acquired within the configured `lock_timeout`.

#### Scenario: Timeout error type
- **WHEN** a lock is not granted within `lock_timeout` on either backend
- **THEN** the store raises `LockTimeoutError` naming the job
- **AND** `upsert_records` retries with exponential backoff before failing

#### Scenario: Timeout seen through the service
- **WHEN** retries are exhausted or a non-retried method times out
- **THEN** `IncrementalUpdateService` raises `FlowExecutionFailedException` whose cause is the `LockTimeoutError`

### Requirement: lock_timeout is configurable on both backends
Both backends SHALL read `lock_timeout` (seconds, a positive number) from the top level of the incremental metadata storage config, with a default of `30.0`.

#### Scenario: PostgreSQL honours the configured timeout
- **WHEN** the `postgresql` backend is configured with `lock_timeout: 10`
- **THEN** each write transaction applies a 10 second lock timeout before taking the advisory lock

#### Scenario: Invalid value
- **WHEN** `lock_timeout` is zero, negative or not a number
- **THEN** store construction fails with a configuration error

### Requirement: Filesystem backend uses shared and exclusive file locks
The filesystem backend SHALL guard each job's parquet file with a `portalocker` lock on a separate per-job lock file. Read methods SHALL take a shared lock and write methods SHALL take an exclusive lock. The lock SHALL NOT be taken on the parquet file itself, and the lock file SHALL NOT be deleted by any operation, including `clear()`.

#### Scenario: Concurrent readers
- **WHEN** two threads or processes call `get_processed_docs` for the same job at the same time
- **THEN** neither waits for the other

#### Scenario: Writer excludes readers and writers
- **WHEN** a write method holds the exclusive lock for a job
- **THEN** other readers and writers for that job wait until it is released
- **AND** writers for a different job are not blocked

#### Scenario: Atomic file replacement
- **WHEN** a write method updates the parquet file
- **THEN** it writes a temporary file and replaces the original atomically while holding the exclusive lock

#### Scenario: Clear retains the lock file
- **WHEN** `clear` is called for a job
- **THEN** the parquet data file is removed
- **AND** `.locks/metadata.lock` still exists

### Requirement: Backend selection follows the deployment mode
Distributed execution, where workers run on more than one host, SHALL use the `postgresql` backend. A single-machine deployment MAY use either the `postgresql` or the `filesystem` backend. The filesystem backend SHALL be documented as safe only for processes sharing one host's local POSIX filesystem.

#### Scenario: Single machine with either backend
- **WHEN** all workers run on one host
- **THEN** both `filesystem` and `postgresql` give the same observable store behaviour and concurrency guarantees

#### Scenario: Documentation states the limit
- **WHEN** a reader consults `ADVANCED_CONFIGURATION.md`
- **THEN** it states that the filesystem backend is not supported across hosts or on NFS and object-store mounts

### Requirement: PostgreSQL backend serialises writes per job
Every PostgreSQL write method SHALL execute inside one transaction that first applies `lock_timeout`, then acquires `pg_advisory_xact_lock` for the job, then performs set-based SQL. The lock SHALL be transaction-scoped and released on commit, rollback, or connection loss. Read methods SHALL NOT take the advisory lock.

#### Scenario: Concurrent upserts for one job
- **WHEN** two workers call `upsert_records` for the same job at the same time, including batches with duplicate or overlapping keys
- **THEN** both succeed, no unique-violation error is raised, and the latest record for each key is stored

#### Scenario: Different jobs do not contend
- **WHEN** two workers write to different jobs
- **THEN** neither waits for the other's advisory lock, except on a hash collision, which affects timing only and never correctness

#### Scenario: Mark missing updates and returns affected ids atomically
- **WHEN** `mark_missing_docs_as_deleted` runs
- **THEN** missing records are marked deleted and their ids returned in one statement, serialised against concurrent writes for the job

#### Scenario: Lock wait is bounded
- **WHEN** the advisory lock, or a row lock taken by the write, is not granted within the configured `lock_timeout`
- **THEN** the store raises `LockTimeoutError`, mapped from the driver's lock-not-available error
- **AND** `upsert_records` retries with exponential backoff before failing

#### Scenario: Timeout leaves no partial write
- **WHEN** a write transaction times out part-way through a chunked batch
- **THEN** the whole transaction is rolled back and no rows from that batch remain
