# elyra-canvas Specification

## Purpose

The elyra-canvas capability is the wrapper around the Elyra `CommonCanvas` library that renders the interactive pipeline graph. It provides a stable interface between the canvas page and the Elyra library — accepting pipeline flow data, palette, toolbar configuration, and event handler callbacks, and emitting a `CanvasController` instance on mount. It also renders optional panel slots (right flyout, bottom panel, top panel) and applies a consistent card-style node layout.

## ADDED Requirements

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
