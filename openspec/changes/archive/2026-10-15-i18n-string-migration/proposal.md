# Proposal

## Why

The Docling Pipelines frontend had user-facing strings hard-coded directly inside React
components, pages, and string-valued display constants. This created several problems:

- No single source of truth for display text. The same label could be worded differently
  across components with no way to enforce consistency.
- The UI was not translatable. Hard-coded literals cannot be swapped for locale-specific
  values without modifying every file that contains them.
- Unit tests that rendered components containing `intl.formatMessage` calls failed because
  `IntlProvider` was not present in the test environment.
- String-valued constants used as display labels were duplicated between the constants
  layer and the components that consumed them.

The i18n infrastructure (`IntlProvider`, `loadMessages`, `messages_en.json`, Elyra canvas bundle
merging) was already established before this migration. This change completes the migration
of all remaining hard-coded user-facing strings into that existing infrastructure.

## What Changes

- All user-facing string literals across components, pages, and the PropertiesPanel are
  served via the centralised message catalogue using co-located `<Component>.messages.ts`
  files and `intl.formatMessage`.
- String-valued display constants previously used as rendered labels are migrated into the
  catalogue and removed from the constants layer.
- Unit tests adopt `renderWithProviders` to supply `IntlProvider` in the test environment.
- All message IDs and their English default strings are registered in `messages_en.json`.

## Capabilities

### New Capabilities

- `frontend/i18n`: All user-facing strings across pages, components, and display constants
  are served via the centralised message catalogue. Components define their strings in
  co-located `<Component>.messages.ts` files using `defineMessages()`. The catalogue is the
  single source of truth for all rendered text in the application.

### Modified Capabilities

None. The i18n infrastructure itself (`IntlProvider`, `loadMessages`, `messages_en.json`)
is not modified by this change. Only the components and pages consuming it are updated.

## Impact

This change is frontend-only. It does not affect:
- Routing under `/ui`
- BFF proxy routes
- Redux state slices
- Backend REST API routes, operators, or storage adapters

Affected frontend areas: `frontend/src/components/`, `frontend/src/pages/`,
`frontend/src/constants/`, and `frontend/tests/unit/`. The full PropertiesPanel subtree
is in scope; the 4 largest custom panel files are covered by a subsequent task in this
change.

## Non-goals

- This change does not add support for any locale beyond English (`en`). Adding a new locale
  requires a new `messages_<locale>.json` file and is deferred to a future change.
- This change does not migrate Elyra canvas internal strings. Those are served from Elyra's
  own locale bundles, which are already merged into the app message map by `loadMessages`.
- This change does not migrate backend error messages or API response strings surfaced in the
  UI. Those originate from the Python backend and are out of scope for frontend i18n.
- This change does not introduce pluralisation rules, ICU message syntax beyond simple
  variable interpolation, or right-to-left layout support.
