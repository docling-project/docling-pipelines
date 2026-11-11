# Tasks

The i18n migration is split across multiple changes covering different areas of the
frontend. Task 5 covers spec validation and archiving, which is handled in the first PR once the spec artifacts are reviewed and stable. Migration tasks 1–4 continue in subsequent PRs against the canonical spec.

## 1. Migrate `src/components`

- [x] 1.1 Create co-located `<Component>.messages.ts` files for all components under
  `frontend/src/components/` (excluding PropertiesPanel) using `defineMessages()`. Replace
  all hard-coded user-facing string literals with `intl.formatMessage` calls. Where a
  component imports string-valued display constants as rendered labels, migrate those
  constants into the message catalogue and remove them from the constants layer.
- [x] 1.2 Update affected unit tests under `frontend/tests/unit/components/` (excluding
  PropertiesPanel) to use `renderWithProviders` in place of bare `render` calls so that
  `IntlProvider` is available in the test environment.
- [x] 1.3 Run `npm run extract:messages` from `frontend/` to extract all new message
  definitions into `messages_en.json`. Verify no message IDs are manually added or edited
  in `messages_en.json`.
- [x] 1.4 Run `npm run lint` and `npm run test:coverage` in `frontend/` and verify all
  unit tests pass.

## 2. Migrate `src/pages`

- [x] 2.1 Create co-located `<Page>.messages.ts` files for all pages under
  `frontend/src/pages/` using `defineMessages()`. Replace all hard-coded user-facing string
  literals with `intl.formatMessage` calls. Where a page imports string-valued display
  constants as rendered labels, migrate those constants into the message catalogue and
  remove them from the constants layer.
- [x] 2.2 Update affected unit tests under `frontend/tests/unit/` for migrated pages to
  use `renderWithProviders`.
- [x] 2.3 Run `npm run extract:messages` from `frontend/` to extract new page message
  definitions into `messages_en.json`.
- [x] 2.4 Run `npm run lint` and `npm run test:coverage` in `frontend/` and verify all
  unit tests pass.

## 3. Migrate PropertiesPanel (excluding 4 largest custom panels)

- [x] 3.1 Create co-located `<Component>.messages.ts` files for all PropertiesPanel
  components under `frontend/src/components/PropertiesPanel/` excluding the 4 largest
  custom panel files. Replace all hard-coded user-facing string literals with
  `intl.formatMessage` calls. Where a component imports string-valued display constants as
  rendered labels, migrate those constants into the message catalogue and remove them from
  the constants layer.
- [x] 3.2 Update affected unit tests under `frontend/tests/unit/components/PropertiesPanel/`
  to use `renderWithProviders`.
- [x] 3.3 Run `npm run extract:messages` from `frontend/` to extract new PropertiesPanel
  message definitions into `messages_en.json`.
- [x] 3.4 Run `npm run lint` and `npm run test:coverage` in `frontend/` and verify all
  unit tests pass.

## 4. Migrate remaining 4 largest PropertiesPanel custom panel files

- [x] 4.1 Create co-located `<Component>.messages.ts` files for the 4 largest PropertiesPanel
  custom panel files. Replace all hard-coded user-facing string literals with
  `intl.formatMessage` calls. Where a component imports string-valued display constants as
  rendered labels, migrate those constants into the message catalogue and remove them from
  the constants layer.
- [x] 4.2 Update affected unit tests to use `renderWithProviders`.
- [x] 4.3 Run `npm run extract:messages` from `frontend/` to extract remaining message
  definitions into `messages_en.json`.
- [x] 4.4 Run `npm run lint` and `npm run test:coverage` in `frontend/` and verify all
  unit tests pass.

## 5. Spec validation and archiving

- [x] 5.1 Run `openspec validate i18n-string-migration --strict` and resolve any failures
  in the spec artifacts.
- [x] 5.2 Run `openspec archive i18n-string-migration` once the spec artifacts are
  reviewed and stable to merge the spec delta into `openspec/specs/frontend/i18n/` and
  move this change to `openspec/changes/archive/`. Migration tasks 1–4 continue against
  the canonical spec after archiving.
