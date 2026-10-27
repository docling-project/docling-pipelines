# Design

## Context

See the [proposal](proposal.md) for motivation for the behavioral contract. The i18n infrastructure (`IntlProvider`, `loadMessages`, `messages_en.json`, Elyra bundle merging) was already in place before this migration. This document describes the design decisions applied during the migration of all hard-coded user-facing strings into that infrastructure.

## Component Hierarchy

`IntlProvider` is mounted once at the app root, which wraps the entire React tree. All
components and pages below it consume messages via the `useIntl` hook.

```
<App>
  └── <IntlProvider messages={loadMessages(locale)} locale={locale}>
        ├── <Pages />         ← all src/pages/** components
        ├── <Components />    ← all src/components/** components
        └── <PropertiesPanel />
```

Carbon Design System components (`Modal`, `DataTable`, `Tearsheet`, `InlineNotification`,
etc.) receive already-resolved strings as props. They do not interact with `IntlProvider`
directly. String resolution always happens in the consuming component before being passed
down as a prop.

No new Carbon components were introduced by this migration. No new SCSS modules were
created and no Carbon design tokens were affected.

## User Interaction and State

This migration introduces no new user interactions, API calls, BFF proxy routes, Redux
actions, or state shape changes. Existing interactions are unchanged. Only the source of
the displayed string changes from a hard-coded literal to a catalogue lookup.

## Decisions

### Co-located message files using `defineMessages()`

Each component or page defines its strings in a sibling `<Component>.messages.ts` file
using `react-intl`'s `defineMessages()`. This keeps message definitions co-located with
the component that owns them, which makes it straightforward to find and update a string without searching `messages_en.json` directly.

```ts
// DeleteModal.messages.ts
import { defineMessages } from 'react-intl';

export const messages = defineMessages({
  title: {
    id: 'src.components.common.DeleteModal.title',
    defaultMessage: 'Delete {assetType}',
  },
});
```

The component then consumes the message via `intl.formatMessage`:

```ts
const intl = useIntl();
intl.formatMessage(messages.title, { assetType: 'project' });
```

### Extracting messages into `messages_en.json`

`messages_en.json` is never edited manually. After defining new messages in a
`<Component>.messages.ts` file, the catalogue is updated by running the extraction script from the `frontend/` directory:

```bash
npm run extract:messages
```

This scans all `defineMessages()` calls across the codebase and writes their IDs and
`defaultMessage` values into `messages_en.json`. Manual edits to `messages_en.json` would be overwritten on the next extraction run and create inconsistencies between the file and the source definitions.

### Message ID naming convention

Message IDs follow the dot-separated path of the source file relative to `frontend/src`, followed by the message key:

```
src.<path>.<ComponentName>.<key>
```

Where `<ComponentName>` is the component name as it appears in the file path. If the
component name is the same as its parent folder name, the folder already identifies the
component. The ID segment should use it once:

```
// Correct
src.components.Canvas.FlowRunHistoryTearsheet.title

// Incorrect — filename repeated
src.components.Canvas.FlowRunHistoryTearsheet.FlowRunHistoryTearsheet.title
```

This keeps IDs concise and avoids redundancy when the folder and filename share the same name, which is the standard component structure in this codebase.

### Dynamic values are parameterized with ICU placeholders

Any value that changes at runtime, such as counts, names, dates, status labels, is passed as an ICU variable placeholder rather than concatenated or hard-coded:

```ts
// Message definition
flowCount: {
  id: 'src.components.Home.SampleProjectModal.flowCount',
  defaultMessage: 'You have {count} flows',
},

// Usage
intl.formatMessage(messages.flowCount, { count: flows.length })
```

Splitting a sentence around a dynamic value (e.g. `"You have " + count + " flows"`) is
not used. Translators require the full sentence in context and word order differs between
languages.

### Inline elements passed as rich text parameters

When a string requires inline styling (e.g. `<b>`), the element is passed as
a rich text parameter rather than splitting the string into multiple message keys:

```ts
// Message definition
warning: {
  id: 'src.components.common.DeleteModal.warning',
  defaultMessage: 'This will <b>permanently delete</b> the item.',
},

// Usage
intl.formatMessage(messages.warning, {
  b: (chunks) => <b>{chunks}</b>,
})
```

Splitting the string around the styled word makes the sentence untranslatable because
translators cannot reorder the fragments. Passing the element as a parameter gives
translators the full sentence with a placeholder they can position correctly for their
locale.

### String-valued display constants migrated into the catalogue

String-valued display constants that were used directly as rendered labels were migrated
into the message catalogue and removed from the constants layer. Components that previously
imported these constants now call `intl.formatMessage` with the corresponding message
definition.

This removes the duplication between the constants layer and the components consuming them
and ensures all rendered text flows through a single source of truth.

### `renderWithProviders` for unit tests

Unit tests that render components consuming `intl.formatMessage` require `IntlProvider`
in the test environment. A shared `renderWithProviders` helper wraps the component under
test with `IntlProvider` (defaulting to the `en` locale and `messages_en.json`). All
affected unit tests were updated to use this helper in place of the bare `render` call
from `@testing-library/react`.

## Risks and Trade-offs

- **Message ID collisions with Elyra bundles:** `loadMessages` merges app messages over
  Elyra bundle messages, so app IDs always win on collision. The dot-namespaced `src.*`
  prefix makes accidental collisions with Elyra IDs unlikely in practice.
- **`messages_en.json` growth:** As the catalogue grows with every migrated component,
  the file becomes the single point of maintenance for all English strings. Keeping message definitions co-located in `<Component>.messages.ts` files mitigates this. `messages_en.json` is the serialised output, not the primary editing surface.
- **Missing `IntlProvider` in new tests:** Any future component test that omits
  `renderWithProviders` and uses a message key will fail with a missing `IntlProvider`
  context error. Unit test failures guard against this.
