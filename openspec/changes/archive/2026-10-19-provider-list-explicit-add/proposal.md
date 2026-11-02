# Proposal

## Why

In the Ingest Source properties panel, the `Paths` field used a tag-style input that committed the pending text as a chip whenever the input lost focus. A user who builds a path across two copy-paste steps (paste a folder path, switch to a terminal to copy the filename, return to append it) lost the partial path the moment focus left: it became a chip and the input cleared. Pending text must only be committed by an explicit user action.

## What Changes

- Provider `list` fields in operator panels render an input with an explicit **Add +** button instead of a tag-style input. Pending text is committed only on Enter, comma, or Add; losing focus never commits or clears it.
- Committed values are listed in a paginated table below the input, each row with a remove button.
- A value that already exists is rejected: the typed text is kept and the input shows an invalid state with a message, instead of being silently cleared.
- After a value is added, the table shows the page that contains it.
- The shared provider form (`ProviderFieldsForm`) renders every `list` field this way. This covers Ingest Source `Paths` and also `list` fields in the PII and HAP, Chunker, and Document Classifier panels.

**Layer:** frontend-only.

**Carbon components:** `TextInput`, `Button` (tertiary, `Add` icon), `Table`, `IconButton`, `Pagination`.

## Capabilities

### New Capabilities

- `frontend/common/list-input`: the shared `ListInput` component commits values only through an explicit action, rejects duplicates visibly, lists committed values in a paginated table, and is keyboard accessible. Specified under `common/` alongside `vault-input` and `shared-data-table`, because the component is a reusable primitive rather than part of the properties panel.

### Modified Capabilities

None.

## Impact

- Frontend components: new shared `ListInput` component under `frontend/src/components/common/`; `ProviderFieldsForm` switched to use it; `JsonTextArea` and `ListInput` exported through the `common` barrel; new message catalogue for the component's user-facing strings; accordion content in the Ingest Source panel uses the full panel width.
- No routing under `/ui`, BFF proxy routes, Redux slices, or backend APIs are affected. Persisted values stay a `string[]` on the existing provider config attribute.
- Implemented in PR #273; this change records the behavioral contract.

## Non-goals

- Changing `TagInput` or its other usages (Extract, Storage Output, project and flow dialogs).
- Backend, operator metadata, or flow JSON changes.
- Splitting or reordering values, or validating path syntax; entries are stored as typed after trimming.
- Specifying how `ProviderFieldsForm` or the individual operator panels use `ListInput`, or changing how Save is gated for nested required fields.
