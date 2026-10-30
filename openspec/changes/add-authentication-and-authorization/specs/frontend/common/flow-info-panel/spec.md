# Spec Delta

## ADDED Requirements

### Requirement: Permission-gated edit details button
`FlowInfoPanel` SHALL disable or hide the edit (pencil) icon button with an explanatory tooltip when the caller cannot modify the flow (lacks `editor`, or the flow is owned by another user and the caller is not `admin`).

#### Scenario: Unauthorized caller views flow info panel
- **WHEN** a viewer or a non-owner editor opens `FlowInfoPanel`
- **THEN** the edit details button is disabled with a tooltip explaining the missing permission or ownership
