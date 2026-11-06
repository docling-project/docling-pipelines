# Proposal

## Why

`VectorDBOperator` has no formal specification in OpenSpec. The `remove-vectordb-create-index-flag` change needs a baseline `backend/vectordb-operator` capability to modify. Following standard OpenSpec practice, the existing (brownfield) behavior is formalized and archived on its own, so the behavior change is recorded as a separate, reviewable delta against it.

## What Changes

- Introduce a new `backend/vectordb-operator` capability spec describing the operator's current observable behavior, including the existing `create_index` option.
- No production code changes - this is a documentation-only formalization.

## Capabilities

### New Capabilities

- `backend/vectordb-operator`: Table and metadata contract, vector dimension auto-detection, sparse and hybrid indexing, index/collection lifecycle management, stale primary key cleanup, batch indexing with error isolation, operator metadata introspection, and vector store resource metadata for flow enrichment.

### Modified Capabilities

*(none - no existing specs to modify)*

## Impact

- Adds `openspec/specs/backend/vectordb-operator/spec.md` on archive (new file, no code touched).
- `src/docpipe/core/operators/vectordb/vectordb_operator.py` and the OpenSearch/Milvus adapters are the implementation reference.
- Must be archived before `remove-vectordb-create-index-flag`, which declares `backend/vectordb-operator` as a modified capability.
