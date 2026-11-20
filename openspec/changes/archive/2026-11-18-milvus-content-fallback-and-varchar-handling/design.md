# Design

## Context

See `proposal.md` for background and motivation.

Milvus collections declare a content field (default `text`) of type `VARCHAR(65535)`. In dense mode, default feature mappings only map embedding vectors, leaving the content text unmapped. When inserting rows, Milvus evaluates `VARCHAR` length in UTF-8 bytes and rejects the entire batch insertion request if any value exceeds 65,535 bytes.

## Goals / Non-Goals

**Goals:**
- Automatically populate the collection's content field from row `content` in dense mode when unmapped.
- Measure `VARCHAR` lengths strictly in UTF-8 bytes (`len(val.encode("utf-8"))`).
- Isolate oversized rows during batch construction in `create_batches()` so that valid documents in the same batch are preserved.
- Report rejected rows in standard failed document metadata (`failed_items`) with clear diagnostic messages.

**Non-Goals:**
- Silent text truncation for explicitly mapped values.
- Client-side modifications to Milvus server-side data types or limits.

## Decisions

### Decision 1: Best-effort unmapped fallback vs strict per-row rejection
- **Approach**: For the automatic unmapped content fallback, if the text exceeds 65,535 UTF-8 bytes, the text is omitted (field left empty with a warning) and the row is still batched with its vector embeddings. For explicitly mapped `VARCHAR` features, over-length values cause that specific row to be rejected and reported in `failed_items`.
- **Rationale**: The unmapped fallback is a convenience feature; omitting oversized text avoids failing dense vectors that would otherwise insert cleanly. Explicit mappings represent an intentional schema commitment where data loss should not be silently masked.

### Decision 2: UTF-8 byte measurement for VARCHAR fields
- **Approach**: Check `len(value.encode("utf-8"))` rather than `len(value)`.
- **Rationale**: Multi-byte UTF-8 sequences (e.g. CJK, emoji) consume 3–4 bytes per character. Milvus enforces the 65,535 limit on byte length; measuring character count would allow over-length multi-byte strings to reach the server and crash the batch.

### Decision 3: Pre-insert isolation in `create_batches()`
- **Approach**: Identify oversized `VARCHAR` values in `create_batches()` before grouping documents into batch lists. Return `tuple[list[list[dict]], list[dict]]` from `create_batches()`.
- **Rationale**: Isolating invalid rows before calling `client.insert()` prevents one corrupted or oversized row from aborting the insertion of up to 100 valid documents in the batch.

## Risks / Trade-offs

- **[Risk]** Unmapped content fallback in dense mode might omit text for large unchunked documents without failing the node.
  → *Mitigation*: Log a clear `logger.warning` identifying the document and recommending a `chunker` node before `vectordb`.
- **[Risk]** UTF-8 byte encoding check overhead on every VARCHAR string.
  → *Mitigation*: The check is only applied to fields resolved as `VARCHAR` in the schema (`_varchar_field_names`), which is a small frozenset resolved once during processor initialization.
