# Design

## Context

`Canvas.tsx` opens the node properties panel through `openNodePanel`, which sets the selected node and a new `propertiesInfo` for Elyra's `<CommonProperties>` (now rendered by `CommonPropertiesWrapper`). The wrapper configures `applyPropertiesWithoutEdit: true` and provides `applyPropertyChanges`, `closePropertiesDialog`, `controllerHandler` and `propertyListener` callbacks.

In Elyra, `applyPropertyChanges` runs only when `PropertiesMain.applyPropertiesEditing(closeProperties)` runs. That method is reached from the Save button. The method is exposed on the `CommonProperties` component instance, not on the controller from `controllerHandler`.

## Goals / Non-Goals

**Goals:**
- Make the `frontend/canvas-page` "Node properties panel" requirement match observed behavior.

**Non-Goals:**
- Changing runtime behavior of the properties panel.
- Introducing auto-save or a discard prompt.

## Decisions

### 1. Describe the behavior as "discard on switch, commit on Save"
- **Decision**: State that form values are committed to the canvas model when the user saves the panel, and that opening another node while the panel is open does not apply the previous panel's unsaved edits.
- **Rationale**: This is what the application does and what users see. Save is an explicit action, and the Save button is disabled while required parameters are missing. Committing on node switch would bypass that guard.
- **Alternatives Considered**: Keeping auto-save in the spec and implementing it (via a ref on `<CommonProperties>` or `applyOnBlur`). Rejected for this change since it would be a new feature with UX implications and is out of scope for correcting the spec.

### 2. Express the change as REMOVED + ADDED under a new requirement name
- **Decision**: Remove the requirement "Node properties panel" and add "Node properties panel lifecycle" with the corrected text and scenarios, instead of using a MODIFIED delta.
- **Rationale**: `openspec validate --strict` rejects a MODIFIED block that omits a scenario the current spec has ("Auto-save on node switch"), because MODIFIED replaces the whole block and the CLI refuses to drop scenarios silently. Removal of a single scenario is only possible by replacing the requirement. ADDED and REMOVED cannot share one name, so the replacement needs a different name.
- **Alternatives Considered**: (a) MODIFIED while keeping a scenario named "Auto-save on node switch" with new content. Rejected since the name would contradict the behavior.

## Risks / Trade-offs

- **[Risk]** Users may expect unsaved edits to survive a node switch, and the spec now documents that they do not.
  - **Mitigation**: This is the existing behavior. A discard warning or auto-save can be proposed as a separate change.

## Migration Plan

1. Review and validate this change with `openspec validate fix-canvas-page-node-switch-spec --strict`.
2. After review, archive with `openspec archive fix-canvas-page-node-switch-spec` to update `frontend/canvas-page`.
