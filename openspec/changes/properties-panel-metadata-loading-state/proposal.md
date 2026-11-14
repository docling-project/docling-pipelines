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
  state instead of the configuration form. This applies only to operators whose panel depends on
  operator metadata. Operators whose panel does not read it, such as Branching, Merging,
  Ededup, and Document Quality, will keep rendering their panel immediately.
- When the operator metadata arrives while the panel is open, the loading state will be replaced by the
  configuration form with populated options from the operator metadata.
- When the operator metadata fetch fails, the Configuration tab will show an error state instead of an
  empty or partial form, and will not stay in the loading state indefinitely.
- When the operator metadata fetch succeeds but has no attributes for the selected node's operator,
  because the result is empty or lacks that operator, the Configuration tab will show the same error state. The panel depends on the metadata of its own operator to populate its fields, so this is treated as an error and not as a loading state. An operator with no registered configuration panel still shows the placeholder.
- When the operator metadata is fetched again on Canvas remount after an earlier failure, the
  Configuration tab will show the loading state and not the previous error. The fetch action
  will clear the previous error when the new request starts.
- While the Configuration tab is in the loading or error state, the panel Save button will be
  disabled, so an unrendered form cannot be saved over the node's existing configuration. Save
  is not affected for operators whose panel does not depend on operator metadata.
- When the operator metadata is already loaded, the form will continue to render immediately with no
  loading flash. This is the current behavior. It will be specified so it is not regressed.
- Any usage of the operator metadata in the properties panel components will read it from the
  Redux store instead of `controller.getAppData()`, so the loading state, the error state, and the
  form options all come from one source. This is an internal change with no new user-visible
  behavior of its own.

## Delivery

The implementation will be delivered in two PRs after the spec PR. PR 1 makes the properties
panel components read the operator metadata from the Redux store, with no user-visible change.
PR 2 adds the loading and error states and depends on PR 1, so that the loading state and the
form options never come from different sources. It should be raised right after PR 1.

## Capabilities

### New Capabilities

None

### Modified Capabilities

- `frontend/properties-panel`: will add requirements for the Configuration tab loading state
  and error state driven by the operator metadata fetch, and will modify three existing
  requirements (`Three-tab structure`, `Operator-specific configuration panel`, `General operator configuration lifecycle`) whose current wording conflicts with that behavior.

## Impact

This change is frontend-only. It will not affect:
- Routing under `/ui`
- BFF proxy routes
- Backend REST API routes, operators, or storage adapters

Current state of Redux: the `operators` slice defines `loading` and `error` for the operator
metadata fetch lifecycle, but the fetch action does not use them. No component under
`frontend/src/components/PropertiesPanel` reads Redux. They read `operatorMetadata` through
`controller.getAppData()`. The name `getOperatorMetadata` is used for both the API action in
`operator-actions.ts` and the Redux selector in `operatorsSlice.ts`, and all six selectors of
the slice are named `getX`.

Planned change of Redux (no new slice fields):
- PR 1: all six selectors in `operatorsSlice.ts` will be renamed from `getX` to `selectX`, for
  example `getOperatorMetadata` to `selectOperatorMetadata`. The API action keeps the name
  `getOperatorMetadata`. The properties panel components, including `CommonPropertiesPanel` and
  the custom panels, will read operator metadata from the `operators` slice instead of
  `controller.getAppData()`. Other data in `appData`, such as `nodeId`, `pipelineFlow`, and
  `nodeFeatureMap`, stays on `appData`. The full rename list is in `design.md`.
- PR 2: the fetch action will clear the previous error and set `loading` before the request,
  and set `error` on failure. `CommonPropertiesPanel` will read the metadata and `loading`
  from the slice. For an operator whose panel depends on operator metadata, no attributes for
  the selected node's operator, with `loading` false, is the error state. Operators whose
  panel does not depend on operator metadata skip the loading and error checks.

Carbon components: `InlineLoading` will render the loading state and `InlineNotification` with
`kind="error"` will render the error state. Both will render inside the existing Configuration tab.

Affected frontend areas:
- PR 1: the six selector declarations in `frontend/src/slices/operatorsSlice.ts`, and the
  import of the metadata selector in `frontend/src/pages/Canvas/Canvas.tsx`
- PR 1: the custom panel components under `frontend/src/components/PropertiesPanel/CustomPanels/` that
  use operator metadata
- PR 1: the affected unit test files under `frontend/tests/unit/components/PropertiesPanel/`
- PR 1 and PR 2: `CommonPropertiesPanel`, which renders the Configuration tab
- PR 2: the operator metadata API action (`frontend/src/services/api/actions/operator-actions.ts`)

## Non-goals

- This change will not alter the Input and Output tabs. They already show their own
  loading state.
- This change will not modify `frontend/canvas-page`, and will not change the behavior of
  `Canvas.tsx`. The only edit to `Canvas.tsx` is the import of the renamed selector. It will
  not add loading or error state to the `appData` that Canvas builds for the properties panel.
  Canvas will keep placing `operatorMetadata` in `appData`. Removing it once nothing in the
  properties panel reads it is a separate cleanup.
- This change will not apply defaults to nodes dropped on the canvas before the operator
  metadata arrives. `applyNodeDefaults` in `Canvas.tsx` currently returns early for these nodes
  because it has no attributes to read, and nothing applies their defaults later, so their
  saved parameters stay empty. Fixing this modifies Canvas behavior and saved flow data, so it
  is a separate change against `frontend/canvas-page`. In this change, the Configuration tab
  shows the form for such a node once the metadata arrives, and the form
  does not have the defaults that `applyNodeDefaults` would have written.
- This change will not modify behavior in `frontend/state/operators-slice`. Its loading and
  error states already cover this lifecycle.
- This change will not add an automatic retry for a failed metadata
  fetch. The existing behavior stays: a failed fetch is not retried while the Canvas page
  remains mounted, and is attempted again the next time the Canvas page mounts with no
  metadata loaded.
