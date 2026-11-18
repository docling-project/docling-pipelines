# Design

## Context

See `proposal.md - Why` for motivation. The implementation lives in `src/docpipe/core/operators/vectordb/vectordb_operator.py` and the vector store adapters. No production code changes in this change.

## Goals / Non-Goals

**Goals:**
- Capture the current observable behavior of `VectorDBOperator` as a versioned OpenSpec capability so later changes can express behavior changes as deltas.

**Non-Goals:**
- Modifying `VectorDBOperator` or its adapters.
- Removing or deprecating `create_index` - that is handled by `remove-vectordb-create-index-flag`, applied on top of this baseline.
- Covering internal implementation details (private helpers, adapter internals).

## Decisions

**Single capability (`backend/vectordb-operator`)**
The operator is one class with provider adapters behind a port; the spec mirrors that boundary.

**Spec describes behavior at the time of formalization**
The baseline intentionally documents `create_index` as it behaves today, so the follow-up change shows a true `MODIFIED` delta rather than a rewritten baseline.

## Risks / Trade-offs

- **Ordering**: `remove-vectordb-create-index-flag` cannot be archived until this change is archived, since its `MODIFIED` requirements must match existing ones. Mitigation: archive this change first.
