# Spec Delta

## ADDED Requirements

### Requirement: Permission-gated canvas editing and execution actions
When the user lacks permission to modify the flow (the user lacks `editor`, or `flow.created_by` belongs to another user and the user is not `admin`), the Save action, canvas editing controls (palette, undo/redo, cut/paste/delete, comment, node and link-condition saving, flow run properties save, and `FlowInfoPanel` edit details) SHALL be disabled or hidden with an explanatory tooltip. When the user lacks `editor` (`viewer`), the Run flow action SHALL also be disabled with an explanatory tooltip.

#### Scenario: Viewer opens canvas
- **WHEN** a viewer opens `/flows/:flow_id/canvas`
- **THEN** Save, Run flow and canvas editing actions are disabled or hidden with a permission tooltip, while viewing the graph and run history remains available

#### Scenario: Editor opens another user's flow on canvas
- **WHEN** an editor opens a flow created by another user on `/flows/:flow_id/canvas`
- **THEN** Save and flow editing controls are disabled or hidden with an ownership tooltip, while running the saved flow remains enabled

#### Scenario: Owner or admin opens flow on canvas
- **WHEN** the flow's creator or an `admin` opens `/flows/:flow_id/canvas`
- **THEN** Save, Run flow and all editing actions are enabled
