# Spec Delta

## ADDED Requirements

### Requirement: Permission-gated canvas editing actions
When the user lacks permission to modify the flow (the user lacks `editor`, or `flow.created_by` belongs to another user and the user is not `admin`), the Save action and the canvas editing controls SHALL be disabled or hidden with an explanatory tooltip. The editing controls are the palette, undo/redo, cut/paste/delete, comment, node and link-condition saving, flow run properties save, and `FlowInfoPanel` edit details.

#### Scenario: Viewer opens canvas
- **WHEN** a viewer opens `/flows/:flow_id/canvas`
- **THEN** Save, Run flow and canvas editing actions are disabled or hidden with a permission tooltip, while viewing the graph and run history remains available

#### Scenario: Editor opens another user's flow on canvas
- **WHEN** an editor opens a flow created by another user on `/flows/:flow_id/canvas`
- **THEN** Save and flow editing controls are disabled or hidden with an ownership tooltip, while running the saved flow remains enabled

#### Scenario: Owner or admin opens flow on canvas
- **WHEN** the flow's creator or an `admin` opens `/flows/:flow_id/canvas`
- **THEN** Save, Run flow and all editing actions are enabled

### Requirement: Permission-gated flow run on the canvas
When the user lacks `editor` (`viewer`), the Run flow action SHALL be disabled with an explanatory tooltip. Running a saved flow SHALL NOT depend on flow ownership.

#### Scenario: Viewer cannot run
- **WHEN** a viewer opens a flow on the canvas
- **THEN** Run flow is disabled with a permission tooltip

#### Scenario: Non-owner editor can run
- **WHEN** an editor opens another user's flow on the canvas
- **THEN** Run flow is enabled
