# Tasks

## 1. Milvus Batch Processor and Content Fallback

- [x] 1.1 [backend] Implement `_fill_unmapped_content_field()` in `MilvusBatchProcessor` to write chunk text to the collection content field in dense mode when unmapped and within limit, and omit with warning when over limit. Verify with `test_milvus_batch_processor.py::TestUnmappedContentFallback`.
- [x] 1.2 [backend] Implement `_find_oversized_varchar_value()`, `_resolve_varchar_field_names()`, and `_utf8_length()` to measure VARCHAR values by UTF-8 byte length against `VARCHAR_MAX_LENGTH` (65,535 bytes). Verify with `test_milvus_batch_processor.py::TestVarcharLengthLimit`.
- [x] 1.3 [backend] Update `create_batches()` in `MilvusBatchProcessor` to reject oversized explicitly mapped VARCHAR rows per-row, return `(batches, failed_items)`, and merge them in `MilvusAdapter.index_documents()`. Verify with `test_milvus_adapter.py::TestMilvusAdapterIndexDocuments`.

## 2. Documentation and Verification

- [x] 2.1 [backend] Document the unmapped content fallback, dense mode behavior, and VARCHAR limit handling in `docs/operators/vectordb/milvus.md`. Verify documentation links and syntax.
- [x] 2.2 [backend] Run all Milvus and vectordb unit tests (`pytest tests/unit/operators/vectordb/`) to verify all scenarios pass.
