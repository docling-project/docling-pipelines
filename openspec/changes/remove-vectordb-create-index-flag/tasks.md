# Tasks

## 1. Backend Core Operator & Constants Update

- [x] 1.1 [backend] Remove `create_index` initialization and conditional check in `VectorDBOperator.transform()`, calling `_ensure_index_ready()` unconditionally, adding deprecation warning logger when `create_index` is present in config, and remove `CREATE_INDEX` from `get_metadata()`. Verify with `pytest tests/unit/operators/vectordb/test_vectordb_operator.py`.
- [x] 1.2 [backend] Remove `CREATE_INDEX = "create_index"` constant from `OperatorConstants.VectorDB` and clean up `config.py` environment mapping helpers. Verify constants imports and usages across codebase.

## 2. Unit and Integration Test Updates

- [x] 2.1 [backend] Add unit tests in `tests/unit/operators/vectordb/test_vectordb_operator.py` verifying collection creation when `index_exists()` returns `False`, schema validation when `index_exists()` returns `True`, and deprecation warning logging when `create_index` is supplied. Verify with `pytest tests/unit/operators/vectordb/test_vectordb_operator.py`.
- [x] 2.2 [backend] Remove `create_index` and `CREATE_INDEX` from all unit test configs (`test_vectordb_operator.py`, `test_vectordb_metrics.py`, `test_multi_model_embeddings.py`, `test_config_utils.py`). Verify with `pytest tests/unit/operators/vectordb/`.
- [x] 2.3 [backend] Update integration test files (`tests/integration/opensearch/test_opensearch_advanced.py`, `tests/integration/opensearch/test_opensearch_with_container.py`, `tests/integration/test_ingest_extract_chunk_embed_milvus_lite.py`) to remove `create_index` from test configurations. Verify syntax and static analysis.

## 3. Sample Flows & Documentation Updates

- [x] 3.1 [backend] Remove `"create_index"` parameters from all JSON flow files in `sample_flows/`. Verify valid JSON format for all modified sample flows.
- [x] 3.2 [backend] Update documentation in `docs/reference/OPERATORS.md`, `docs/operators/vectordb/opensearch.md`, `docs/operators/vectordb/milvus.md`, `docs/operators/vectordb/vectordb_readme.md`, and `docs/guides/FLOW_CONFIGURATION_GUIDE.md`. Verify documentation links and markdown formatting.

## 4. End-to-End Validation

- [x] 4.1 [backend] Run full pytest suite for VectorDB unit and integration tests and ensure no regressions. Verify with `pytest tests/unit/operators/vectordb/`.
