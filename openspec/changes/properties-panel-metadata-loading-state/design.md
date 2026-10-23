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
- The slice exports the selectors `getOperatorMetadata`, `getOperatorsLoading`, and
  `getOperatorsError`.

### Planned change

The implementation will be delivered in two PRs, in this order.

PR 1, a single source of operator metadata (no user-visible change):
- Any usage of operator metadata in the properties panel components, including
  `CommonPropertiesPanel` and the custom panels, will read it from the slice instead of
  `controller.getAppData()`, so there is a single source of truth for the loading state,
  the error state, and the form options.

PR 2, loading and error state (depends on PR 1):
- The metadata action will set `loading` and `error` on the `operators` slice.
- `CommonPropertiesPanel` will read the error from the slice and render a loading, error,
  or form state in the Configuration tab.

`Canvas.tsx` will not change in either PR.

## Component Hierarchy

Planned structure:

```
CommonPropertiesPanel                  ← will read operators slice (metadata, error) via selectors
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
| Canvas mounts with empty metadata | An effect calls `getOperatorMetadata(dispatch)`. No properties panel loading state is set. | The same effect stays. The action will dispatch `setLoading(true)` before the request. |
| Request succeeds | The action dispatches `setOperatorMetadata`, which sets `metadata`, `loading=false`, `error=null`. | No change to the action. `CommonPropertiesPanel` will re-render and show the form. |
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
correct when merged on its own, and PR 1 changes nothing the user can see.

### Redux is the single source of operator metadata for the properties panel

Any usage of operator metadata in the properties panel components, including
`CommonPropertiesPanel` and the custom panels, will use the `operators` slice with
`useAppSelector` and the selectors the slice already exports. No properties panel component
will read `operatorMetadata` through `controller.getAppData()`. Other data that Canvas
places in `appData`, such as `nodeId`, `pipelineFlow`, and `nodeFeatureMap`, will still be
read from `appData`. Canvas will not pass loading or error state through `appData`. This
will keep Canvas unchanged. An open panel will re-render on every transition (pending to
loaded, pending to failed) through the Redux usage, with no extra update to
`propertiesInfo`. It will also leave `parameterDef` untouched, so Elyra will not re-run
`setForm` or reset UI state.

The loading and error state depends on the Redux store, so reading the form options from a
second source could show a form with empty options at the moment the slice flips to loaded.

### State derivation

The Configuration tab will derive its branch from slice state, in this order:

1. `error` is non-null: error state.
2. `metadata` is empty: loading state. This will also cover the window before the fetch
   action has dispatched `setLoading(true)`, so the first render after mount is never a
   flash of an empty form.
3. Otherwise: the operator-specific form.

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
- **PR 2 must not merge before PR 1:** Between the two PRs, the loading state and the form
  options would come from different sources. PR 2 depends on PR 1 and should be raised right
  after it.
- **Unused `appData.operatorMetadata`:** Canvas will keep placing `operatorMetadata` in
  `appData`, and nothing in the properties panel will read it. This is left in place to keep
  Canvas unchanged and can be removed in a separate cleanup.
- **First use of Redux in the properties panel components:** The panels must render inside
  the Redux provider. They are rendered by Elyra from within the Canvas React tree, which
  is expected to provide it. This will be confirmed during implementation of PR 1.
