# Spec Delta

## ADDED Requirements

### Requirement: Vector index type selection in the feature mapping tearsheet
The VectorDB feature mapping tearsheet SHALL provide a control to select the Milvus `index_type` or the OpenSearch `algorithm`. Its options, label and default SHALL come from operator metadata, with static values used only as a fallback when metadata is unavailable.

#### Scenario: Select an index type for a new Milvus collection
- **WHEN** the user creates a new Milvus collection in the tearsheet
- **THEN** an index type dropdown is shown, preselected with the metadata default, and the chosen value is saved to `provider_config.index_type` without using Advanced JSON

#### Scenario: Select an algorithm for a new OpenSearch index
- **WHEN** the user creates a new OpenSearch index in the tearsheet
- **THEN** an algorithm dropdown is shown and the chosen value is saved to `provider_config.algorithm`

#### Scenario: Existing resource shows its stored index type read-only
- **WHEN** the user selects an existing collection or index whose `stored_resource_metadata.index_type` is not `null`
- **THEN** the stored value is shown in a read-only field and cannot be edited

#### Scenario: Existing resource with unknown index type
- **WHEN** the user selects an existing resource whose `stored_resource_metadata.index_type` is `null`
- **THEN** the index type is not editable and the saved `index_type` / `algorithm` value is left unchanged

#### Scenario: Metadata unavailable
- **WHEN** operator metadata carries no `valid_values` or `applicability` for the index key
- **THEN** the control uses the fallback values and the form remains usable

### Requirement: Context-aware index type options
The tearsheet SHALL offer only the index types that are valid for the current context, derived from the `applicability` metadata, and SHALL NOT offer sparse index types.

#### Scenario: Milvus Lite
- **WHEN** the Milvus `auth_type` is `lite`
- **THEN** the dropdown offers `FLAT` only and preselects it

#### Scenario: Binary-only features
- **WHEN** every mapped vector feature is of type `vector_binary` and `auth_type` is not `lite`
- **THEN** the dropdown offers `BIN_FLAT` and `BIN_IVF_FLAT` only

#### Scenario: Dense features with or without sparse
- **WHEN** a dense `vector` feature is mapped, with the sparse vector option on or off, and `auth_type` is not `lite`
- **THEN** the dropdown offers the CPU dense and GPU index types, and never `SPARSE_INVERTED_INDEX` or `SPARSE_WAND`

#### Scenario: OpenSearch algorithm follows the engine
- **WHEN** the user selects an OpenSearch engine
- **THEN** the algorithm dropdown offers only the algorithms the `applicability` map allows for that engine

#### Scenario: Engine change invalidates the algorithm
- **WHEN** the user changes the engine to one that does not allow the selected algorithm
- **THEN** the algorithm is reset to the first allowed option

#### Scenario: Explicit vector mode limits the options
- **WHEN** the saved `provider_config` sets `vector_mode` to `dense`, `gpu` or `binary`
- **THEN** the dropdown offers only the index types of that mode (`dense`: CPU dense; `gpu`: GPU; `binary`: `BIN_*`), unless that would leave no option for the mapped features, in which case the `vector_mode` filter is not applied

#### Scenario: Selection invalidated by context change
- **WHEN** a context change such as a new `auth_type` or mapped feature set makes the selected index type unavailable
- **THEN** the selection is reset to the first offered option for a new resource

### Requirement: Metric options follow the selected index family
The tearsheet SHALL derive the Milvus similarity metric options from the index family selected in the form, not from the saved provider configuration, and SHALL NOT offer `BM25` for the dense vector field.

#### Scenario: CPU dense index
- **WHEN** a CPU dense index type is selected
- **THEN** the metric dropdown offers `L2`, `IP` and `COSINE`

#### Scenario: GPU index
- **WHEN** a GPU index type is selected
- **THEN** the metric dropdown offers `L2` and `IP`

#### Scenario: Binary index
- **WHEN** a `BIN_*` index type is selected
- **THEN** the metric dropdown offers `HAMMING` and `JACCARD`

#### Scenario: Metric updates before saving
- **WHEN** the user changes the index type to a family that does not allow the current metric
- **THEN** the metric options update immediately, before the tearsheet is saved, and the metric is reset to the first valid option

#### Scenario: Sparse vector enabled with a dense feature
- **WHEN** the sparse vector option is on and the mapped features include a dense vector
- **THEN** the metric dropdown does not include `BM25`

#### Scenario: Sparse vector enabled with binary features only
- **WHEN** the sparse vector option is on and every mapped vector feature is `vector_binary`
- **THEN** the metric dropdown offers `HAMMING`, `JACCARD` and `BM25`, because no dense field is indexed with the configured metric

### Requirement: Index type is managed by the tearsheet
`index_type` and `algorithm` SHALL be managed by the tearsheet and SHALL NOT be shown in the Advanced JSON field. A value already present in a saved flow SHALL pre-populate the control with no data loss.

#### Scenario: Saved value pre-populates the control
- **WHEN** a flow saved with `index_type: "IVF_FLAT"` in Advanced JSON is opened and the tearsheet is shown
- **THEN** the dropdown shows `IVF_FLAT` and saving without changes keeps that value

#### Scenario: Saved value not in the offered options
- **WHEN** the saved `index_type` is not among the offered options for the current context
- **THEN** the control shows the value as invalid with an inline message, the value is not silently dropped, and the user must pick a valid option before saving

#### Scenario: Unrelated Advanced JSON keys preserved
- **WHEN** the tearsheet saves an index type selection
- **THEN** all other `provider_config` keys, including `index_parameters`, are preserved unless cleared by the index parameters requirement

#### Scenario: Existing flows run unchanged
- **WHEN** an existing flow that never touched the index control is loaded, saved and run
- **THEN** its saved configuration and behavior are unchanged

### Requirement: Index parameters on index type change
When the user changes the selected index type, the tearsheet SHALL clear `index_parameters` or warn that existing parameters may not apply. Editing the parameters SHALL remain in Advanced JSON.

#### Scenario: Index type changed with parameters present
- **WHEN** `index_parameters` is non-empty and the user selects a different index type
- **THEN** `index_parameters` is cleared on save, and an inline notice tells the user the parameters were reset

#### Scenario: No parameters present
- **WHEN** `index_parameters` is empty and the user changes the index type
- **THEN** no notice is shown

### Requirement: Mixed dense and binary collection note
When dense and binary vector features are mapped for a Milvus collection, the tearsheet SHALL show a note that the selected index applies to the fields it fits and the other fields use default indexes.

#### Scenario: Mixed features mapped
- **WHEN** both a `vector` and a `vector_binary` feature are mapped
- **THEN** an inline note states that the other vector field falls back to `HNSW` with `L2`, or to `BIN_FLAT` with `HAMMING`

#### Scenario: Single kind of vector feature
- **WHEN** only dense or only binary features are mapped
- **THEN** the note is not shown

### Requirement: Index type control accessibility and localization
The index type and algorithm controls SHALL be operable by keyboard, have accessible labels, and take every user-visible string from localizable message definitions.

#### Scenario: Keyboard operation
- **WHEN** the user navigates the tearsheet with the keyboard
- **THEN** the index type control can be focused, opened, navigated and selected without a pointer, and focus order matches visual order

#### Scenario: Accessible label and invalid state
- **WHEN** the control is rendered, including in the invalid or read-only state
- **THEN** it has an associated label and the invalid message is programmatically associated with the control

#### Scenario: Localized strings
- **WHEN** the tearsheet is rendered in any supported locale
- **THEN** the control label, option labels, notices and error messages come from the message catalogue

## MODIFIED Requirements

### Requirement: Milvus GPU mode similarity metric filtering
The VectorDB feature mapping tearsheet SHALL restrict the Milvus similarity metric options to `L2` and `IP` when the index family selected in the form is GPU. Before an index type is selected in the form, GPU mode SHALL be taken from the provider configuration: `vector_mode` is `gpu`, or `vector_mode` is unset and `index_type` starts with `GPU_`.

#### Scenario: GPU vector mode limits dense metric options
- **WHEN** the Milvus provider configuration has `vector_mode: "gpu"` and the mapped features are dense vectors
- **THEN** the similarity metric dropdown offers only `L2` and `IP`, and neither `COSINE` nor `BM25` is offered

#### Scenario: GPU index type implies GPU mode
- **WHEN** the Milvus provider configuration has no `vector_mode` and `index_type` is `GPU_CAGRA`
- **THEN** the similarity metric dropdown offers only `L2` and `IP`

#### Scenario: GPU index selected in the form
- **WHEN** the user selects a `GPU_*` index type in the tearsheet for a new collection
- **THEN** the similarity metric dropdown offers only `L2` and `IP` immediately, regardless of the saved provider configuration

#### Scenario: Selected metric no longer valid after GPU filtering
- **WHEN** a new collection is being created, GPU mode is active, and the current metric is `COSINE`
- **THEN** the metric is reset to the first offered option

#### Scenario: Non-GPU configuration is unchanged
- **WHEN** the Milvus provider configuration has no GPU `vector_mode` or `index_type`
- **THEN** the similarity metric options are the same as before this change, except that `BM25` is no longer offered for the dense field

#### Scenario: Binary-only features keep binary metrics
- **WHEN** GPU mode is active and only `vector_binary` features are mapped
- **THEN** the dropdown offers `HAMMING` and `JACCARD` as it does for any Milvus binary collection

#### Scenario: Mixed dense, binary and sparse features in GPU mode
- **WHEN** GPU mode is active and dense, `vector_binary` and sparse vector features are all mapped
- **THEN** the dropdown offers only `L2` and `IP`, because the metric configures the dense field
