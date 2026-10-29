# Spec Delta

## Purpose

Allow Python applications and notebooks to construct, inspect, validate, and execute Docling document ingestion flows without hand-authoring JSON files or runtime graph identifiers.

## ADDED Requirements

### Requirement: Construct flows with configured nodes
The public Python API SHALL expose `Flow` with keyword-based node addition using typed configurations or a registered-operator specification. Nodes SHALL have unique names. Adding a node SHALL snapshot its configuration without initializing an operator or modifying the caller's configuration.

#### Scenario: Configure a node
- **WHEN** a user adds a named chunker with a valid configuration
- **THEN** the flow contains that named chunker with the supplied parameters and applicable defaults

#### Scenario: Duplicate name
- **WHEN** a user adds a node with a name already used in the flow
- **THEN** the addition fails with a diagnostic identifying the duplicate and the flow remains unchanged

#### Scenario: Isolated configuration snapshots
- **WHEN** the caller changes a nested dictionary after adding a configured node
- **THEN** the node's stored configuration remains unchanged

### Requirement: Connect nodes explicitly
The API SHALL expose `connect(source=..., target=..., output=...)` and `connect_chain(nodes=...)`. Connections SHALL reference existing nodes and named branch outputs where applicable. Unknown nodes, unknown outputs, duplicate edges, self-edges, and cycles SHALL fail without partially changing the graph.

#### Scenario: Linear chain
- **WHEN** a user connects source, extract, chunk, embed, and output nodes using a chain
- **THEN** the flow has the same dependencies as connecting each adjacent pair individually

#### Scenario: Atomic invalid chain
- **WHEN** a chain includes an unknown node or introduces a cycle
- **THEN** no edges from that chain are added and a diagnostic identifies the problem

### Requirement: Address branch outputs by name
The API SHALL expose named conditional branches and unconditional fan-out. Each conditional branch SHALL independently select matching rows; unconditional branches SHALL receive all input rows. Connections SHALL serialize named outputs into existing authoring branch references without requiring user-supplied runtime link identifiers.

#### Scenario: Overlapping branch conditions
- **WHEN** one document satisfies two branch conditions
- **THEN** the document is included in both outputs rather than only the first matching output

#### Scenario: Unmatched document
- **WHEN** a document satisfies no conditional branch and there is no unconditional branch
- **THEN** that document is absent from all branch outputs according to existing branching semantics

#### Scenario: Unconditional fan-out
- **WHEN** a branching node has two branches with no conditions
- **THEN** both branches receive every input row

### Requirement: Combine branch results explicitly
The API SHALL support explicit merge nodes with at least two incoming connections. Row merges SHALL retain existing duplicate-`id` rejection. Column merges SHALL join on `id` with `inner_join` or `full_outer`. Merge input links SHALL be generated from graph connections; implicit table merging SHALL NOT be introduced.

#### Scenario: Join independent enrichment results
- **WHEN** two branches add different feature columns to the same document IDs and feed a column merge
- **THEN** the result combines their columns by `id` using the configured join semantics

#### Scenario: Duplicate IDs in row merge
- **WHEN** two incoming tables contain the same `id` and use row merge
- **THEN** execution rejects the duplicate IDs rather than silently duplicating or deduplicating rows

#### Scenario: Multiple destinations
- **WHEN** branches terminate at separate valid output nodes without a merge
- **THEN** the flow can validate and execute without requiring the branches to rejoin

### Requirement: Exchange portable authoring definitions
The API SHALL expose `to_dict()` and `from_dict(data=...)` using the existing authoring format. Exported dictionaries SHALL be JSON-serializable, detached copies preserving names, dependencies, parameters, global settings, description, and a supplied flow ID. Import/export SHALL NOT resolve secrets or persist a flow.

#### Scenario: Equivalent round trip
- **WHEN** a branched flow is exported, JSON-encoded and decoded, and imported
- **THEN** its authoring semantics, branch names, merge settings, and explicit flow ID are preserved

#### Scenario: Existing manager interoperability
- **WHEN** an exported dictionary is passed as `DocpipeFlowManager(flow_def=...)`
- **THEN** it compiles and executes through the existing authoring/compiler path without a JSON file

### Requirement: Validate without executing the flow
`Flow.validate()` SHALL return a report with `valid`, `errors`, and `warnings`, plus `raise_for_errors()`. Validation SHALL check parameter schemas, graph structure, and upstream feature compatibility without instantiating runtime operators or probing external services. Warnings SHALL NOT make a report invalid, including existing missing-terminal-output warnings.

#### Scenario: Required upstream feature absent
- **WHEN** a node requires a column not supplied by its predecessors
- **THEN** the report is invalid and identifies the node and missing feature

#### Scenario: Report helper
- **WHEN** `raise_for_errors()` is called on a report containing errors
- **THEN** a flow-validation exception is raised with the report's diagnostics

#### Scenario: Offline validation
- **WHEN** a valid flow is validated with external services unavailable and source paths absent on this machine
- **THEN** static validation does not fail solely because those resources are unavailable

### Requirement: Execute using existing runtime semantics
`Flow.execute()` SHALL delegate a detached authoring definition through the existing flow manager and runtime, returning the manager's execution result. The API SHALL support existing execution options and custom packages. Global settings, micro-batching defaults, cancellation, and execution metadata SHALL retain manager semantics.

#### Scenario: Default micro-batching
- **WHEN** a builder flow executes without an explicit micro-batching setting
- **THEN** execution uses the manager's existing enabled-by-default behavior

#### Scenario: Explicit override
- **WHEN** the flow explicitly disables micro-batching
- **THEN** the supplied value is preserved during execution

### Requirement: Preserve operator data contracts
Programmatically authored flows SHALL retain each operator's existing PyArrow input/output schema and `tuple[list[pa.Table], dict]` transform contract. Branch outputs SHALL remain tables, column merge SHALL require `id`, and execution metadata SHALL remain compatible with existing reporting.

#### Scenario: Equivalent authored inputs
- **WHEN** equivalent builder and dictionary flows execute against identical fixtures
- **THEN** they produce equivalent table schemas, content, and operator metadata apart from generated identifiers and timing

### Requirement: Support registered extensions without publishing internal components
The API SHALL accept `OperatorSpec(type=..., config=...)` for registered custom operators and use existing factory priority. Custom packages SHALL be selectable before validation and execution. Schema-less extensions SHALL retain their validation hooks with an explicit coverage warning. Internal `doc_id_hash` SHALL NOT acquire a public typed configuration.

#### Scenario: Custom operator resolution
- **WHEN** a registered custom operator overrides a built-in short name
- **THEN** generic authoring resolves it according to existing factory priority rather than silently validating it as the built-in

#### Scenario: No extension schema
- **WHEN** a generic custom node has no registered pure configuration schema
- **THEN** static validation reports its limited coverage without constructing the operator and execution retains its existing checks
