# Tasks

The implementation will be delivered in two PRs in this order: PR 1 unifies the source of
operator metadata with no user-visible change, and PR 2 adds the loading and error state and
must merge after PR 1.

## 1. PR 1: Redux as the single source of operator metadata

- [ ] 1.0 Rename all six selectors in `frontend/src/slices/operatorsSlice.ts` from `getX` to
  `selectX` (the list is in `design.md`) and update every import, including `Canvas.tsx`. Keep
  the API action `getOperatorMetadata` in `operator-actions.ts` as it is. Verify with a search
  that no old selector name is still used, that the only edit to `Canvas.tsx` is the selector
  import, and that the tests of the slice pass.
- [ ] 1.1 In `CommonPropertiesPanel`, read the operator metadata from the
  `operators` slice with `useAppSelector` and `selectOperatorMetadata`
  instead of `controller.getAppData()`. This feeds the required-field evaluation that
  controls the Save button. Verify the Save button scenarios in the `CommonPropertiesPanel`
  tests still pass.
- [ ] 1.2 Make any usage of operator metadata in the custom panels under
  `CustomPanels/` read it from the `operators` slice with `selectOperatorMetadata` instead of
  `controller.getAppData()`.
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
  arrives.
- [ ] 1.5 Run `npm run lint` and `npm run test:coverage` in `frontend/` and verify
  all unit tests pass. Run `npm run build` and verify a successful build.

## 2. PR 2: Loading and error state (after PR 1)

- [ ] 2.1 In `getOperatorMetadata` (`frontend/src/services/api/actions/operator-actions.ts`),
  dispatch `clearError()` and `setLoading(true)` as the first statements, before the `try`
  block, and dispatch `setError` on failure. Keep the no-throw behavior
  and keep logging the raw error with `logUtil.error`. Update the JSDoc of the action: remove
  the `@throws` tag, since the action logs and absorbs errors and does not rethrow, remove the
  statement that the metadata is passed to the panels via `appData.operatorMetadata`, and
  describe the new `loading` and `error` dispatches. Verify with success, failure, and
  remount after failure cases in `operator-actions.test.ts`. In the remount case, a previous
  error is cleared when the new request starts, and `loading` is true before the request
  resolves.
- [ ] 2.2 Add the loading and error strings with `defineMessages()`, following the canonical
  `frontend/i18n` spec. Verify the new ids appear in `messages_en.json` and none were added
  by hand.
- [ ] 2.3 In `CommonPropertiesPanel`, read the loading flag from the `operators` slice
  with `useAppSelector` and `selectOperatorsLoading`, in addition to the metadata from task 1.1.
  Keep the existing check for a registered configuration panel first, so an operator with no
  registered panel still shows the placeholder. Add a set of operators whose panel does not
  depend on operator metadata (`branching`, `merge`, `ededup`, `doc_quality`) next to
  `OPERATOR_PANEL_MAP`, with a comment that a panel that reads operator metadata must not be
  added. For these operators, render the form whatever the metadata and `loading` are. For any
  other operator with a registered panel, show the form if the metadata has attributes for the
  node's operator, otherwise the loading state if `loading` is true, otherwise the error state.
  Render `InlineLoading` or `InlineNotification kind="error"` in the Configuration tab in
  place of the form. Verify the loading, error, already loaded, remount after failure, missing
  operator entry, and empty entry scenarios, that an unknown operator still shows the
  placeholder, and that each operator in the set renders its form with empty metadata, while
  loading and after a failure, in the `CommonPropertiesPanel` tests, using
  `renderWithProviders`.
- [ ] 2.4 Verify that an open panel moves from the loading state to the
  form, and from the loading state to the error state, when the slice changes.
- [ ] 2.5 Call `controller.setSaveButtonDisable(true)` while the loading or error
  state is shown, and re-evaluate required fields when the form renders. Verify Save is
  disabled in both states, that the saved parameters of an existing node are unchanged, and
  that Save is not disabled by the metadata request for an operator in the set from task 2.3.
- [ ] 2.6 Verify the accessibility scenarios: the loading indicator exposes a
  status message and the error is announced as an alert.
- [ ] 2.7 Run `npm run lint` and `npm run test:coverage` in `frontend/` and verify
  all unit tests pass. Run `npm run build` and verify a successful build.
- [ ] 2.8 Reproduce the original issue manually: restart the server and open an
  Ingest properties panel before the metadata arrives. Verify the loading state is shown and
  is then replaced by the populated provider list. Also open a Branching panel in the same
  window and verify it renders at once.

## 3. Spec validation and archiving

- [x] 3.1 Run `openspec validate properties-panel-metadata-loading-state --strict`
  and resolve any failures in the spec artifacts.
- [ ] 3.2 Run `openspec archive properties-panel-metadata-loading-state` once
  the spec artifacts are reviewed and stable to merge the spec delta into
  `openspec/specs/frontend/properties-panel/spec.md` and move this change to
  `openspec/changes/archive/`. Implementation of PRs 1 and 2 continues against the canonical
  spec after archiving. Verify the canonical spec contains both new requirements and the
  three modified requirements (`Three-tab structure`, `Operator-specific configuration
  panel`, `General operator configuration lifecycle`), each with all of its scenarios.
