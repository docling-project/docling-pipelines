# Tasks

## 1. Milvus Index Manager Binary Index and Metric Support

- [x] 1.1 [backend] Add binary index types (`BIN_FLAT`, `BIN_IVF_FLAT`) and binary metric types (`HAMMING`, `JACCARD`, `TANIMOTO`, `SUBSTRUCTURE`, `SUPERSTRUCTURE`) to `MilvusIndexTypes` and `MilvusMetricTypes` in `src/docpipe/core/operators/vectordb/adapters/outbound/milvus/index_manager.py` and verify type constants with unit tests in `tests/unit/operators/vectordb/test_milvus_index_manager.py`.
- [x] 1.2 [backend] Implement index validation and default parameters (`BIN_IVF_FLAT: {"nlist": 128}`) in `MilvusIndexManager` ensuring binary index types only pair with binary metrics, and verify error cases via unit tests.
- [x] 1.3 [backend] Add Milvus Lite safeguard in `MilvusIndexManager` rejecting binary index types or binary vector fields with an informative `DocpipeException`, and verify with unit tests.

## 2. Milvus Schema Creation and Batch Processing

- [x] 2.1 [backend] Update `_create_schema_fields` in `MilvusIndexManager` to support `DataType.BINARY_VECTOR` when vector type is binary, validate `dim % 8 == 0`, and verify schema construction with unit tests.
- [x] 2.2 [backend] Update `MilvusBatchProcessor.prepare_document` in `src/docpipe/core/operators/vectordb/adapters/outbound/milvus/batch_processor.py` to serialize binary vectors to raw `bytes` for PyMilvus insert calls and verify with unit tests.
- [x] 2.3 [backend] Support multi-vector schema creation (combining `DataType.FLOAT_VECTOR` and `DataType.BINARY_VECTOR`) in `MilvusIndexManager.create_collection` and verify with unit tests.

## 3. Binary Quantization in Embeddings Workflow

- [x] 3.1 [backend] Add `quantization` config parameter (`"none" | "binary" | "ubinary"`) to `EmbeddingsOperator` in `src/docpipe/core/operators/functional/embeddings/embeddings_operator.py` implementing 1-bit sign thresholding (`> 0`) and `numpy.packbits` byte conversion.
- [x] 3.2 [backend] Add unit tests in `tests/unit/operators/embeddings/` validating that quantized outputs produce byte arrays of length `dim / 8`.

## 4. Documentation, Examples and End-to-End Validation

- [x] 4.1 [backend] Update Milvus operator documentation in `docs/operators/vectordb/milvus.md` and `docs/reference/OPERATORS.md` with binary index types, metrics, quantization examples, and Milvus Lite compatibility notes.
- [x] 4.2 [backend] Add sample flow JSON `sample_flows/vectordb/milvus_binary_integration.json` demonstrating an end-to-end ingest -> extract -> chunk -> binary embedding -> Milvus binary vector storage pipeline.
- [x] 4.3 [backend] Run test suite and pre-commit checks (`pytest tests/unit/operators/vectordb/` and `pytest tests/unit/operators/embeddings/`) to verify clean passage.

## 5. Flow Validation Coverage

- [x] 5.1 [backend] Override `validate_vector_feature_types` in `OpenSearchAdapter` (`src/docpipe/core/operators/vectordb/adapters/outbound/opensearch/adapter.py`) to reject `vector_binary` features, and verify with unit tests in `tests/unit/operators/vectordb/test_opensearch_adapter.py`.
- [x] 5.2 [backend] Add a validator-level test over `sample_flows/vectordb/milvus_binary_integration.json` in `tests/unit/core/orchestrator/test_milvus_binary_flow_validation.py` (passes as shipped, fails without `quantization`).
