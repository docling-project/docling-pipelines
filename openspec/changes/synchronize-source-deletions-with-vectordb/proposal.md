# Proposal

## Why

`retain_deleted_docs: false` currently reconciles an absent source inventory as an empty list and does not reliably
remove missing documents from VectorDB. Users need source deletion synchronization while retaining `max_files` as
the limit on documents processed per run, including forced re-ingestion and micro-batching.

## What Changes

- With retention disabled, enumerate the complete source metadata inventory, select at most `max_files` eligible
  documents, and mark missing tracked documents soft-deleted only after successful complete discovery.
- With retention enabled, preserve existing limited ingestion and perform no source-deletion cleanup.
- Honor deletion synchronization with `force_ingest: true`; preserve comparison history and pending deletions while
  bypassing incremental eligibility checks for selected documents.
- Remove provider discovery caps in synchronization mode and distinguish complete discovery from partial results,
  filters, single-file events, and enumeration failures.
- Resolve pending source IDs to all stored chunk IDs in OpenSearch and Milvus, with retry-safe acknowledgment.
- Schedule cleanup once per VectorDB destination per run, including runs with no selected documents, without
  duplicating cleanup across concurrent processing batches.
- Document the discovery cost, four flag combinations, supported source scope, and cleanup failure behavior.

## Capabilities

### New Capabilities

- `backend/incremental-update`: Incremental processing and bounded selection, conditional full source discovery,
  forced reprocessing, source-deletion tracking, VectorDB cleanup scheduling, and retry-safe acknowledgment.

### Modified Capabilities

None. Incremental-update behavior is owned by the new capability, including its ingestion, orchestration,
and VectorDB integration. Existing engine and VectorDB specs remain baseline contracts.

## Impact

Backend-only behavior change. Affected components are `IngestSourceOperator`, source ports/adapters, incremental
metadata application services and filesystem/Postgres adapters, `AbstractOrchestrator`, `PrefectEngine`, and
`VectorDBOperator` with its OpenSearch/Milvus ports and adapters. The Python orchestrator also uses this flow engine.
Existing CLI, library, and REST job execution inherit the behavior; no REST routes or DTO schemas are added.
No frontend, `/ui` routing, BFF, Redux, or dependency changes are planned. Backend default retention remains `true`.

## Non-goals

- Deletion synchronization for document sets or other output types.
- Changing frontend defaults or redesigning flow run properties.
- Fixing existing provider discovery caps when retention is enabled.
- Persistent traversal cursors, source change feeds, scheduled reconciliation, or bounded-memory redesign of the
  existing full incremental-history dictionary.
- Automatic cleanup of destinations removed from a flow, cross-flow shared-index ownership, or source snapshot
  isolation during concurrent external edits.
- Implementing the change as part of this proposal.
