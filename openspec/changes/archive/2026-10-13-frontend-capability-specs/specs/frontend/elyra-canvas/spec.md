# Spec Delta

## ADDED Requirements

### Requirement: Palette categorization and operator registration
The canvas palette SHALL categorize registered operators into collapsible sections (Ingest, Extract, Functional, Quality, VectorDB, Storage) and support dragging operator tiles onto the canvas viewport to create new nodes.

#### Scenario: Operators grouped by category in palette
- **WHEN** the canvas palette is opened
- **THEN** operators are listed under their respective category headers with their corresponding icons

#### Scenario: Dragging operator from palette creates canvas node
- **WHEN** the user drags an operator tile from the palette and drops it onto the canvas
- **THEN** a new pipeline node of that operator type is created at the drop coordinates

### Requirement: Canvas toolbar configuration and action states
The canvas SHALL provide a top toolbar with action buttons (Zoom In, Zoom Out, Zoom to Fit, Undo, Redo, Layout Arrange, Delete, Palette Toggle) that dynamically reflect their enabled/disabled states based on selection and history stacks.

#### Scenario: Undo and redo reflect command history
- **WHEN** no prior canvas actions exist
- **THEN** the Undo button is disabled, becoming enabled once an action is taken

#### Scenario: Zoom to fit reframes all nodes
- **WHEN** the user clicks "Zoom to Fit" on the toolbar
- **THEN** the canvas viewport scales and centers to encompass all nodes and connections

### Requirement: Node and canvas context menu actions
The canvas SHALL display contextual menus when right-clicking on nodes, links, or the canvas background, providing appropriate actions (Properties, Disconnect, Delete, Duplicate).

#### Scenario: Right click on node opens node context menu
- **WHEN** the user right-clicks a canvas node
- **THEN** a context menu appears with options to open Properties, disconnect links, or delete the node

#### Scenario: Right click on canvas background opens canvas menu
- **WHEN** the user right-clicks an empty canvas area
- **THEN** a context menu appears with options to add nodes, arrange layout, or zoom

### Requirement: Canvas grid and layout configuration
The canvas SHALL support snap-to-grid positioning, orthogonal or curved link routing styles, and auto-layout graph arrangement algorithms.

#### Scenario: Snap to grid aligns dragged nodes
- **WHEN** a user moves a node across the canvas
- **THEN** node placement snaps to the active grid coordinates for visual alignment

### Requirement: Node card structure and decoration badges
The `CardNodeWrapper` component SHALL render each node with an operator icon, editable label, input/output port attachment dots, and optional badge decorations for validation warnings or execution status.

#### Scenario: Node card displays operator icon and port dots
- **WHEN** a node is rendered on the canvas
- **THEN** it displays its operator icon, node label, and input/output connection port dots
