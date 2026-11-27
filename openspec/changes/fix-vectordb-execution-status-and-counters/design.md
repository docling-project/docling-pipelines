# Design

## Context

See [proposal.md](proposal.md) for motivation and scope. The requirement change is in
[specs/backend/vectordb-operator/spec.md](specs/backend/vectordb-operator/spec.md).

`VectorDBOperator._index_and_record_results` calls `adapter.index_documents(documents)`, which returns
`(success_count, failed_chunks)`. Each failed chunk is `{"index": {"_id": <chunk pk>, "error": {...}}}` for every
adapter. `chunk_id_to_doc_id` maps a chunk pk to its parent `doc_id_hash`; non-chunked rows use the `doc_id_hash` as the
pk, so a missing key falls back to the failed `_id` itself.

## Decisions

**D1. Reuse `OperatorUtils.determine_execution_status()` rather than add a status mechanism.**
It already encodes `failed and none processed -> Failed`, `failed -> CompletedWithErrors`, `skipped -> CompletedWithWarnings`,
else `Completed`, and is used by the ingest, extract, classifier and storage-output operators. The call is made at the end
of the success path of `_index_and_record_results`, once `processed_docs` is known. Failure paths that already set
`Failed` explicitly (index creation, dimension detection, adapter exception) are unchanged.

**D2. Resolve the document identity with the existing `doc_hash_to_id` map.**
Failed chunks are collected as `doc_id_hash` values (the key space of `chunk_id_to_doc_id`) and translated with
`doc_hash_to_id.get(hash, hash)` only when recording the failure. Names use `doc_hash_to_name` keyed by the hash. This
mirrors the existing whole-batch failure path, so a document has one identity across all failure paths and matches the
`id` column the executor uses to derive `docs_completed`.

**D3. `processed_docs = documents in scope - failed - skipped`.**
Failed documents are recorded once per unique document (a set of hashes), so the subtraction cannot double count, and the
three counters sum to the documents in scope. Subtracting skipped rows (rows with an empty document ID) is required so a
skipped row is not reported as processed; previously only failures were subtracted. The aggregation layer
(`aggregate_batch_node_stats`) reports `Processed Docs` as completed + failed + skipped, derived from document-id lists,
so the operator-level `processed_docs` value is the count of successfully processed documents and does not conflict.

**D4. Job status needs no change.**
`OperatorUtils.determine_final_job_status` takes the most severe node status, so a node reporting `Failed` yields a
`Failed` job and `CompletedWithErrors` yields `CompletedWithErrors`. The orchestrator is left untouched.

## Risks

- Flows that previously ended `Completed` despite chunk failures now end `CompletedWithErrors` or `Failed`. This is the
  intended correction.
- A failed chunk whose `_id` is not a known chunk pk or document hash is recorded under that raw value (unchanged
  behaviour); it still counts the node as having a failure.
