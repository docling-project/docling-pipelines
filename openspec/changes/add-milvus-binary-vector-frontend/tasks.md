# Tasks

## 1. Backend Milvus Resource Metadata & Flow Enrichment

- [ ] 1.1 [backend] Update `MilvusResourceMetadata._collection_columns` and `_apply_index_info` in `src/docpipe/core/operators/vectordb/adapters/outbound/milvus/resource_metadata.py` to extract bit dimension and `index_info` (metric type and index type) for `BINARY_VECTOR` fields; verify with unit test assertions in `tests/unit/operators/vectordb/test_metadata_fetcher.py`.
- [ ] 1.2 [backend] Update `MilvusResourceMetadata._is_supported` and `_stored_metadata` to support `BINARY_VECTOR` collections without requiring `FLOAT_VECTOR` and extract binary similarity metrics (`HAMMING`, `JACCARD`); verify unit tests pass with `uv run pytest tests/unit/operators/vectordb/test_metadata_fetcher.py`.
- [ ] 1.3 [backend] Verify `MilvusResourceMetadata.fetch` gracefully handles unreachable vector stores and connection exceptions by returning `empty_result()` without raising unhandled exceptions; verify with unit tests in `tests/unit/operators/vectordb/test_metadata_fetcher.py`.

## 2. Frontend Embeddings Operator Quantization UI

- [ ] 2.1 [frontend] Add `QUANTIZATION` attribute constant and defaults in `frontend/src/components/PropertiesPanel/CustomPanels/Embeddings/constants.ts` and i18n messages in `Embeddings.messages.ts`.
- [ ] 2.2 [frontend] Add Quantization `Dropdown` to the Advanced accordion in `frontend/src/components/PropertiesPanel/CustomPanels/Embeddings/Embeddings.tsx`, ensuring it renders `None` when `quantization` is undefined and persists `"binary"` on selection; verify rendering and state persistence with unit tests in `frontend/tests/unit/components/PropertiesPanel/CustomPanels/Embeddings/`.

## 3. Frontend VectorDB Properties Panel & Tearsheet Enhancements

- [ ] 3.1 [frontend] Add `HAMMING` and `JACCARD` to `DEFAULT_METRIC_TYPE_VALUES` in `frontend/src/components/PropertiesPanel/CustomPanels/VectorDB/constants.ts` and label messages in `VectorDBFeatureMappingTearsheet.messages.ts`.
- [ ] 3.2 [frontend] Update `VectorDBFeatureMappingTearsheet.tsx` with `similarityMetricLabels` mappings for `HAMMING` and `JACCARD`, implement contextual metric filtering based on `vector_binary` feature presence, and support union metric lists for multi-vector/hybrid collections; verify with unit tests in `frontend/tests/unit/components/PropertiesPanel/CustomPanels/VectorDB/VectorDBFeatureMappingTearsheet.test.tsx`.
- [ ] 3.3 [frontend] Add Milvus Lite binary vector restriction warning `InlineNotification` to `frontend/src/components/PropertiesPanel/CustomPanels/VectorDB/VectorDB.tsx` and verify with unit tests in `frontend/tests/unit/components/PropertiesPanel/CustomPanels/VectorDB/`.

## 4. Full-stack Verification & Quality Checks

- [ ] 4.1 [both] Run backend code formatting and type checks (`uv run ruff check .` and `uv run mypy .`) and all vector DB unit tests (`uv run pytest tests/unit/operators/vectordb/`).
- [ ] 4.2 [frontend] Run frontend linting (`npm run lint`), build (`npm run build`), and component unit tests (`npm test`).
