# Tasks

## 1. Migration helper

- [ ] 1.1 Add a pure migration helper next to the StorageOutput panel (non-blank `credentials` values win, blanks ignored, Box `credentials_json_path` -> `credentials_path`, `credentials` key removed, nothing returned when there is nothing to migrate); verify with a unit test under `frontend/tests/unit/components/PropertiesPanel/StorageOutput/`.

## 2. Panel

- [ ] 2.1 Remove the Credentials field and its unused imports, variables and i18n messages from `StorageOutput.tsx`, `StorageOutput.messages.ts` and `messages_en.json`; stop writing `credentials: {}` on provider change.
- [ ] 2.2 Run the migration in a `useEffect` on panel open; verify manually that an old flow shows its values in the provider fields, cancel keeps the stored `credentials`, and save removes the key.

## 3. Validation

- [ ] 3.1 Run `npx vitest run`, `npm run lint` and `npm run build` in `frontend/`; verify no new failures.
