# Proposal

## Why

When some or all chunks fail to index, the `vectordb` operator still reports `node_status = Completed`, because
`_index_and_record_results` never updates the status it initialised to `Completed`. A node whose every chunk was rejected
therefore shows as successful, and the job status derived from node statuses hides the failure.

The same path also records failed documents under their `doc_id_hash` instead of the document `id`. Everywhere else
(`_ensure_index_ready`, the whole-batch failure path, and the executor's `docs_completed` calculation) a document is
identified by its `id`, falling back to `doc_id_hash` only when `id` is missing or empty. With the mismatch, a failed
document is not excluded from the completed documents, so it is counted as both failed and completed.

## What Changes

- After chunk-level indexing results are known, set `node_status` with the existing
  `OperatorUtils.determine_execution_status()`, the same call used by the ingest, extract, classifier and storage-output
  operators:
  - every document indexed: `Completed`
  - some documents failed: `CompletedWithErrors`
  - no document indexed and at least one failed: `Failed`
- Record documents that had failed chunks under their document identity (`doc_hash_to_id`, the `id` column, else
  `doc_id_hash`) and use the matching name, so they are excluded from the completed documents.
- Compute `processed_docs` as documents in scope minus failed and skipped documents, so completed, failed and skipped
  counts add up to the documents in scope and a skipped row is not also reported as processed.

## Non-Goals

- Milvus collection loading, swallowed Milvus query exceptions, collection schema or feature-mapping mismatches.
- Progress-percentage clamping in shared aggregation code.
- Orchestrator execution behaviour; job status continues to be derived from node statuses unchanged.
- Frontend changes.

## Capabilities

### Modified Capabilities
- `backend/vectordb-operator`: the "Batch document indexing and error isolation" requirement now defines the document
  identity used for failed chunks, and a new "Indexing outcome status and document counters" requirement defines the
  node status and counters produced by chunk-level indexing outcomes.

## Impact

- Code: `VectorDBOperator._index_and_record_results` in
  `src/docpipe/core/operators/vectordb/vectordb_operator.py`. No adapter, port or schema change; the fix reads only the
  failed-item shape (`{"index": {"_id": ...}}`) that the OpenSearch, Milvus and Weaviate adapters already return.
- Tests: new `TestIndexingOutcomeStatusAndCounters` in `tests/unit/operators/vectordb/test_vectordb_operator.py`.
- Behaviour: a run with chunk failures now ends `CompletedWithErrors` or `Failed` instead of `Completed`, and the job
  status follows through the existing node-status aggregation.
