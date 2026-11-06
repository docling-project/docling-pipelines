# Proposal

## Why

Following the backend addition of Milvus binary vector support (PR #452), the frontend pipeline editor lacks UI controls to configure embedding quantization and Milvus binary similarity metrics. Users currently cannot configure 1-bit binary vector quantization on the Embeddings operator panel, cannot select binary vector similarity metrics (`HAMMING`, `JACCARD`) on the VectorDB feature mapping tearsheet, and receive false "unsupported resource" errors during flow feature enrichment when inspecting existing Milvus binary collections.

## What Changes

- **Embeddings Operator Quantization UI**: Add a `Quantization` dropdown field inside the Advanced accordion of the Embeddings operator custom panel (`Embeddings.tsx`), exposing `None` (default, float32) and `Binary (1-bit packed)` (`"binary"`).
- **Milvus Binary Vector Metrics Support**: Add `HAMMING` and `JACCARD` to the default vector similarity metrics list, message catalogs, and label mappings for Milvus collections in the VectorDB feature mapping tearsheet.
- **Contextual Similarity Metric Selection**: Dynamically adapt the similarity metric dropdown choices in the VectorDB feature mapping tearsheet based on mapped vector feature types (displaying `HAMMING` / `JACCARD` for `vector_binary` features, `L2` / `IP` / `COSINE` for dense float vectors).
- **Milvus Lite & OpenSearch Restriction Safeguards**: Display an inline warning in the VectorDB properties panel when `auth_type: "lite"` (for Milvus) or `provider: "opensearch"` is selected alongside upstream `vector_binary` features, alerting users that these configurations do not support binary vectors and directing them to switch deployments/providers or set Quantization to "None" in the upstream Embeddings operator.
- **Live Resource Enrichment for Binary Milvus Collections**: Update `MilvusResourceMetadata` backend helpers (`_collection_columns`, `_is_supported`, `_stored_metadata`, `_apply_index_info`) to extract dimensions and index metadata for `BINARY_VECTOR` fields and recognize existing binary collections as docpipe-supported.

## Non-goals

- **Client-side Vector Math or Quantization**: No embedding transformations or quantization execution occur in the browser or BFF; actual bit-packing is executed exclusively by the backend `EmbeddingsOperator`.
- **OpenSearch Binary Support**: OpenSearch does not support Milvus-style binary vector indexing and will continue to reject `vector_binary` features at flow validation.
- **Milvus Lite Engine Changes**: Milvus Lite C++ engine limitations are not altered; only frontend and enrichment guidance are provided.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `frontend/properties-panel`: Add quantization dropdown to Embeddings panel, binary similarity metrics (`HAMMING`, `JACCARD`) and contextual metric filtering to VectorDB tearsheet, and Milvus Lite & OpenSearch binary vector warning banners.
- `backend/vectordb-operator`: Update `MilvusResourceMetadata` in `enrich_flow_features` to inspect, parse, and validate collections containing `BINARY_VECTOR` fields.

## Impact

- **Layer**: Full-stack (backend `MilvusResourceMetadata` + frontend `frontend/src/components/PropertiesPanel/CustomPanels/{Embeddings,VectorDB}`).
- **Affected REST Routes & Services**: `/api/v1/flow_enrichment/enrich_flow_features` (`FlowEnrichmentService` -> `VectorDBMetadataFetcher` -> `MilvusResourceMetadata`).
- **Affected Frontend Components**:
  - `EmbeddingsPanelBody` (`frontend/src/components/PropertiesPanel/CustomPanels/Embeddings/Embeddings.tsx`, `constants.ts`, `Embeddings.messages.ts`).
  - `VectorDBPanelBody` and `VectorDBFeatureMappingTearsheet` (`frontend/src/components/PropertiesPanel/CustomPanels/VectorDB/VectorDB.tsx`, `VectorDBFeatureMappingTearsheet.tsx`, `constants.ts`, `VectorDBFeatureMappingTearsheet.messages.ts`).
- **UI Components & Carbon Tokens**: Carbon `Dropdown`, `InlineNotification`, `DefinitionTooltip`, `Accordion`, `ComboBox`, and `DataTableSkeleton`.
- **Dependencies & State**: No new package dependencies; utilizes existing Redux state slices and BFF proxy routes.
