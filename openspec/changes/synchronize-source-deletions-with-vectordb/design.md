# Design

## Context

The [incremental-update specification](specs/backend/incremental-update/spec.md) owns this behavior end to end,
including ingestion, tracking, cleanup scheduling, and VectorDB deletion. Existing engine and VectorDB specs remain
reference contracts; this change does not introduce separate deltas for those capabilities.

See [proposal.md](proposal.md) for motivation and scope. Ingestion currently loads processing history through
`get_all_processed_docs()`, yields at most `max_files` accepted rows, and never supplies the inventory expected by
the orchestrator. Reconciliation defaults that inventory to an empty list, clears history on forced ingestion,
and purges previous soft deletions without VectorDB acknowledgment. Empty ingest output exits before downstream work.

Google Drive, Box, and Dropbox cap adapter discovery before incremental selection. Filesystem and S3 stream metadata
but can omit entries after errors; Google Drive materializes listing and document arrays. Vector adapters expose
source-ID-to-chunk lookup, but lookup failures currently return an empty mapping indistinguishable from absence.

The domain record contains a source document ID and `deleted` flag, not per-destination acknowledgments.
The Python orchestrator uses `PrefectEngine`, so its batch scheduling changes affect both execution modes.

## Goals / Non-Goals

**Goals:** Separate discovery evidence from processing rows, reuse the current document identity and storage ports,
and make cleanup durable, idempotent, and independent of batch count. Preserve data/metadata contracts and existing
retention-enabled behavior.

**Non-Goals:** See the proposal. This design does not promise constant memory for the full incremental history,
cross-flow shared-index ownership, or a consistent snapshot of a source being edited externally during discovery.
No frontend components or SCSS modules are involved.

## Decisions

### 1. Separate discovery identity from processing eligibility

Resolve retention and forced-ingest options once from effective execution configuration. When retention is disabled,
enumerate source identity metadata to completion; retain the original `max_files` limit only in processing selection.
Record presence before unchanged checks, processing filters, conversion failures, or selection-limit checks.
Use the current MD5 of the source reference consistently, not the adapter's raw ID or content-derived `doc_id_hash`.

Load historical source IDs, including pending deletions, into an unmatched-candidate set. Remove IDs as discovery
encounters them. Only the remaining historically tracked IDs are candidates for deletion; never track all unprocessed
source IDs just to compare them. Emit only selected rows in the existing PyArrow schema. Beyond the limit, avoid
creating full LangChain documents or JSON metadata solely to record presence.

Rejected: collecting all ten million IDs in `ALL_DOC_IDS` and serializing them through every batch. The candidate set
reduces duplicate inventory memory and avoids carrying unprocessed source entries through orchestration.

### 2. Make discovery completeness explicit in the source contract

Add a metadata discovery capability to the source port, with explicit completion/failure status. Adapt built-in
filesystem, S3-compatible, Google Drive, Box, Dropbox, OneDrive, and SharePoint discovery to expose it. In synchronization
mode, remove provider listing caps and stream paginated identity metadata; Google Drive must stop materializing the
entire inventory. Preserve normal limited fetching outside synchronization mode.

Keep root paths, buckets, prefixes, and configured folder IDs as the authoritative source scope. Processing-only
filters do not prove deletion: enumerate identities before those filters, or explicitly resolve existence of tracked
entries excluded by them. If the provider cannot establish presence/absence reliably, report incomplete discovery
and withhold cleanup rather than inferring deletion. Do not silently broaden scope to other roots or accounts.

Filesystem walking must surface subtree errors and failed metadata inspection. S3 must retain identity evidence when
metadata conversion fails. Verify pagination to exhaustion for every adapter, including Box folder listing.
An accessible empty root is complete; a missing/unreadable root is incomplete. Cancellation invalidates completion.
Single-file events never establish a full inventory. Custom/legacy loaders without a completeness contract continue
selecting rows but report synchronization incomplete and do not reconcile or clean up from that run.

Rejected: treating normal generator exhaustion as authoritative, because caps, ignored directory errors, or filtered
entries can produce a short inventory without proving absence.

### 3. Reconcile through the incremental application service

Keep source access in adapters and absence comparison in the incremental application layer. Introduce a typed internal
discovery result containing completeness, tracking scope, counts, missing candidates, and observed pending IDs.
Place that result in internal metadata or a shared result object consumed once by the orchestrator; do not add public
table columns or change `tuple[list[pa.Table], dict]`. Missing result means no reconciliation, not an empty source.

Extend the domain store port for explicit candidate marking, pending-record retrieval, and guarded completion. Implement
the same semantics in filesystem and Postgres adapters. Read/write/acknowledgment use `context_id` with `job_id` fallback.
The service never imports concrete adapters; operators never issue database calls directly.

For retention disabled, forced ingestion bypasses eligibility checks but does not clear historical records. Upsert
selected documents only after existing successful-processing checks. Preserve unselected history and pending deletions.
For retention enabled, keep the existing force-ingest reset policy and skip source-deletion operations.

When a previously pending ID is discovered again, cancel that deletion and invalidate its completed-processing marker
so it is eligible for regeneration, even when outside this run's selection. This conservative choice repairs output
that a prior partially successful cleanup may have removed. It does not falsely mark regeneration complete.

Rejected: clearing history and then attempting comparison, or restoring pending records directly as already processed.

### 4. Perform one cleanup phase per destination before document batches

After successful discovery/reconciliation, resolve configured VectorDB nodes from the compiled DAG. Schedule a cleanup
phase through the existing executor/operator boundary once per destination before concurrent document batches start.
The operator exposes cleanup business logic independently of normal indexing; the orchestrator owns its scheduling.
It uses existing node configuration and session context and does not require embeddings or upstream content rows.

Run the same phase when the selected table is empty; skip ordinary content-processing work. Batch execution must not
reset deletion state to zero or consume global pending records independently. Normal indexing continues to use the
existing stale-chunk cleanup for modified documents. Respect cancellation and existing failure policy, but always
record a cleanup error so the run cannot claim complete synchronization.

Keep internal discovery counts separate from actual deleted source-document counts and deleted chunk counts. Preserve
existing processing metrics; add cleanup failure/completion details through existing metadata/event reporting.

Rejected: invoking source-deletion cleanup inside every batch transform, which races acknowledgments and misses runs
with no batches.

### 5. Resolve and delete chunks with explicit success semantics

VectorDB reads pending source IDs through the incremental service and calls `VectorStorePort` for chunk resolution and
deletion. Reuse the original ingest ID already stored in OpenSearch's mapped `id` field and hashed into Milvus chunk
prefixes. Partition source IDs into bounded requests, paginate all chunk results, and bound deletion request sizes.
Ensure Milvus lookup retrieves all matching chunks, not just a default query result subset.

Provide a strict lookup operation or explicit result type for synchronization so existing best-effort stale-chunk
cleanup can retain its behavior. A lookup error cannot become `{}` success. Treat already absent chunk IDs as success
for idempotent retries. Aggregate deletion success at source-document level; a partial chunk failure leaves that
source pending. A missing index/collection counts as absent only after a successful authoritative existence check.

Rejected: passing source IDs directly to chunk-PK deletion, or acknowledging a document from aggregate success counts
that cannot prove all of its chunks were removed.

### 6. Retain tombstones until all current destinations finish

Use a conservative acknowledgment barrier without adding per-destination columns initially. All configured destinations
attempt the pending set; purge a source record only after every current destination confirms that source has no chunks.
On partial destination failure or crash, retain tombstones and repeat already successful deletions idempotently later.
With no VectorDB destinations, keep pending evidence. Changing retention to true suppresses pending cleanup as well.
Removed or reconfigured destinations are outside this change's ownership guarantee.

Serialize synchronization runs sharing one tracking context through a dedicated store-backed execution guard spanning
history snapshot, discovery, reconciliation, cleanup, and processing-metadata completion. Keep this guard distinct from
short record-operation locks, so concurrent micro-batches can save metadata normally. Use a separate FileLock for the
filesystem backend and an advisory lock on a dedicated connection for Postgres, released on cancellation/failure.
Revalidate candidate state before acknowledgment; never hard-delete a record that has since been regenerated.

Rejected: deleting pending records at the start of the next run, or using only an in-process lock when workers may
execute in different processes. Persisted per-destination acknowledgments can optimize retries later.

## Risks / Trade-offs

- Full inventory discovery on every retention-disabled run is O(source size) -> make the cost explicit in docs;
  fetch metadata only, stream provider pages, and never exceed the processing selection limit.
- Historical IDs still occupy O(tracked size) memory -> reuse existing history where possible and avoid an additional
  full source inventory; bounded-memory storage reconciliation remains separate work.
- Discovery can fail after rows are selected -> report incomplete synchronization and preserve deletion evidence;
  selected work follows existing processing failure policy, with no source cleanup on incomplete discovery.
- External source edits during enumeration are not snapshot-isolated -> document this limitation and never infer
  success from an interrupted or failed scan.
- Long context guards serialize same-context runs -> preserve correctness first; do not serialize independent contexts
  or concurrent processing batches within the same run.
- Conservative acknowledgments repeat successful requests after failures -> bounded, idempotent requests preserve
  correctness without a new destination-state schema.
- Historical versions may already contain incorrect soft deletions -> a fresh successful full scan revalidates pending
  records; do not execute an old backlog before discovery or infer proof from legacy empty inventory metadata.

## Migration Plan

1. Add source completeness and strict VectorDB cleanup contracts with filesystem/Postgres parity tests.
2. Wire conditional discovery and the guarded cleanup phase, preserving existing retention-enabled behavior.
3. Update configuration/operator documentation and verify CLI, library, and REST-job execution paths through tests.
4. No dependency or public API migration is planned. Reuse the existing deleted flag and avoid new persistent columns.
5. On rollout, require fresh complete discovery before consuming existing tombstones. On rollback, pause affected
   retention-disabled flows; the previous runtime can purge pending metadata unsafely, so changing code alone is not
   a safe retry strategy. Export pending metadata before rollback and reconcile it before resuming synchronization.
