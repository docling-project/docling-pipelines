# properties-panel Specification

## Purpose

The properties-panel capability is the operator configuration flyout that opens when a node is selected on the canvas. It renders the operator's icon, type label, an editable display name, a description, and three tabs: Configuration (operator-specific fields), Input (upstream features flowing into the node), and Output (the union of the node's own output features and the passthrough input features, representing everything a downstream node would receive). For the `merge` operator the Output tab shows only the node's own output features, because the backend already writes the full union into `output_features` directly. It is the primary surface through which users configure individual pipeline operators before saving or running a flow.

## ADDED Requirements

### Requirement: Three-tab structure
The panel SHALL always render three tabs — Configuration, Input, and Output — for every selected node.

#### Scenario: Configuration tab is default
- **WHEN** the user opens the panel by selecting a node
- **THEN** the Configuration tab is active and the operator-specific form is visible

#### Scenario: Input tab shows upstream features
- **WHEN** the user selects the Input tab
- **THEN** the features flowing into the selected node from upstream operators are displayed

#### Scenario: Output tab shows downstream features
- **WHEN** the user selects the Output tab
- **THEN** the combined set of features the node will emit to downstream operators is displayed

### Requirement: Editable display name
The panel SHALL allow the user to rename the node's display label inline via an edit icon.

#### Scenario: Edit mode activates on icon click
- **WHEN** the user clicks the edit icon next to the display name
- **THEN** the display name field becomes editable and receives focus

#### Scenario: Name saved on blur
- **WHEN** the user finishes editing and clicks away
- **THEN** the edited display name is persisted to the canvas model

### Requirement: Save button disabled when required params are missing
The Save button — owned by Elyra's `CommonProperties` flyout, not rendered by this panel — SHALL be disabled whenever any required operator parameter has no value. The panel controls this by calling `controller.setSaveButtonDisable(true/false)` after evaluating the current property values against the operator's required attribute metadata.

#### Scenario: Save disabled on missing required field
- **WHEN** a required configuration field is empty
- **THEN** the Save button is disabled

#### Scenario: Save enabled when all required fields have values
- **WHEN** all required configuration fields are filled
- **THEN** the Save button is enabled

### Requirement: Operator-specific configuration panel
The Configuration tab SHALL render the operator-specific form registered for the selected operator type. When no panel is registered for an operator, a placeholder message SHALL be shown.

#### Scenario: Known operator shows its form
- **WHEN** the selected node is a known operator (e.g. ingest_source, chunker)
- **THEN** the operator's custom configuration form is rendered in the Configuration tab

#### Scenario: Unknown operator shows placeholder
- **WHEN** the selected node has no registered configuration panel
- **THEN** a placeholder message is shown in the Configuration tab
