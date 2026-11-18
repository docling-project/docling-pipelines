# properties-panel/custom-panels/branching-panel Specification

## Purpose

The branching custom panel is the read-only configuration view for the `branching` operator. It shows a summary table of the operator's outgoing links — one row per named link — displaying the target node's display label and the link's condition name. Link conditions are set on the canvas directly via the LinkConditionTearsheet, not through this panel.

## ADDED Requirements

### Requirement: Read-only link summary table
The panel SHALL display a table of all named outgoing links from the branching node, with one row per link.

#### Scenario: Table shows target node and link name
- **WHEN** the branching node has named outgoing links
- **THEN** each row shows the target node's display label and the link condition name

#### Scenario: Links without names or with whitespace-only names are excluded
- **WHEN** an outgoing link has no saved link_name, or the link_name is an empty string or contains only whitespace
- **THEN** that link does not appear in the table

#### Scenario: Empty state when no named links
- **WHEN** no outgoing links have been named
- **THEN** the table shows an empty state

### Requirement: No editing controls in panel
The panel SHALL NOT provide any controls for editing link conditions — those are set via the canvas link decoration.

#### Scenario: Panel is read-only
- **WHEN** the user opens the branching panel
- **THEN** no input fields, buttons, or editable controls are present in the Configuration tab
