# Proposal

## Why

In dense vector mode, default feature mappings do not explicitly target the Milvus collection's content text field, resulting in documents inserted with empty text fields even when `content` exists in the row data. Additionally, Milvus enforces a strict 65,535 UTF-8 byte limit on `VARCHAR` fields; when an over-length value is submitted, the Milvus server rejects the entire batch insertion call, causing all adjacent valid documents in that batch to fail.

## What Changes

- **New**: Automatic content field fallback for Milvus in dense mode: when no feature mapping targets the collection's content field and `content` is available for vectordb, the field is populated from the row's `content` value if it fits within the VARCHAR limit.
- **New**: Best-effort fallback omission: if unmapped content exceeds the 65,535 UTF-8 byte VARCHAR limit, the text is omitted (field left empty with a warning) so the row is still inserted with its embeddings rather than failing.
- **New**: Per-row pre-insert validation for explicitly mapped VARCHAR values: any row with an explicitly mapped VARCHAR field exceeding the 65,535 UTF-8 byte limit is isolated and rejected per-row in `create_batches()` (recorded in `failed_items` / `failed_docs`), allowing the remaining documents in the batch to be inserted successfully.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `backend/vectordb-operator`: defines the Milvus unmapped content fallback behavior and per-row rejection of oversized VARCHAR values.

## Non-goals

- Automatic text truncation for explicitly mapped VARCHAR fields (over-limit values are rejected to avoid silent data loss).
- Extending fallback behavior to OpenSearch or other vector store providers.
- Changing Milvus server-side schema limits or collection index structures.

## Impact

- **Backend only**: affects `src/docpipe/core/operators/vectordb/adapters/outbound/milvus/` (`batch_processor.py`, `adapter.py`, `index_manager.py`).
- **No breaking changes**: existing flows with explicit mappings or sparse/BM25 configurations behave identically.
- **Dependencies**: none.
