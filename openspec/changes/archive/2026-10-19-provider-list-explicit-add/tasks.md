# Tasks

## 1. ListInput component

- [x] 1.1 [frontend] Add `ListInput` with `TextInput`, Add `Button`, table, remove `IconButton`, and Carbon `Pagination`; commit only on Enter, comma, or Add, never on blur. Verify with `ListInput.test.tsx` blur, Enter, comma, and Add cases.
- [x] 1.2 [frontend] Reject duplicates with `invalid` / `invalidText`, keeping the typed text and clearing the error on edit. Verify with the duplicate test in `ListInput.test.tsx`.
- [x] 1.3 [frontend] Jump to the page containing a newly added item. Verify with the page-jump test in `ListInput.test.tsx`.
- [x] 1.4 [frontend] Add `ListInput.module.scss` using Carbon tokens only (`$field`, `$spacing-*`), with the Add button on the input row and no table left border. Verify no hex or px literals with `grep` and a `sass` compile.
- [x] 1.5 [frontend] Add `ListInput.messages.ts` with `defineMessages`, use `intl.formatMessage` for every user-facing string including Pagination labels, and regenerate `messages_en.json` with `npm run extract:messages`. Verify the new ids appear in `messages_en.json`.

## 2. Provider form integration

- [x] 2.1 [frontend] Render `list` fields in `ProviderFieldsForm` with `ListInput`, and export `ListInput` and `JsonTextArea` through the `common` barrel. Verify `ProviderFieldsForm.test.tsx` and `IngestSource.test.tsx` pass.
- [x] 2.2 [frontend] Add the `fullWidthAccordion` class and apply it to the Ingest Source accordion so fields use the full panel width. Verify the compiled CSS contains the `.cds--accordion__content` override.

## 3. Validation

- [x] 3.1 [frontend] Run the component test suite (`npx vitest run tests/unit/components`) and verify all tests pass.
- [x] 3.2 [frontend] Run `npm run lint` and `npm run build`; verify no errors in changed files and a successful build.
- [x] 3.3 [frontend] Run `openspec validate provider-list-explicit-add --strict` and verify it reports the change as valid.

## Workflow follow-up

- Archive the change with `openspec archive provider-list-explicit-add` after PR #273 is approved, so the delta creates `openspec/specs/frontend/common/list-input/spec.md`.
- Verify the canonical list-input spec contains the new requirements after archive.
