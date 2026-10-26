# Design

## Context

`VectorDBOperator` handles vector ingestion into OpenSearch and Milvus. Currently, it inspects `self.create_index` (derived from configuration). If true, it calls `_ensure_index_ready()`, which probes `adapter.index_exists()` and either creates the index or validates the existing schema. If false, `_ensure_index_ready()` is bypassed entirely, which causes runtime insertion crashes when an index has not yet been initialized.

## Goals / Non-Goals

**Goals:**
- Eliminate user-facing `create_index` flag from `VectorDBOperator` and its metadata parameter schema.
- Unconditionally invoke `_ensure_index_ready()` inside `transform()` before document batching and insertion.
- Emit a warning log when legacy configs contain `create_index`.
- Maintain existing adapter contracts (`OpenSearchAdapter`, `MilvusAdapter`, and `VectorStorePort`).
- Update sample flows, documentation, and test fixtures to remove `create_index`.

**Non-Goals:**
- Modifying underlying vector adapter implementations (`index_documents`, `upsert`, query logic).
- Changing database schema representations.

## Decisions

### 1. Unconditional index readiness check in `transform()`
- **Decision**: In `VectorDBOperator.transform()`, invoke `self._ensure_index_ready(...)` directly without checking any configuration flags.
- **Rationale**: The vector adapter already knows how to test if the index/collection exists via `adapter.index_exists()`. If absent, it creates it with detected dimensions; if present, it validates schema compatibility.
- **Alternatives Considered**: Keeping an optional `auto_create_index` flag. Rejected because index readiness is an invariant requirement for indexing, not an optional preference.

### 2. Removal of `CREATE_INDEX` from `OperatorConstants.VectorDB` and Config Utils
- **Decision**: Remove `OperatorConstants.VectorDB.CREATE_INDEX = "create_index"`. Clean up `get_opensearch_config()` and `get_milvus_config()` in `src/docpipe/utils/infrastructure/config.py`.
- **Rationale**: Eliminates dead configuration constants and prevents invalid environment variable mappings from populating operator config.

### 3. Graceful compatibility for legacy flow configs with warning logging
- **Decision**: When `create_index` is present in the configuration dictionary passed to `VectorDBOperator.__init__()`, emit a warning logger: `logger.warning("The 'create_index' configuration parameter is deprecated and will be ignored. Index lifecycle is now handled automatically.", extra=self.common_log_arguments)` and proceed normally.
- **Rationale**: Prevents breaking existing legacy pipeline JSON files stored externally while explicitly alerting users and maintainers that the setting has no effect and should be removed.

## Risks / Trade-offs

- **[Risk]** Existing flows passing `create_index: false` with custom index structures might trigger schema validation errors.
  - **Mitigation**: `validate_existing_schema()` validates only that mapped vector fields match detected dimensions and primary keys exist, which is required for correct insertion anyway.

## Migration Plan

1. Brownfield base specification for `backend/vectordb-operator` is formalized and archived separately (`formalize-vectordb-operator-spec`).
2. Remove `create_index` from operator configuration parsing and `get_metadata()`, adding deprecation warning log when present.
3. Remove `CREATE_INDEX` constant.
4. Clean up sample flows, documentation, and tests.
5. Verify with unit and integration tests.
