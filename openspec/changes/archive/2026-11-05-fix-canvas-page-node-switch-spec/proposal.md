# Proposal

## Why

The `frontend/canvas-page` spec says the node properties panel "SHALL ... commit form values to the canvas model on node switch" and has a scenario requiring `applyPropertiesEditing(false)` to be called on the properties controller when the user opens another node. This has never been true at runtime:

- `applyPropertiesEditing` is a method on the Elyra `<CommonProperties>` component instance, not on the `CommonPropertiesController` returned by the `controllerHandler` callback. The optional call `propertiesControllerRef.current?.applyPropertiesEditing?.(false)` in `openNodePanel` was a silent no-op.
- Elyra applies edits only through `applyPropertiesEditing`, which the Save button calls. `applyOnBlur` is not enabled, so nothing else triggers it.
- Observed UI behavior: switching to another node while the panel is open discards the previous panel's unsaved edits. Edits are committed only when the user clicks Save.

The dead call has been removed from `Canvas.tsx` as part of extracting `CommonProperties` into `CommonPropertiesWrapper`. The spec must now describe the actual behavior so it does not mislead future work.

## What Changes

- Replace the "Node properties panel" requirement in `frontend/canvas-page` with "Node properties panel lifecycle" (REMOVED + ADDED, see `design.md` for why it is not a MODIFIED):
  - Replace "commit form values to the canvas model on node switch" with "commit form values to the canvas model when the user saves the panel", and state that unsaved edits are not committed when another node is opened.
  - Drop the scenario "Auto-save on node switch".
  - Add the scenarios "Save commits form values to the canvas model" and "Unsaved edits are discarded on node switch".
  - Carry over unchanged: "Panel opens on double-click", "Non-execution nodes skip panel", "Parameter definitions are cached" and "Required-field guard disables Save button".
- No code changes. This change only aligns the spec with existing behavior.

## Non-goals

- Adding auto-save on node switch or a confirmation of unsaved edit discard prompt.
- Changing the required-field guard behavior or any other scenario in the requirement.

## Capabilities

### New Capabilities
- None

### Modified Capabilities
- `frontend/canvas-page`: replace the "Node properties panel" requirement so it no longer claims that form values are committed or auto-saved on node switch.

## Impact

- **Affected Layer**: Frontend spec only
- **Affected Spec**: `openspec/specs/frontend/canvas-page/spec.md` (via archive of this change).
- **Related Code**: `frontend/src/pages/Canvas/Canvas.tsx` (`openNodePanel`) and `frontend/src/components/PropertiesPanel/CommonPropertiesWrapper.tsx`, already updated in the refactor that extracted `CommonProperties`.
