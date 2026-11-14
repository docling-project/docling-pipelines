# Design

## Context

See the [proposal](proposal.md) for the behavioral contract.

### Current state

`Canvas.tsx` currently fetches operator metadata once on mount through `getOperatorMetadata`
and keeps it in the `operators` slice. The properties panels currently read `operatorMetadata`
through `controller.getAppData()`. If the request is still in flight, `operatorMetadata` is `{}`
and metadata-driven fields (for example the Ingest Source provider list) render with no options.
When the response arrives, the fields receive their options. Nothing indicates the loading state in between,
and a failed fetch leaves the fields empty permanently.

Three facts about the current code shape the design:

- `getOperatorMetadata` in `operator-actions.ts` catches and logs every error and never
  throws, so a failure leaves the store identical to a still loading state (`metadata = {}`,
  `error = null`).
- The `operators` slice has `loading` and `error` for the metadata fetch lifecycle, and
  `setError` clears `loading`. The metadata action does not use them.
- The slice exports six selectors, all named `getX`. `getOperatorMetadata` is also the name of
  the API action in `operator-actions.ts`, and `Canvas.tsx` disambiguates them with import
  aliases.

### Planned change

The implementation will be delivered in two PRs, in this order.

PR 1, a single source of operator metadata (no user-visible change):
- All six selectors in `operatorsSlice.ts` will be renamed from `getX` to `selectX` (see
  Decisions). The API action in `operator-actions.ts` keeps the name `getOperatorMetadata`.
- Any usage of operator metadata in the properties panel components, including
  `CommonPropertiesPanel` and the custom panels, will read it from the slice instead of
  `controller.getAppData()`, so there is a single source of truth for the loading state,
  the error state, and the form options.

PR 2, loading and error state (depends on PR 1):
- The metadata action will clear the previous error and set `loading` and `error` on the
  `operators` slice.
- `CommonPropertiesPanel` will read the metadata and `loading` from the slice and render a
  loading, error, or form state in the Configuration tab.

The behavior of `Canvas.tsx` will not change in either PR. Its only edit is the import of the
renamed selector in PR 1.

## Component Hierarchy

Planned structure:

```
CommonPropertiesPanel                  ← will read operators slice (metadata, loading) via selectors
└── Configuration tab
    ├── InlineLoading                  ← will show while metadata is pending; status text
    ├── InlineNotification kind=error  ← will show when the metadata fetch failed
    └── operator-specific form         ← will show when metadata is available
        (custom panel)                    will read operator metadata from the operators slice
```

The three branches will be mutually exclusive. The Input and Output tabs will not change.
`Canvas.tsx` is not part of this hierarchy.

No new SCSS modules are expected. The Carbon `InlineLoading` and `InlineNotification` components will
supply spacing and color through tokens. Any wrapper spacing will use `$spacing-*` tokens,
with no hex or px literals.

## User Interaction and State

| Trigger | Current behavior | Planned behavior |
|---|---|---|
| Canvas mounts with empty metadata | An effect calls `getOperatorMetadata(dispatch)`. No properties panel loading state is set. | The same effect stays. Before the `try` block, the action will dispatch `clearError()` and `setLoading(true)`, so an error left by an earlier failed fetch is not paired with `loading=true`. `CommonPropertiesPanel` will show the loading state while the request is in flight. |
| Request succeeds | The action dispatches `setOperatorMetadata`, which sets `metadata`, `loading=false`, `error=null`. | No change to the action. `CommonPropertiesPanel` will re-render and show the form. |
| Request succeeds with no metadata for the selected node's operator (an empty map, or a map without that operator) | Same dispatch. The panel renders a form with no options. | No change to the action. `CommonPropertiesPanel` will show the error state. |
| Request fails | The action logs the error. The store is unchanged. | The action will dispatch `setError` with a generic message, which sets `error` and `loading=false`. `CommonPropertiesPanel` will re-render and show the error state. |
| User opens a node (double-click or node context menu) | Canvas `openWithParamDef` opens the panel. | No change to Canvas. `CommonPropertiesPanel` will mount and show loading state, error, or form from the current slice state. |

## Decisions

### Deliver the single source of truth before the loading and error state

PR 1 (Redux as the single source of metadata) will merge before PR 2 (loading and error
state). If PR 2 merged first, `CommonPropertiesPanel` would follow the Redux slice and swap
the loading state for the form as soon as the slice flips to loaded, while the custom panels
would still read `controller.getAppData()`. If `appData` were stale at that moment, the form
would appear with empty options and no loading indicator, which is worse than the current
behavior because the UI would signal that it is ready. Merging PR 1 first means each PR is
correct when merged on its own, and PR 1 changes nothing the user can see. PR 2 should be
raised right after PR 1.

### Redux is the single source of operator metadata for the properties panel

Any usage of operator metadata in the properties panel components, including
`CommonPropertiesPanel` and the custom panels, will use the `operators` slice with
`useAppSelector` and the renamed `selectX` selectors of the slice. No properties panel component
will read `operatorMetadata` through `controller.getAppData()`. Other data that Canvas
places in `appData`, such as `nodeId`, `pipelineFlow`, and `nodeFeatureMap`, will still be
read from `appData`. Canvas will not pass loading or error state through `appData`. This
will keep Canvas unchanged. An open panel will re-render on every transition (pending to
loaded, pending to failed) through the Redux usage, with no extra update to
`propertiesInfo`. It will also leave `parameterDef` untouched, so Elyra will not re-run
`setForm` or reset UI state.

The loading and error state depends on the Redux store, so reading the form options from a
second source could show a form with empty options at the moment the slice flips to loaded.

### Rename all selectors in the operators slice to selectX, and not the API action

`getOperatorMetadata` names both the API action in `operator-actions.ts` and the Redux
selector in `operatorsSlice.ts`. In PR 1, every selector in `operatorsSlice.ts` will be
renamed from `getX` to `selectX`, and every use of them will follow:

| Current name | New name |
|---|---|
| `getOperatorMetadata` | `selectOperatorMetadata` |
| `getOperatorsLoading` | `selectOperatorsLoading` |
| `getOperatorsError` | `selectOperatorsError` |
| `getNodeFeatures` | `selectNodeFeatures` |
| `getFeaturesLoading` | `selectFeaturesLoading` |
| `getNodeFeaturesForNode` | `selectNodeFeaturesForNode` |

`selectOperatorMetadata` is the name `Canvas.tsx` already uses through an import alias, so the
rename removes that alias. Renaming all six keeps one naming convention in the slice. Only
`getOperatorMetadata` is imported outside the slice file (by `Canvas.tsx`), so the rename is
safe in one PR. The API action keeps its name.

### Spec delta modifies three existing requirements

The delta uses `ADDED Requirements` for the loading and error state, which have no canonical
equivalent. It also uses `MODIFIED Requirements` for three canonical requirements whose
current wording would contradict the new behavior once archived:

- `Three-tab structure`: the "Configuration tab is default" scenario currently says the
  operator-specific form is visible when the panel opens. That is no longer true while the
  metadata is pending or failed.
- `Operator-specific configuration panel`: currently says the Configuration tab always renders
  the operator-specific form. It will render the form once the metadata is available.
- `General operator configuration lifecycle`: step 1 currently reads metadata from controller
  `appData`. It will read operator metadata from the Redux `operators` slice with a new
  scenario for it.

### State derivation

The Configuration tab will derive its branch from `loading` and from whether `metadata` has an
entry for the operator of the selected node ("populated"). `error` does not select the branch.
The endpoint returns the metadata of all operators at once, so the panel checks only the entry
of its own node. A map that is `{}`, or that lacks this operator, is "empty".

| `metadata` for the node's operator | `loading` | `error` | Branch | Case |
|---|---|---|---|---|
| populated | any | any | Operator-specific form | Normal case. |
| empty | true | any | Loading state | The request is in flight. |
| empty | false | non-null | Error state | The request failed. |
| empty | false | null | Error state | Edge case: the request succeeded but the metadata has no entry for the node's operator. |

Two checks run in this order. If the metadata is populated, the form is shown. Otherwise, if
`loading` is true, the loading state is shown. Anything else is the error state, so it is the
fallthrough and not a check of its own. The populated check runs first so that an error can
never hide a form that already has its data.

An operator with no registered configuration panel is a different case. It still shows the
placeholder whatever the metadata is, because the panel checks for a registered panel first and
applies the metadata check only to operators that have one.

`loading` can be relied on because `getOperatorMetadata` is called only from `Canvas.tsx`,
which mounts before a user can open a panel, and because the action dispatches
`setLoading(true)` before the request while `setOperatorMetadata` and `setError` both clear it.

### Clear the previous error when the fetch starts

The `operators` slice outlives the Canvas page, and `setLoading(true)` does not clear `error`.
After a failed fetch, a later Canvas mount would start a new request with the old error still
in the store. The fetch action will therefore dispatch `clearError()` together with
`setLoading(true)` before the request, so `loading=true` is never paired with an earlier error.
The panel does not depend on this, because it checks `loading` before the error state. It is
done in the action and not on panel mount. A panel that mounts again while Canvas stays
mounted starts no new request, so a failed fetch must keep showing its error there.

### Save gating

The form will not be rendered in the loading and error states, so the panel's
required-field evaluation will have nothing to read. The panel will call
`controller.setSaveButtonDisable(true)` for those branches and re-evaluate required fields
when the form appears.

### Generic error message

The fetch action will store a fixed, user-facing message in `error` instead of the raw
Axios error. This will keep status codes and backend text out of the UI. The raw error will
continue to go to `logUtil.error`, as it currently does.

### Keeping the no-throw behavior

Currently, the comment in `getOperatorMetadata` explains that rethrowing caused a remount
loop through React's global error handler. The planned failure handling will therefore
report the failure through `setError` and will not throw.

### Internationalization

The new user-facing strings will be defined with `defineMessages()` and
rendered with `intl.formatMessage`, as required by the canonical `frontend/i18n` spec.

## Risks and Trade-offs

- **A failed fetch will leave properties panels unusable until the Canvas page mounts
  again:** Accepted because retry is out of scope. The error message will tell the user
  the configuration could not be loaded.
- **The loading state depends on `setLoading(true)` running before the request is issued:**
  Otherwise a panel opened in that window would show the error state for a request that is in
  flight. It will be dispatched synchronously before the `try` block, and covered by a test in
  `operator-actions.test.ts`.
- **No retry while Canvas stays mounted:** `metadataFetchedRef` in Canvas is a per-mount
  `useRef` that currently exists and will not change. After a failure, the fetch is not
  attempted again until Canvas mounts again with no metadata loaded.
- **The no-throw behavior is what prevents a request loop:** `getOperatorMetadata`
  currently absorbs errors because a rethrown error would reach React's global error
  handler in development, remount Canvas, reset `metadataFetchedRef`, and fetch again in an
  endless loop. The planned `setError` dispatch must stay inside the existing `catch` and
  must not rethrow.
- **Wider change surface in PR 1:** Currently, `CommonPropertiesPanel` and custom panels
  read `operatorMetadata` through `controller.getAppData()`. All of them will change to
  use the Redux store, and so will the affected unit test files under
  `frontend/tests/unit/components/PropertiesPanel/`. The change per panel is the same single
  read, and each panel keeps its existing behavior. This will be verified by the existing
  panel tests passing after they supply metadata through the store, and by a manual check
  that an open panel still receives its options when the response arrives.
- **Nodes dropped before the metadata arrives still get no defaults:** `applyNodeDefaults`
  currently skips a node when `operatorMetadata` has no attributes for its operator, and
  nothing retries. The loading state hides the form while the request is in flight, but it
  does not write defaults. This is out of scope because fixing it changes Canvas behavior
  (see the non-goals in the proposal).
- **Unused `appData.operatorMetadata`:** Canvas will keep placing `operatorMetadata` in
  `appData`, and nothing in the properties panel will read it. This is left in place to keep
  Canvas unchanged and can be removed in a separate cleanup.
- **First use of Redux in the properties panel components:** The panels must render inside
  the Redux provider. They are rendered by Elyra from within the Canvas React tree, which
  is expected to provide it. This will be confirmed during implementation of PR 1.
