# Design

## Context

See `proposal.md` for background and motivation. PR #452 added backend binary vector support in Milvus, including `DataType.BINARY_VECTOR`, binary similarity metrics (`HAMMING`, `JACCARD`), embedding quantization in `EmbeddingsOperator` (`quantization: "binary"`), and feature propagation as `vector_binary`. The frontend properties panels and the backend flow enrichment metadata fetcher must now be updated to seamlessly expose, validate, and test these capabilities.

## Goals / Non-Goals

**Goals:**
- Provide a clean `Quantization` selection in the `Embeddings` operator panel to generate binary vectors, defaulting to `None` when undefined.
- Support `HAMMING` and `JACCARD` binary vector metrics in the `VectorDB` feature mapping tearsheet when Milvus is selected.
- Provide contextual metric filtering in the tearsheet based on whether incoming/mapped features are binary, dense float, or a hybrid/multi-vector combination.
- Show actionable warnings when Milvus Lite (`auth_type: "lite"`) or OpenSearch (`provider: "opensearch"`) is configured with upstream binary vectors.
- Ensure `MilvusResourceMetadata` in `enrich_flow_features` correctly handles binary vector collections (dimension bit-count detection, support check, index info extraction, and graceful fallback on connection failures).

**Non-Goals:**
- Client-side vector quantization or index calculation in TypeScript.
- Supporting binary vectors in OpenSearch (rejected by backend flow validation).
- Altering the core canvas graph rendering or edge types.

## Component Hierarchy & Carbon Primitives

```
PropertiesPanel/CustomPanels/
│
├── Embeddings/
│   └── EmbeddingsPanelBody (Embeddings.tsx)
│       └── Accordion (Carbon <Accordion>)
│           └── AccordionItem "Advanced" (Carbon <AccordionItem>)
│               ├── NumberInput "Overlap Ratio" (Carbon <NumberInput>)
│               ├── NumberInput "Token Limit" (Carbon <NumberInput>)
│               └── Dropdown "Quantization" (Carbon <Dropdown>)
│                   ├── "None" (persists undefined or "none", default state)
│                   └── "Binary (1-bit packed)" (persists "binary")
│
└── VectorDB/
    ├── VectorDBPanelBody (VectorDB.tsx)
    │   ├── InlineNotification (Carbon <InlineNotification>) [Milvus Lite / OpenSearch + vector_binary warning]
    │   ├── Connection & Settings Accordions
    │   └── Summary Table & "Configure Feature Mappings" Button
    │
    └── VectorDBFeatureMappingTearsheet (VectorDBFeatureMappingTearsheet.tsx)
        ├── Tearsheet (Carbon <Tearsheet>)
        ├── ComboBox "Resource Name" (Carbon <ComboBox>)
        ├── Dropdown "Metric type" (Carbon <Dropdown>)
        │   ├── Dense vectors: "L2", "Cosine", "Inner Product"
        │   ├── Binary vectors: "Hamming distance", "Jaccard distance"
        │   └── Multi-vector / Hybrid: Union of compatible metrics
        ├── Checkbox "Sparse Vector (BM25)" (Carbon <Checkbox>)
        └── VectorDBFeatureMappingTable (Carbon <DataTable>)
```

## Decisions & Technical Choices

### 1. Embeddings Panel Quantization UI
- **Decision**: Expose `Quantization` inside the existing "Advanced" accordion as a `Dropdown`. Options: `None` (`"none"`) and `Binary (1-bit packed)` (`"binary"`). When the property value is undefined or unpersisted, initialize the selected option to `None`.
- **Rationale**: Keeps the primary provider configuration clean and matches the layout of `overlap_ratio` and `token_limit`. `binary` and `ubinary` are functionally identical in backend numpy bit-packing, so exposing a clean binary option avoids user confusion.
- **Alternatives Considered**: Radio button group (takes more vertical space in narrow property flyouts).

### 2. Contextual Similarity Metric Selection & Multi-Vector Handling
- **Decision**: In `VectorDBFeatureMappingTearsheet`, dynamically determine `vectorSimilarityOptions` for Milvus based on the presence of `vector_binary` features in `available_features` or `feature_mappings`:
  - When only binary vector features are detected/mapped: offer `HAMMING` and `JACCARD` with descriptive labels (`"Hamming distance"`, `"Jaccard distance"`).
  - When only dense float features are mapped: offer `L2`, `IP`, `COSINE`.
  - When both (multi-vector / hybrid collection) or neither are mapped: offer the complete union of metrics (`L2`, `IP`, `COSINE`, `HAMMING`, `JACCARD`, `BM25`).
- **Rationale**: Prevents users from selecting invalid metric combinations (such as `COSINE` on a binary vector or `HAMMING` on a dense float vector) at creation time before backend validation fails.
- **Alternatives Considered**: Showing all metrics unfiltered in the dropdown and relying solely on backend save validation. Filtered lists provide immediate visual feedback.

### 3. Milvus Lite & OpenSearch Restriction Warnings
- **Decision**: In `VectorDBPanelBody`, detect when upstream input features include `type === 'vector_binary'` and:
  - For Milvus (`provider === 'milvus'` and `milvusAuthType === 'lite'`): display an `InlineNotification` (warning kind, lowContrast) explaining that Milvus Lite does not support binary vectors and advising standalone/grpc/uri or setting Quantization to "None".
  - For OpenSearch (`provider === 'opensearch'`): display an `InlineNotification` (warning kind, lowContrast) explaining that OpenSearch does not support binary vectors and advising using a supported provider (e.g. Milvus) or setting Quantization to "None".
- **Rationale**: Immediate canvas-level feedback prevents runtime pipeline execution failures and backend validation errors before attempting to save or run.

### 4. Backend `MilvusResourceMetadata` Flow Enrichment & Error Fallback
- **Decision**: Update `_collection_columns`, `_is_supported`, `_stored_metadata`, and `_apply_index_info` in `MilvusResourceMetadata` to handle `DataType.BINARY_VECTOR` alongside `FLOAT_VECTOR`. If the Milvus connection fails or the vector store is unreachable, return the standard five-key empty fallback dictionary (`empty_result()`) without throwing an unhandled exception.
- **Rationale**:
  - `_collection_columns`: Extract `dimension` (bit count) and `index_info` (index type and metric type) for `BINARY_VECTOR` fields.
  - `_is_supported`: Check for `FLOAT_VECTOR` or `BINARY_VECTOR` with an index, preventing false "unsupported resource" rejections for pure binary collections.
  - `_stored_metadata`: Return `vector_similarity` and `dimension_size` from `BINARY_VECTOR` fields when present.
  - Connection/error fallback: Ensures pipeline canvas feature enrichment degrades gracefully when offline or during transient network errors.

## Interaction & State Mapping

| User Action | Frontend Handler | Target Controller / State / API |
|---|---|---|
| Select Quantization in Embeddings | `handleQuantizationChange` | `controller.updatePropertyValue({ name: 'quantization' }, value)` |
| Change Auth Type in Milvus | `updateMilvusAuthField` | `controller.updatePropertyValue({ name: 'provider_config' }, nextConfig)` |
| Open Feature Mapping Tearsheet | `handleOpenTearsheet` | Calls `enrichFlowFeaturesForNode(...)` via BFF `/api/v1/flow_enrichment/enrich_flow_features` |
| Select Binary Metric in Tearsheet | `setSimilarityMetric` | Local tearsheet state -> saved in `provider_config.metric_type` on tearsheet save |

## Risks / Trade-offs

- **[Risk]** Existing custom flows might contain legacy metric names.
  - *Mitigation*: Fallback label mappings in `similarityMetricLabels` map `k -> similarityMetricLabels[k] ?? k` so raw values remain readable.
- **[Risk]** Unreachable vector store during feature enrichment.
  - *Mitigation*: `MilvusResourceMetadata.fetch()` catches exceptions and returns `empty_result()`, preserving UI responsiveness.
- **[Risk]** Multi-vector collections with both dense and binary embeddings.
  - *Mitigation*: Backend defaults the non-primary index automatically; frontend tearsheet allows full feature mapping and displays the union of available metrics if both vector types exist.
