# Tasks

The implementation will be delivered in two PRs, in this order:

1. Implementation PR 1 unifies the source of operator metadata. It has no
   user-visible change.
2. Implementation PR 2 adds the loading and error state. It must be merged
   after PR 1, and PR 1 and PR 2 should be raised close together.

Implementation groups 1 and 2 will continue against the canonical spec after archiving.

## 1. PR 1: Redux as the single source of operator metadata

- [ ] 1.1 In `CommonPropertiesPanel`, read the operator metadata from the
  `operators` slice with `useAppSelector` and the existing `getOperatorMetadata` selector
  instead of `controller.getAppData()`. This feeds the required-field evaluation that
  controls the Save button. Verify the Save button scenarios in the `CommonPropertiesPanel`
  tests still pass.
- [ ] 1.2 Make any usage of operator metadata in the custom panels under
  `CustomPanels/` read it from the `operators` slice instead of `controller.getAppData()`.
  Update the doc comments that describe the old source. Data in `appData` other than the
  operator metadata, such as `nodeId`, `pipelineFlow`, and `nodeFeatureMap`, stays on
  `appData`. Verify that nothing under
  `frontend/src/components/PropertiesPanel` reads `operatorMetadata` through `getAppData`.
- [ ] 1.3 Update the affected unit test files under
  `frontend/tests/unit/components/PropertiesPanel/` so they supply the operator metadata
  through the Redux store, using `renderWithProviders`. Verify all of them pass.
- [ ] 1.4 Verify that an open panel still receives its options after the metadata
  arrives, now through the Redux store: restart the server, open an Ingest properties panel
  before the metadata arrives, and verify the provider list is populated once the response
  arrives. Verify that `Canvas.tsx` is not changed.
- [ ] 1.5 Run `npm run lint` and `npm run test:coverage` in `frontend/` and verify
  all unit tests pass. Run `npm run build` and verify a successful build.

## 2. PR 2: Loading and error state (after PR 1)

- [ ] 2.1 In `getOperatorMetadata` (`frontend/src/services/api/actions/operator-actions.ts`),
  dispatch `setLoading(true)` before the request and `setError` with a generic message on
  failure. Keep the no-throw behavior and keep logging the raw error with `logUtil.error`.
  Verify with success and failure cases in `operator-actions.test.ts`.
- [ ] 2.2 Add the loading and error strings with `defineMessages()`, following the canonical
  `frontend/i18n` spec. Verify the new ids appear in `messages_en.json` and none were added
  by hand.
- [ ] 2.3 In `CommonPropertiesPanel`, read the error from the `operators` slice
  with `useAppSelector` and the existing selector. Render `InlineLoading` or
  `InlineNotification kind="error"` in the Configuration tab in place of the properties panel form,
  using the derived state. Do not change
  `Canvas.tsx`. Verify the loading, error, and already-loaded scenarios in the
  `CommonPropertiesPanel` tests, using `renderWithProviders`.
- [ ] 2.4 Verify that an open panel moves from the loading state to the
  form, and from the loading state to the error state, when the slice changes.
- [ ] 2.5 Call `controller.setSaveButtonDisable(true)` while the loading or error
  state is shown, and re-evaluate required fields when the form renders. Verify Save is
  disabled in both states and that the saved parameters of an existing node are unchanged.
- [ ] 2.6 Verify the accessibility scenarios: the loading indicator exposes a
  status message and the error is announced as an alert.
- [ ] 2.7 Run `npm run lint` and `npm run test:coverage` in `frontend/` and verify
  all unit tests pass. Run `npm run build` and verify a successful build.
- [ ] 2.8 Reproduce the original issue manually: restart the server and open an
  Ingest properties panel before the metadata arrives. Verify the loading state is shown and
  is then replaced by the populated provider list.

## 3. Spec validation and archiving

- [x] 3.1 Run `openspec validate properties-panel-metadata-loading-state --strict`
  and resolve any failures in the spec artifacts.
- [ ] 3.2 Run `openspec archive properties-panel-metadata-loading-state` once
  the spec artifacts are reviewed and stable to merge the spec delta into
  `openspec/specs/frontend/properties-panel/spec.md` and move this change to
  `openspec/changes/archive/`. Implementation of PRs 1 and 2 continues against the canonical
  spec after archiving. Verify the canonical spec contains both new requirements.
