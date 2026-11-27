# Proposal: Fix Milvus collection loading and query error handling

## Why

The Milvus adapter issues `query` calls against collections that Milvus has not loaded, and
it converts query failures into empty results.

- A collection reopened in a new process reports `NotLoad`. Milvus rejects `query` on such a
  collection with code 101 (`call load() before search/get/query`). The adapter never calls
  `load_collection`, so these queries fail.
- `query_by_doc_names` and `get_chunk_ids_for_documents` catch every exception and return
  `[]` or `{}`. A rejected query therefore looks like a successful query that matched nothing.
- Stale-chunk cleanup and soft-delete cleanup both depend on `get_chunk_ids_for_documents`. When
  its query fails, they see "no existing chunks" and skip deletion, so stale or soft-deleted
  chunks stay in the store with no error reported.

## What Changes

- The Milvus batch processor loads a collection that is not yet loaded before running a query
  against it. A collection already in the `Loaded` state is not reloaded, and a loaded state is
  cached for the lifetime of the processor so repeated queries do not re-check it.
- When a query fails while the loaded state is cached and the collection is no longer `Loaded`
  (released, dropped, or recreated by another client), the processor clears the cached state and
  repeats the load check and the query once. Any other failure is raised without a retry.
- A collection that does not exist yet returns an empty result without querying. This keeps
  first-run cleanup working.
- Failures to load, or to query an existing collection, raise `DocpipeException` with
  `OPERATOR_EXECUTION_FAILED` and chain the original exception. They are no longer converted to
  empty results.
- Deletes and collection statistics are unchanged. Milvus accepts writes and stats on an
  unloaded collection, so forcing a load for them would add cost without fixing anything.

## Layers Affected

Backend only. The change is confined to the Milvus adapter's batch processor. No REST route,
operator contract, frontend component, or flow JSON field changes.

## Non-goals

- Changing the `VectorDBOperator` (`vectordb_operator.py`). Its existing handlers already log
  and roll back on adapter exceptions; they only ever saw an empty result before.
- Execution-status determination, `NODE_STATUS`, the document, chunk, or failed-document
  counters, `doc_hash_to_id`, pipeline status aggregation, or progress calculation.
- Collection schema or feature-mapping mismatches.
- The OpenSearch and Weaviate adapters.
- Frontend components.
- Changing how Milvus Lite is connected or how indexes are created.
- Releasing collections or managing load lifetimes beyond the processor's lifetime.
- Changing `VectorStorePort`. Its `query_by_doc_names` contract already documents `Raises: Exception: If
  query operation fails`; the Milvus adapter now honours it. `get_chunk_ids_for_documents` declares no
  `Raises` section, so the Milvus adapter raising there is a behavior difference, not a signature change.

## Impact

- `query_by_doc_names` and `get_chunk_ids_for_documents` can now raise `DocpipeException` where
  they previously returned empty results. `VectorDBOperator.query_by_doc_names` callers see this
  change. The operator's stale-chunk and soft-delete cleanup now reach their existing failure
  handling instead of silently skipping. `get_document_count` is unchanged.
- No new dependencies. `LoadState` comes from the already-pinned `pymilvus==3.0.3`.
- Milvus Lite (`auth_type: "lite"`) behavior is preserved: the same load and query calls run
  against the embedded database.
