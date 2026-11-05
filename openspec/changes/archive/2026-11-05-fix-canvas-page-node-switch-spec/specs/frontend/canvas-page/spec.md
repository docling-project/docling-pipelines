# Spec Delta

## REMOVED Requirements

### Requirement: Node properties panel

## ADDED Requirements

### Requirement: Node properties panel lifecycle
The page SHALL open a right-flyout properties panel when an execution node is double-clicked or edited from the context menu. The panel SHALL load cached parameter definitions, display properties via `CommonProperties`, show async loading states, and commit form values to the canvas model when the user saves the panel. Unsaved edits SHALL NOT be committed when the user opens a different node.

#### Scenario: Panel opens on double-click
- **WHEN** the user double-clicks an execution node
- **THEN** the right-flyout properties panel opens for that node

#### Scenario: Non-execution nodes skip panel
- **WHEN** a node with `type !== 'execution_node'` is double-clicked
- **THEN** no properties panel opens

#### Scenario: Parameter definitions are cached
- **WHEN** the user opens a panel for an operator type already opened this session
- **THEN** the cached param definition is used without a new network request

#### Scenario: Save commits form values to the canvas model
- **WHEN** the user clicks Save in the properties panel for node A
- **THEN** the form values are written to node A's parameters in the canvas model and the flow is marked dirty

#### Scenario: Unsaved edits are discarded on node switch
- **WHEN** the panel is open for node A with unsaved edits and the user opens node B
- **THEN** the panel shows node B and node A's unsaved edits are not written to node A's parameters

#### Scenario: Required-field guard disables Save button
- **WHEN** any required parameter has an empty or missing value
- **THEN** the properties panel Save button is disabled
