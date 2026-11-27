# Design: Milvus collection loading and query error handling

## Context

The Milvus adapter is split across `MilvusClient` (connection), `MilvusIndexManager` (collection
lifecycle), and `MilvusBatchProcessor` (reads and writes). Queries live in the batch processor.
Probes against the pinned `pymilvus==3.0.3` and `milvus-lite==3.2.2` established the behavior
this design depends on:

| Operation on a collection reopened in a new process | Result |
|---|---|
| `get_load_state` | `NotLoad` |
| `query` | raises code 101, `call load() before search/get/query` |
| `insert`, `delete` by filter | succeed |
| `get_collection_stats` | succeeds |
| `query` on a missing collection | raises code 100 |
| `get_load_state` on a missing collection | `NotExist`, no exception |

Within one process, a collection created and indexed through the adapter is already `Loaded`.
The defect therefore appears on any run that reopens an existing collection, which is the
incremental-run case the cleanup paths exist for.

## Goals / Non-Goals

**Goals**

- Load a collection before any query against it, once per processor.
- Never convert a query or load failure into an empty result.
- Keep first-run behavior (missing collection) returning empty results.

**Non-Goals**

- Operator-level changes, counters, status, or document-set handling.
- Forcing a load for writes or stats, which Milvus accepts on an unloaded collection.

## Decisions

### Decision 1: Load inside the batch processor, not in the operator

The processor is the only object that issues `query`. Putting the load next to the query keeps
the guarantee local to the call that needs it, so no caller can skip it. The operator and the
index manager are unchanged.

### Decision 2: Check the load state, then load only when needed

`_ensure_collection_loaded` reads `get_load_state` and calls `load_collection` only when the
state is neither `Loaded` nor `NotExist`. An already loaded collection costs one state check and
no load call.

### Decision 3: Cache the loaded flag per processor

After a successful load, the processor sets `_collection_loaded`, so later queries on the same
processor skip the state check. A failed load does not set the flag, so the next query retries
the load. The processor is created per operator run and closed when the run ends, so the cached
state is not reused across runs.

The flag can still go stale inside one processor's lifetime when another client releases, drops,
or recreates the collection. Probes against Milvus v2.5.10 showed a released collection reports
`NotLoad` and rejects queries with code 101, and a dropped collection rejects them with code 100.
`_query_loaded` therefore recovers once: when a query fails on a cached flag, it re-reads the load
state, and only if the collection is no longer `Loaded` does it clear the flag and repeat the load
check and the query a single time. A dropped collection then returns the empty result for a missing
collection, a released or recreated one is loaded again. If the state is still `Loaded`, or cannot be
read, the original query error is raised unchanged, so real failures are neither retried nor hidden.

### Decision 4: Missing collections return empty without querying

`NotExist` makes `_ensure_collection_loaded` return `False`, and each query method returns its
empty value without calling `query`. First-run stale-chunk and soft-delete cleanup run before the
collection exists, so this path must stay a normal empty result.

### Decision 5: Raise `DocpipeException` using the repository convention

Failures raise `DocpipeException(message=..., status_code=500, error_code=ErrorCode.OPERATOR_EXECUTION_FAILED)`
chained with `from e`, matching the other Milvus adapter errors. The operator's existing
`except` blocks handle them: `_cleanup_stale_pks` logs a warning and proceeds, and
`_cleanup_soft_deleted_documents` rolls back the soft-delete marks and fails the node.

### Decision 6: Partial results are never returned from a failed lookup

`get_chunk_ids_for_documents` raises on the first failed per-document query instead of returning
the PKs found so far. A partial map would make stale-chunk cleanup delete only part of the stale
set without any signal.

## Layer Boundaries

Backend only. The change stays in the Milvus adapter's outbound layer:

- `batch_processor.py` (outbound adapter): `_ensure_collection_loaded`, `_query_loaded`,
  `_load_state_changed`, `query_by_doc_names`, `get_chunk_ids_for_documents`.
- `VectorDBOperator` and the port (`VectorStorePort`) are not modified. The port documents that
  `query_by_doc_names` raises on failure. The OpenSearch adapter still returns `[]` on a failed
  query and the OpenSearch and Weaviate adapters are out of scope, so providers differ until they
  are changed separately.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Stale cached load state after an external release, drop, or recreation | `_query_loaded` clears the flag and repeats the load check and query once when the collection is no longer `Loaded`; other failures raise. |
| Extra `get_load_state` round trip on the first query | One call per processor, cached afterwards. |
| Callers that did not handle exceptions now see them | Operator cleanup paths already catch and handle adapter exceptions. `VectorDBOperator.query_by_doc_names` has no production caller in `src/`; it is used by tests and `examples/`, so the new exception reaches only those callers. |
| Behavior differs between Lite and server Milvus | The same `get_load_state`, `load_collection`, and `query` calls run on both; the Lite integration tests exercise the reopen path. |
