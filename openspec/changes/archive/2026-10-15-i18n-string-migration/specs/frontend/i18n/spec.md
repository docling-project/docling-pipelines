# Spec Delta

## Purpose

The i18n capability establishes the centralised message catalogue as the single source of
truth for all user-facing strings in the Docling Pipelines frontend. All components, pages,
and panels SHALL serve their displayed text via the catalogue rather than hard-coded string
literals or string-valued constants.

## ADDED Requirements

### Requirement: All user-facing strings served via the message catalogue
Every user-facing string rendered by a component, page, or panel SHALL be defined in a
co-located `<Component>.messages.ts` file using `defineMessages()` and resolved at runtime
via `intl.formatMessage`. Hard-coded string literals SHALL NOT appear as rendered text in
any component, page, or panel.

#### Scenario: Component renders via catalogue
- **WHEN** a component mounts and displays a label, heading, button text, or error message
- **THEN** the displayed string is resolved from the message catalogue via `intl.formatMessage` and not hard-coded in the TSX

#### Scenario: Hard-coded string absent from rendered output
- **WHEN** the source of a component is inspected
- **THEN** no string literal that would appear as rendered user-facing text is present
  outside of a `defineMessages()` definition

### Requirement: Message IDs follow the dot-namespaced path convention
Every message ID SHALL follow the pattern `src.<path>.<ComponentName>.<key>` where
`<path>` is the dot-separated directory path relative to `frontend/src`, and
`<ComponentName>` is the component name. When the component name is the same as its
parent folder name, the folder name SHALL identify the component and the ID segment SHALL
use it once without repetition.

#### Scenario: ID follows path convention
- **WHEN** a message is defined in `src/components/common/DeleteModal/DeleteModal.messages.ts`
- **THEN** its ID begins with `src.components.common.DeleteModal.` followed by the message key

#### Scenario: No repeated component name in ID
- **WHEN** the component file and its parent folder share the same name
- **THEN** the component name appears only once in the message ID

### Requirement: Dynamic values parameterized with ICU placeholders
Any value that changes at runtime, including counts, names, dates, and status labels,
SHALL be passed as an ICU variable placeholder in the message `defaultMessage`. String
concatenation around dynamic values SHALL NOT be used.

#### Scenario: Count rendered via placeholder
- **WHEN** a component displays a count alongside static text
- **THEN** the full sentence is defined as a single message with an ICU placeholder
  (e.g. `'You have {count} flows'`) and the count is passed as a parameter to
  `intl.formatMessage`

#### Scenario: No string concatenation with dynamic values
- **WHEN** the source of a component is inspected
- **THEN** no dynamic runtime value is concatenated with a string literal to produce
  rendered text

### Requirement: Inline elements passed as rich text parameters
When a rendered string requires inline HTML elements for styling (e.g. `<b>`), the element
SHALL be passed as a rich text parameter to `intl.formatMessage`. The message
`defaultMessage` SHALL contain the element tag as a placeholder. The string SHALL NOT be
split into multiple message keys and concatenated around the element.

#### Scenario: Bold text rendered via rich text parameter
- **WHEN** a component renders a string containing bolded text
- **THEN** the full sentence is a single message definition containing the element tag
  as a placeholder, and the element is passed as a parameter to `intl.formatMessage`

### Requirement: `messages_en.json` populated via extraction script only
The file `frontend/src/i18n/messages_en.json` SHALL be updated by running
`npm run extract:messages` and SHALL NOT be edited manually. All message IDs and their
English `defaultMessage` values SHALL be present in `messages_en.json` after extraction.

#### Scenario: New messages appear in catalogue after extraction
- **WHEN** new `defineMessages()` definitions are added and `npm run extract:messages` is run
- **THEN** the new message IDs and their `defaultMessage` values appear in `messages_en.json`

#### Scenario: Manual edits not permitted
- **WHEN** `npm run extract:messages` is run after a manual edit to `messages_en.json`
- **THEN** the extraction overwrites the file, discarding any manually added entries
  not backed by a `defineMessages()` definition

### Requirement: String-valued display constants migrated into the catalogue
String-valued constants used directly as rendered labels SHALL be migrated into the
message catalogue. The constant SHALL be removed from the constants layer and the
consuming component SHALL use `intl.formatMessage` with the corresponding message
definition in its place.

#### Scenario: Status label resolved via catalogue
- **WHEN** a component renders a status label previously sourced from a string constant
- **THEN** the label is resolved via `intl.formatMessage` and the originating string
  constant no longer exists in the constants layer

### Requirement: Unit tests supply `IntlProvider` via `renderWithProviders`
Any unit test that renders a component consuming `intl.formatMessage` SHALL use the
`renderWithProviders` helper in place of a bare `render` call. The helper SHALL supply
`IntlProvider` with the `en` locale and `messages_en.json` to the component under test.

#### Scenario: Test renders migrated component without error
- **WHEN** a unit test renders a component that uses `intl.formatMessage`
- **THEN** the test uses `renderWithProviders` and the component renders without a
  missing `IntlProvider` context error

#### Scenario: Bare render causes test failure
- **WHEN** a unit test renders a component using `intl.formatMessage` with a bare `render`
  call and no `IntlProvider` in the tree
- **THEN** the test fails with a missing context error
