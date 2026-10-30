# Proposal

## Why

Currently, the operator metadata request (`fetchOperatorMetadata`) can still be in flight when a user
opens an operator's properties panel. The Configuration tab then renders from an empty operator metadata
map, so metadata-driven options are missing. This causes several problems:

- Nothing tells the user the data is still loading, so a form with empty field options looks
  like a broken one. The options only appear once the response arrives.
- A failed operator metadata fetch is indistinguishable from a slow one. The fetch action logs and
  absorbs the error, so the user sees the same empty form either way.
- The canonical `frontend/properties-panel` spec does not say what the Configuration tab
  shows while operator metadata is pending or when its fetch fails, so this behavior is currently
  unspecified.

## What Changes

- While the operator metadata is not yet available, the Configuration tab will show a loading
  state instead of the configuration form.
- When the operator metadata arrives while the panel is open, the loading state will be replaced by the
  configuration form with populated options from the operator metadata.
- When the operator metadata fetch fails, the Configuration tab will show an error state instead of an
  empty or partial form, and will not stay in the loading state indefinitely.
- While the Configuration tab is in the loading or error state, the panel Save button will be
  disabled, so an unrendered form cannot be saved over the node's existing configuration.
- When the operator metadata is already loaded, the form will continue to render immediately with no
  loading flash. This is the current behavior. It will be specified so it is not regressed.
- Any usage of the operator metadata in the properties panel components will read it from the
  Redux store instead of `controller.getAppData()`, so the loading state, the error state, and the
  form options all come from one source. This is an internal change with no new user-visible
  behavior of its own.

## Delivery

The implementation will be delivered in two PRs after the spec PR:

1. PR 1: the properties panel components will read the operator metadata from the Redux
   store instead of `controller.getAppData()`. There is no user-visible change.
2. PR 2: the operator metadata fetch action will set `loading` and `error`, and the
   Configuration tab will show the loading and error states. This PR depends on PR 1.

PR 1 comes first so that the loading state and the form options never come from different
sources. PR 2 should be raised right after PR 1.

## Capabilities

### New Capabilities

None

### Modified Capabilities

- `frontend/properties-panel`: will add requirements for the Configuration tab loading state
  and error state driven by the operator metadata fetch.

## Impact

This change is frontend-only. It will not affect:
- Routing under `/ui`
- BFF proxy routes
- Backend REST API routes, operators, or storage adapters

Current state of Redux: the `operators` slice defines `loading` and `error` for the operator
metadata fetch lifecycle, but the operator metadata fetch action does not use them.
No component under `frontend/src/components/PropertiesPanel` reads Redux. They read
`operatorMetadata` through `controller.getAppData()`.

Planned change of Redux:
- No new slice fields will be added.
- PR 1: any usage of operator metadata in the properties panel components, including
  `CommonPropertiesPanel` and the custom panels under
  `frontend/src/components/PropertiesPanel/CustomPanels/`, will read it from the `operators`
  slice instead of `controller.getAppData()`, using the selector the slice already exports.
  Other data that Canvas places in `appData`, such as `nodeId`, `pipelineFlow`, and
  `nodeFeatureMap`, will still be read from `appData`.
- PR 2: the operator metadata fetch action will set `loading` and `error`, and
  `CommonPropertiesPanel` will read the error state from the `operators` slice, using the
  selectors the slice already exports.

Carbon components: `InlineLoading` will render the loading state and `InlineNotification` with
`kind="error"` will render the error state. Both will render inside the existing Configuration tab.

Affected frontend areas:
- PR 1: the custom panel components under `frontend/src/components/PropertiesPanel/CustomPanels/` that
  use operator metadata
- PR 1: the affected unit test files under `frontend/tests/unit/components/PropertiesPanel/`
- PR 1 and PR 2: `CommonPropertiesPanel`, which renders the Configuration tab
- PR 2: the operator metadata API action (`frontend/src/services/api/actions/operator-actions.ts`)

## Non-goals

- This change will not alter the Input and Output tabs. They already show their own
  loading state.
- This change will not modify `frontend/canvas-page` or `Canvas.tsx`, and will not add
  loading or error state to the `appData` that Canvas builds for the properties panel.
  Canvas will keep placing `operatorMetadata` in `appData`. Removing it once nothing in the
  properties panel reads it is a separate cleanup.
- This change will not modify `frontend/state/operators-slice`. Its loading and error
  states already covers this lifecycle.
- This change will not add an automatic retry for a failed metadata
  fetch. The existing behavior stays: a failed fetch is not retried while the Canvas page
  remains mounted, and is attempted again the next time the Canvas page mounts with no
  metadata loaded.
