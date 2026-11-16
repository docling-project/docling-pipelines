# Spec Delta

## ADDED Requirements

### Requirement: Milvus GPU mode similarity metric filtering
The VectorDB feature mapping tearsheet SHALL restrict the Milvus similarity metric options to `L2` and `IP` when the provider configuration selects GPU mode, that is `vector_mode` is `gpu`, or `vector_mode` is unset and `index_type` starts with `GPU_`.

#### Scenario: GPU vector mode limits dense metric options
- **WHEN** the Milvus provider configuration has `vector_mode: "gpu"` and the mapped features are dense vectors
- **THEN** the similarity metric dropdown offers only `L2` and `IP`, and neither `COSINE` nor `BM25` is offered

#### Scenario: GPU index type implies GPU mode
- **WHEN** the Milvus provider configuration has no `vector_mode` and `index_type` is `GPU_CAGRA`
- **THEN** the similarity metric dropdown offers only `L2` and `IP`

#### Scenario: Selected metric no longer valid after GPU filtering
- **WHEN** a new collection is being created, GPU mode is active, and the current metric is `COSINE`
- **THEN** the metric is reset to the first offered option

#### Scenario: Non-GPU configuration is unchanged
- **WHEN** the Milvus provider configuration has no GPU `vector_mode` or `index_type`
- **THEN** the similarity metric options are the same as before this change

#### Scenario: Binary-only features keep binary metrics
- **WHEN** GPU mode is active and only `vector_binary` features are mapped
- **THEN** the dropdown offers `HAMMING` and `JACCARD` as it does for any Milvus binary collection

#### Scenario: Mixed dense, binary and sparse features in GPU mode
- **WHEN** GPU mode is active and dense, `vector_binary` and sparse vector features are all mapped
- **THEN** the dropdown offers only `L2` and `IP`, because the metric configures the dense field
