# frontend/elyra-canvas Specification

## Purpose
The elyra-canvas capability is the wrapper around the Elyra `CommonCanvas` library that renders the interactive pipeline graph. It provides a stable interface between the canvas page and the Elyra library — accepting pipeline flow data, palette, toolbar configuration, and event handler callbacks, and emitting a `CanvasController` instance on mount. It also renders optional panel slots (right flyout, bottom panel, top panel) and applies a consistent card-style node layout.

## Requirements

### Requirement: Pipeline flow rendering
The canvas SHALL render the pipeline flow nodes and links defined in the provided pipelineFlow prop.

#### Scenario: Nodes rendered from pipeline flow
- **WHEN** a pipelineFlow is provided
- **THEN** the canvas renders all nodes and links from that flow definition

#### Scenario: Canvas renders empty when no flow provided
- **WHEN** no pipelineFlow is provided
- **THEN** the component renders an empty container `<div>` and `CommonCanvas` is not mounted — no Elyra graph instance is created until a flow is provided

### Requirement: Controller callback on ready
The canvas SHALL call the `onCanvasControllerReady` callback with the CanvasController instance once the canvas is mounted. The callback is driven by a `useEffect` with `[canvasController, onCanvasControllerReady]` as dependencies, so it also fires if the callback prop reference changes after mount (callers should memoize the callback to prevent spurious re-invocations).

#### Scenario: Controller available after mount
- **WHEN** the canvas mounts and onCanvasControllerReady is provided
- **THEN** the callback is invoked with the CanvasController instance on the first render after mount

### Requirement: Card node layout
The canvas SHALL render all nodes using the card-style external node component (CardNodeWrapper) at a fixed default size.

#### Scenario: Nodes use card layout
- **WHEN** nodes are rendered
- **THEN** each node appears as a card with the operator icon, label, and status area

### Requirement: Optional panel slots
The canvas SHALL conditionally render a right flyout, bottom panel, and top panel based on the provided props.

#### Scenario: Top panel shown when enabled
- **WHEN** showTopPanel is true and topPanelContent is provided
- **THEN** the content is rendered above the toolbar

#### Scenario: Right flyout shown when enabled
- **WHEN** showRightFlyout is true and rightFlyoutContent is provided
- **THEN** the content is rendered in the right flyout

### Requirement: Event handler passthrough
The canvas SHALL forward click, edit action, context menu, and decoration action events to the provided handler callbacks.

#### Scenario: Click action forwarded
- **WHEN** the user clicks a node or link
- **THEN** the clickActionHandler callback is invoked with the event source

#### Scenario: Context menu forwarded
- **WHEN** the user right-clicks or triggers the context toolbar
- **THEN** the contextMenuHandler callback is invoked and its return value used as menu items

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

### Requirement: Elyra canvas keyboard navigation and ARIA landmarks
The Elyra canvas container SHALL provide accessible ARIA region landmarks, support Tab and arrow key traversal across placed nodes and ports, and emit screen-reader announcements when nodes are selected or links are established.

#### Scenario: Canvas viewport marked with application landmark
- **WHEN** the canvas component mounts
- **THEN** the canvas wrapper element has `role="region"` and an appropriate `aria-label` identifying the interactive pipeline editor

#### Scenario: Tab key navigates between canvas nodes
- **WHEN** the user presses Tab within the canvas viewport
- **THEN** keyboard focus cycles sequentially through placed canvas nodes and their input/output ports
