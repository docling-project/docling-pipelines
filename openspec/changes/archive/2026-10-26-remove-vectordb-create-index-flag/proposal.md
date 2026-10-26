# Proposal

## Why

The `create_index` configuration parameter in `VectorDBOperator` exposes an internal implementation detail as a user-configurable option. Users should not need to decide whether collection or index creation occurs — the operator should handle this transparently based on whether the target collection/index exists.

Allowing users to configure this flag causes two issues:
1. Setting `create_index: false` on a new collection silently skips setup and fails during insert with cryptic errors.
2. Setting `create_index: true` on an existing collection triggers unnecessary schema validation overhead on every run.

The operator already provides `adapter.index_exists()` and `adapter.validate_existing_schema()`. Removing the flag and wiring these checks internally (create if absent, validate if present) makes vector database ingestion robust and self-healing.

## What Changes

- **BREAKING**: Remove the `create_index` user configuration parameter from `VectorDBOperator` and its metadata parameter definition.
- Remove `OperatorConstants.VectorDB.CREATE_INDEX` from operator constants and environment config builders.
- Update `VectorDBOperator.transform()` to unconditionally inspect `adapter.index_exists()`:
  - If the index/collection does not exist, call `adapter.create_index(dimension_mapping=...)`.
  - If the index/collection exists, call `adapter.validate_existing_schema(dimension_mapping=...)`.
- Emit a deprecation warning logger when legacy flow configurations pass `create_index`.
- Preserve adapter `create_index()` method signatures across Milvus and OpenSearch adapters.
- Update all sample flow definitions, documentation, and test fixtures to remove `create_index`.

## Non-goals

- Altering the underlying vector database adapter indexing, querying, or batch insertion logic.
- Changing `adapter.create_index()` or `adapter.validate_existing_schema()` method signatures or behavior.
- Frontend UI canvas redesign (only parameter metadata reflecting removal is affected).

## Capabilities

### New Capabilities
- None

### Modified Capabilities
- `backend/vectordb-operator`: Remove user-configurable `create_index` parameter, making index/collection creation and schema validation automatic and internal.

## Impact

- **Affected Layer**: Backend-only.
- **Affected Operators & Files**:
  - `src/docpipe/core/operators/vectordb/vectordb_operator.py`
  - `src/docpipe/core/constants/operator_constants.py`
  - `src/docpipe/utils/infrastructure/config.py`
- **Affected Endpoints**: `GET /api/v1/operators/metadata` (no longer returns `create_index` in `vectordb` attributes).
- **Documentation & Flows**:
  - `docs/reference/OPERATORS.md`, `docs/operators/vectordb/*`
  - `sample_flows/**/*.json`
- **Unit and Integration Tests**:
  - `tests/unit/operators/vectordb/*`
  - `tests/integration/opensearch/*`, `tests/integration/test_ingest_extract_chunk_embed_milvus_lite.py`
