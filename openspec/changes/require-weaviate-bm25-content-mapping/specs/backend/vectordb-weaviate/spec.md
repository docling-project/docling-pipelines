# Spec Delta

## Purpose

The Weaviate provider of the `vectordb` operator. This delta adds how flow enrichment represents the content mapping that sparse (BM25) mode requires. The other requirements of the capability are defined by the change `add-weaviate-vectordb-adapter`.

## ADDED Requirements

### Requirement: Weaviate enrichment advertises the content mapping required by sparse mode
For a `vectordb` node with `provider: "weaviate"` and `add_sparse_vector` true, flow enrichment SHALL mark the content feature (the node's `doc_column`, `content` by default) as mandatory for the vector database and SHALL return a mapping for it. With `add_sparse_vector` false or absent, enrichment SHALL return feature metadata and mappings unchanged. Upstream feature metadata SHALL NOT be modified.

#### Scenario: Content marked mandatory in sparse mode
- **WHEN** a Weaviate node with `add_sparse_vector` true is enriched and the content feature is among the upstream features
- **THEN** the node's `available_features` returns that feature with `mandatory_for_vector_db` true, and the enrichment response's `available_features` returns it the same way

#### Scenario: Sparse mode off leaves feature metadata unchanged
- **WHEN** a Weaviate node with `add_sparse_vector` false or absent is enriched
- **THEN** the content feature keeps its original metadata, including any existing `mandatory_for_vector_db` value

#### Scenario: Configured content column
- **WHEN** the node's `doc_column` is `body` and `add_sparse_vector` is true
- **THEN** the `body` feature, not `content`, is marked mandatory and mapped

#### Scenario: Upstream metadata is not modified
- **WHEN** a Weaviate node with `add_sparse_vector` true is enriched
- **THEN** the feature metadata of the upstream nodes and of other nodes keeps its original `mandatory_for_vector_db` value

#### Scenario: Content feature absent
- **WHEN** `add_sparse_vector` is true and the upstream features do not include the content feature
- **THEN** no feature is marked mandatory and no content mapping is added

#### Scenario: Saved mappings without content
- **WHEN** a Weaviate node has saved mappings that contain no content mapping, `add_sparse_vector` is true, and the content feature is available
- **THEN** `feature_mappings` returns every saved mapping unchanged followed by the content feature mapped to `text`, or to the searchable content property of the selected existing collection when it has one

#### Scenario: Existing content mapping preserved
- **WHEN** saved mappings already map the content feature to another column such as `body`, or map any feature to `text` or `content`
- **THEN** `feature_mappings` is returned without an additional content mapping, and the existing target column is unchanged

#### Scenario: No duplicate on repeated enrichment
- **WHEN** enrichment is repeated with the mappings it previously returned as the saved mappings
- **THEN** the returned `feature_mappings` is identical

#### Scenario: Default mappings for an unsaved node
- **WHEN** a node has no saved mappings and `add_sparse_vector` is true
- **THEN** `feature_mappings` contains the content feature mapped to `text` exactly once, as before this requirement

#### Scenario: Run-time validation unchanged
- **WHEN** a flow with `add_sparse_vector` true and no content mapping is validated or run without enrichment, for example through the CLI or the Python API
- **THEN** validation rejects it with the existing message that a mapping for the content feature is required
