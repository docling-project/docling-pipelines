# Spec Delta

## ADDED Requirements

### Requirement: Feature propagation behavior is declared by each operator
Feature propagation SHALL be operator-agnostic: the engine SHALL derive each node's feature set from the operator's declared output features and from propagation behavior the operator itself declares, never from operator-name checks in the engine. An operator that declares no propagation behavior SHALL pass its input features through and add its declared output features.

#### Scenario: Operator without propagation behavior
- **WHEN** a node's operator declares output features but no propagation behavior
- **THEN** the node's available features are its input features plus the operator's declared output features

#### Scenario: New operator needs no engine change
- **WHEN** an operator (built-in or enabled custom) declares propagation behavior that removes a feature it declares
- **THEN** that feature is absent from the node's available features without any change to the propagation engine

#### Scenario: Unknown operator name
- **WHEN** a node references an operator that is not registered
- **THEN** propagation adds no operator-declared features and applies no operator-specific behavior, and flow validation reports the unknown operator as it does today

### Requirement: Untrusted operators are never run during propagation
Feature propagation SHALL NOT import or instantiate an untrusted custom operator. An untrusted operator SHALL propagate features using only its statically declared metadata.

#### Scenario: Untrusted custom operator in a flow
- **WHEN** a flow containing an untrusted custom operator is validated or enriched
- **THEN** the operator's source file is not imported and propagation uses its static metadata only

### Requirement: Extract entity features follow entity extraction mode
For an `extract_operator` node, propagation SHALL include the `entities` and `document_type` features only when `entity_extraction.provider` is set to a value other than the none mode, and SHALL omit them otherwise.

#### Scenario: Entity extraction disabled
- **WHEN** an `extract_operator` node has no `entity_extraction` config or its provider is the none mode
- **THEN** `entities` and `document_type` are not available downstream

#### Scenario: Entity extraction enabled
- **WHEN** an `extract_operator` node has `entity_extraction.provider` set to a real provider
- **THEN** `entities` (type `list`) and `document_type` (type `string`, available for filtering) are available downstream

### Requirement: Embeddings quantization determines the embeddings feature type
For an `embeddings` node, propagation SHALL type the embeddings feature `vector_binary` when `quantization` is `binary` or `ubinary` (case-insensitive) and keep a dense `vector` type otherwise. A downstream node that declares a plain `vector` input SHALL NOT replace an upstream `vector_binary` type. The node's `model_id`, when set, SHALL be published as the flow's `embeddings_model_id` global parameter.

#### Scenario: Binary quantization
- **WHEN** an `embeddings` node sets `quantization` to `binary` or `ubinary`
- **THEN** the embeddings feature has type `vector_binary` and a binary-vector description

#### Scenario: No quantization
- **WHEN** an `embeddings` node sets no quantization or `none`
- **THEN** the embeddings feature keeps the dense vector type and description

#### Scenario: Downstream plain vector declaration
- **WHEN** a downstream node declares the embeddings feature as plain `vector` and the upstream type is `vector_binary`
- **THEN** the propagated type remains `vector_binary`

#### Scenario: Model id published
- **WHEN** an `embeddings` node sets `model_id`
- **THEN** the propagation result's global parameters contain `embeddings_model_id` with that value

### Requirement: SQL filter drops only explicitly listed features
For a `sql_filter` node, propagation SHALL remove each feature listed in its `features_to_drop` config from the downstream feature set and record the dropped features for the node. If any listed feature is mandatory, validation SHALL fail with message code `MANDATORY_FEATURES_DROPPED`. With no list, all features SHALL pass through.

#### Scenario: Listed feature dropped
- **WHEN** a `sql_filter` node lists a non-mandatory feature in `features_to_drop`
- **THEN** the feature is not available downstream and is recorded as dropped for that node

#### Scenario: Mandatory feature listed
- **WHEN** a `sql_filter` node lists a mandatory feature in `features_to_drop`
- **THEN** a `FlowValidationException` with message code `MANDATORY_FEATURES_DROPPED` is raised

#### Scenario: No drop list
- **WHEN** a `sql_filter` node has no `features_to_drop`
- **THEN** all input features remain available downstream

### Requirement: Merge node features follow merge type and column option
For a `merge` node with upstream branches, propagation SHALL combine branch features by `merge_type`: `rows` yields the union of all branch features, and `columns` joins branches on the key `id` according to the column option.

#### Scenario: Rows merge
- **WHEN** a `merge` node has `merge_type` `rows`
- **THEN** its available features are the union of all branch features

#### Scenario: Inner join
- **WHEN** a `merge` node has `merge_type` `columns` with the inner-join column option
- **THEN** its available features are those present in every branch plus `id`

#### Scenario: Full outer join with link names
- **WHEN** a `merge` node has `merge_type` `columns` with the full-outer-join option and two branches both expose `name`
- **THEN** the first `name` keeps its name and the second is exposed as `name_<link_name>` for that branch

#### Scenario: Join key never suffixed
- **WHEN** a `merge` node joins branches by columns and every branch exposes `id`
- **THEN** `id` appears once, unsuffixed

#### Scenario: Merge with no resolved parents
- **WHEN** a `merge` node has no upstream propagation results
- **THEN** its available features are its operator-declared and input features unchanged

### Requirement: Merge duplicate feature names are disambiguated per branch
For a `merge` node with `merge_type` `columns` and the full-outer-join option, propagation SHALL keep every feature and SHALL suffix the second and later occurrence of a duplicate name with the branch's `input_links` link name, or the branch index when no link name resolves. The inner-join option SHALL keep only features common to all branches plus `id`.

#### Scenario: Link name unavailable
- **WHEN** a full-outer-join `merge` node has two branches that both expose `name` and no link name resolves for the second branch
- **THEN** the second is exposed as `name_1`

### Requirement: Terminal operators expose no output features
An operator that is terminal (the `vectordb` operator) SHALL report no output features for its node, while the features it consumes remain available as inputs.

#### Scenario: VectorDB node
- **WHEN** features are propagated through a `vectordb` node
- **THEN** the node's recorded output features are empty and its input features are recorded unchanged

### Requirement: Propagation outcome is unchanged for existing operators
Moving propagation behavior onto operators SHALL NOT change the available features, recorded input and output features, dropped features, global parameters, error codes or error messages produced for any existing flow, including the generic `output_features_to_drop` handling.

#### Scenario: Generic output_features_to_drop
- **WHEN** any node lists a non-mandatory feature in `output_features_to_drop`
- **THEN** the feature is absent downstream but still appears in that node's own output features

#### Scenario: Mandatory drop via output_features_to_drop
- **WHEN** any node lists a mandatory feature in `output_features_to_drop`
- **THEN** a `FlowValidationException` with message code `MANDATORY_FEATURES_DROPPED` is raised
