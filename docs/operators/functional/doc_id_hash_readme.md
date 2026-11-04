# DocIdHashOperator

Generates SHA-256 hash identifiers for documents from their content column. Short name: `doc_id_hash` · Category: Functional

## Overview

The DocIdHashOperator hashes each document's content using SHA-256 and writes the result into a `doc_id_hash` column. This column is required by `EdedupOperator` (deduplication), `VectorDBOperator` (primary key), and downstream indexing operations.

> [!NOTE]
> This is an **internal operator** (`IS_OPERATOR_AVAILABLE = False`). You cannot use it directly in a flow configuration. It is invoked automatically by `ExtractOperator`, `ChunkerOperator`, and `EmbeddingsOperator` whenever a `doc_id_hash` column is needed.

## Key Features

- Deterministic SHA-256 hashing via `dpk_doc_id.DocIDTransform` — same content always produces the same hash
- Invoked automatically by upstream operators; no manual configuration needed
- Used as the primary key by `VectorDBOperator`

## Operator Configuration

This operator is **not available for direct use in flows**. It is invoked internally by other operators. If you see a `doc_id_hash` column in your output table, it was produced automatically.

If you need to customise hash column naming for a specific use case, the parameters below are available when invoking the operator programmatically:

```python
from docpipe.core.operators.functional.doc_id_hash import DocIdHashOperator

op = DocIdHashOperator(config={
    "doc_column": "content",          # column to hash
    "doc_id_hash_column": "doc_id_hash"  # output column name
})
```

## Parameters

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `doc_column` | `string` | No | `"content"` | Column containing document text to hash. |
| `doc_id_hash_column` | `string` | No | `"doc_id_hash"` | Name of the output column for the generated hash. |

## Output Columns

| Column | Type | Description |
| --- | --- | --- |
| `doc_id_hash` | `string` | Lowercase SHA-256 hex digest of the document content (via `dpk_doc_id.DocIDTransform`). 64 characters for string content; list-typed content yields a 16-character truncated digest. Size storage for up to 64 characters. Used as the primary key in vector databases. |

## Examples

This operator is invoked internally. The following operators all produce a `doc_id_hash` column automatically:

- `extract_operator` — hashes extracted text
- `chunker` — hashes each chunk
- `embeddings` — ensures hash exists before embedding

No flow configuration is needed.

## Troubleshooting

**`doc_id_hash` column missing** — ensure `ExtractOperator` or `ChunkerOperator` ran before any operator that requires it (e.g. `ededup`, `vectordb`). These operators produce the column automatically.

**Duplicate hashes** — two documents have identical content. This is expected behaviour; use `EdedupOperator` to remove duplicates.

## Sample Flow

See [`sample_flows/advanced/quality_branching_merge_pipeline.json`](../../../sample_flows/advanced/quality_branching_merge_pipeline.json) for a complete pipeline example that includes document ID hashing.
