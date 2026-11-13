# backend/flow-execution-engine Spec Delta

## ADDED Requirements

### Requirement: Soft deletion marking and post-execution cleanup lifecycle
When a pipeline runs with `retain_deleted_docs = false` and `force_ingest = false`, missing tracked documents SHALL be marked soft-deleted in the incremental metadata repository. Downstream output operators SHALL clean up these records from target stores. On successful completion, the engine SHALL purge the soft-deleted records from the repository. If downstream cleanup fails, soft-deleted marks SHALL be reverted and the job run marked `FAILED`.

#### Scenario: Missing source documents marked soft-deleted and purged on flow success
- **WHEN** an incremental flow executes with `retain_deleted_docs = false` and tracked source documents are missing from the current ingestion
- **THEN** missing documents are marked as soft-deleted, downstream output operators execute deletion cleanup, and upon successful flow completion, soft-deleted records are permanently purged from the incremental repository

#### Scenario: Downstream cleanup failure unmarks soft-deleted records
- **WHEN** downstream cleanup in an output operator fails during execution
- **THEN** soft-deleted records are reverted to non-deleted in the incremental repository and the job run fails with `FAILED` status

#### Scenario: Retain deleted docs enabled bypasses deletion sync
- **WHEN** a flow executes with `retain_deleted_docs = true`
- **THEN** missing source documents are not marked as soft-deleted and no deletion sync runs

#### Scenario: Force ingest clears incremental metadata without soft-deletion sync
- **WHEN** a flow executes with `force_ingest = true`
- **THEN** existing incremental metadata is cleared, all selected documents are ingested, and soft-deletion marking is skipped
