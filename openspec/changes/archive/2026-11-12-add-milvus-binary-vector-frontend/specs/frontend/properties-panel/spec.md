# Spec Delta

## MODIFIED Requirements

### Requirement: VectorDB feature mapping and backend configuration
The VectorDB custom panel SHALL support database backend selection (OpenSearch / Milvus), index/collection naming, Milvus Lite binary vector restriction warnings, similarity metric selection including binary metrics (`HAMMING`, `JACCARD`) for Milvus, and a feature mapping tearsheet that manages embeddings-to-field bindings and calls the feature enrichment endpoint.

#### Scenario: Backend selection displays relevant configuration fields
- **WHEN** the user selects "OpenSearch" or "Milvus" as the vector database provider
- **THEN** provider-specific connection and index settings are displayed

#### Scenario: Feature mapping tearsheet manages embedding field bindings
- **WHEN** the user opens the feature mapping tearsheet
- **THEN** upstream embedding features and document metadata can be mapped to vector database payload fields

#### Scenario: Binary similarity metric selection for binary embeddings
- **WHEN** the user configures a Milvus vector database with an upstream `vector_binary` feature
- **THEN** binary similarity metrics (`HAMMING`, `JACCARD`) are available in the similarity metric selection dropdown with localized descriptive labels

#### Scenario: Milvus Lite binary vector restriction warning
- **WHEN** the user selects `auth_type: "lite"` in Milvus provider configuration and an upstream node provides `vector_binary` features
- **THEN** an inline warning notification is displayed in the properties panel explaining that Milvus Lite does not support binary vectors

#### Scenario: OpenSearch binary vector restriction warning
- **WHEN** the user selects OpenSearch provider configuration and an upstream node provides `vector_binary` features
- **THEN** an inline warning notification is displayed in the properties panel explaining that OpenSearch does not support binary vectors

## ADDED Requirements

### Requirement: Embeddings quantization configuration
The Embeddings custom panel SHALL expose a `Quantization` configuration option in its Advanced section allowing users to choose between standard float embeddings (`None`) and 1-bit packed binary embeddings (`Binary`), persisting the choice as `quantization` on the node.

#### Scenario: Default quantization is None
- **WHEN** an Embeddings operator node is opened without a persisted `quantization` attribute
- **THEN** the Quantization dropdown defaults to `None` and outputs standard dense float embeddings

#### Scenario: Selecting binary quantization
- **WHEN** the user selects `Binary (1-bit packed)` in the Quantization dropdown
- **THEN** `quantization="binary"` is saved to the node configuration and the downstream `embeddings` feature is typed as `vector_binary`
