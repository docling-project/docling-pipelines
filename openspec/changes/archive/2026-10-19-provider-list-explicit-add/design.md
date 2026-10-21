# Design

## Context

`ProviderFieldsForm` renders one control per property in a provider schema; `list` properties used the shared `TagInput`, which commits on blur. The form is used by the Ingest Source, PII and HAP, Chunker, and Document Classifier panels. Values flow through the form's `onChange(fieldKey, value)` callback into the panel's local state and then `controller.updatePropertyValue()` on the Elyra canvas controller; `list` values are persisted as `string[]`. See proposal.md for motivation.

## Goals / Non-Goals

**Goals:**
- Make commit an explicit user action for provider `list` fields while keeping the persisted `string[]` shape unchanged.
- Follow existing project conventions: Carbon components, SCSS modules with Carbon tokens, react-intl message descriptors, barrel exports, `renderWithProviders` in tests.

**Non-Goals:**
- Changing `TagInput`, which keeps its blur commit for its other usages.
- Changing how panels persist values or the shape of provider config.

## Decisions

### Component hierarchy

```
ProviderFieldsForm (list field)
└── ListInput
    ├── div.inputRow
    │   ├── TextInput           (invalid / invalidText for duplicates)
    │   └── Button kind=tertiary (Add icon)
    └── div.tableWrapper        (rendered only when items exist)
        ├── Table
        │   ├── TableHead > TableHeader   (title)
        │   └── TableBody > TableRow*
        │       ├── TableCell   (value)
        │       └── TableCell > IconButton + SubtractAlt (remove)
        └── Pagination          (rendered only when more than one page)
```

### Interaction map

No Redux action, thunk, or API client call is involved. Everything runs through the form's existing callback chain.

| User interaction | Handler | Result |
|---|---|---|
| Type or paste | `setInputValue`, clear duplicate state | Text held in local component state only |
| Blur | none | Nothing happens by design |
| Enter, comma, or Add | `commit` | Trim and strip trailing commas; reject duplicates; else `onChange([...items, value])`, jump to the new page, clear input |
| Remove | `handleRemove` | `onChange(items without value)` |
| Pagination | `setPage` | Local page index only |

`onChange` reaches `controller.updatePropertyValue()` through the panel, unchanged from before.

### New `ListInput` component rather than a flag on `TagInput`

The Add button, table, and pagination are a different layout from chips. Adding modes to `TagInput` would put two interaction models in one component and risk regressions in its four existing usages. A separate component keeps `TagInput` untouched.

### Explicit duplicate handling

A duplicate keeps the text and sets `invalid` / `invalidText` on the Carbon `TextInput`, so the error is announced and the user can edit instead of retyping. Silent clearing was rejected in review.

### Carbon `Pagination` for the table

Reuses the same component `SharedDataTable` uses instead of a custom pager. The page size is fixed at 5 with a single page-size option.

### Styling

- New module `ListInput.module.scss`: input row layout, table wrapper, cell alignment.
- Table rows use the `$field` token so they match the `TextInput` background in every theme; spacing uses `$spacing-*` tokens. No hex or px literals.
- New `.fullWidthAccordion` class in `CommonPropertiesPanel.module.scss` overrides Carbon's 25% content end padding for the Ingest Source accordion, matching the existing VectorDB override. Other panels can adopt it later.

### Internationalization

All user-facing strings live in `ListInput.messages.ts` (`defineMessages`) and are rendered with `intl.formatMessage`; `messages_en.json` is regenerated with `npm run extract:messages`. This includes the Pagination labels.

## Risks / Trade-offs

- [All provider `list` fields change, not only Ingest Source Paths] → Intended: the blur problem applies to every such field, and one rendering path avoids drift. Called out in the proposal impact.
- [Existing tests that render `ProviderFieldsForm` need an intl context because `ListInput` uses `useIntl`] → Tests use `renderWithProviders`.
- [A user who types a value and never clicks Add loses it on Save] → Accepted trade-off of explicit commit, specified as "Pending text is not saved". The enabled Add button and helper text make the pending state visible. Warning on Save would need a hook into Elyra's Save and is out of scope.
- [Nested required list fields are not enforced on Save] → Pre-existing and outside `ListInput`: `hasAnyRequiredParamMissing` only checks top-level operator attributes, so `paths` inside `provider_config` is checked by the backend instead (`FilesystemConfig.validate_paths`). The `list-input` spec only guarantees that pending text is never reported as a value. Out of scope here.
- [Fixed page size of 5 may not suit very long lists] → Acceptable for path-style lists; revisit if a field needs larger lists.
