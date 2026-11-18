# frontend/state/notifications-slice Specification

## Purpose

The notifications-slice capability is the Redux slice that manages the global notification system. It implements a three-tier notification pattern: global toasts (visible in `ToastContainer`), a history panel (append-only log for the current session), and notification preferences. Inline `InlineNotification` components rendered directly in JSX are outside this slice's scope. The slice assigns `id` and `timestamp` to every notification — callers never provide them.

## Requirements

### Requirement: Adding a notification writes to both active and history
`addNotification` SHALL append the new notification to `active` (shown as a toast) AND prepend it to `history` (newest-first in the history panel), and SHALL increment `unreadCount` by 1. The slice SHALL generate a unique `id` (UUID v4 when `crypto.randomUUID` is available, otherwise a timestamp-based fallback) and an ISO 8601 `timestamp`. Callers provide `kind`, `title`, and optional `subtitle`, `caption`, and `dismissAfter`.

#### Scenario: Notification appears in both active and history
- **WHEN** `addNotification` is dispatched
- **THEN** the notification appears in `state.active` and at the head of `state.history`, and `unreadCount` is incremented by 1

#### Scenario: Slice assigns id and timestamp
- **WHEN** `addNotification` is dispatched
- **THEN** the resulting entry has a non-empty `id` and a non-empty `timestamp`; neither was provided by the caller

### Requirement: Removing an active notification preserves history
`removeNotification` SHALL remove the entry with the matching `id` from `active`. The entry SHALL remain in `history` — dismissing a toast does not erase the history record.

#### Scenario: Dismissed toast removed from active only
- **WHEN** `removeNotification` is dispatched with a notification ID
- **THEN** the entry is absent from `state.active` but still present in `state.history`

### Requirement: Clearing active notifications preserves history
`clearActiveNotifications` SHALL empty the `active` array. The `history` array and `unreadCount` SHALL be unchanged.

#### Scenario: clearActiveNotifications empties active only
- **WHEN** `clearActiveNotifications` is dispatched
- **THEN** `state.active` is empty and `state.history` is unchanged

### Requirement: Clearing history resets unread counter
`clearHistory` SHALL empty the `history` array AND reset `unreadCount` to 0.

#### Scenario: clearHistory empties history and resets counter
- **WHEN** `clearHistory` is dispatched
- **THEN** `state.history` is empty and `state.unreadCount` is 0

### Requirement: Marking history read resets unread counter only
`markHistoryRead` SHALL set `unreadCount` to 0. The `history` array SHALL be unchanged.

#### Scenario: markHistoryRead clears counter without clearing history
- **WHEN** `markHistoryRead` is dispatched after notifications have accumulated
- **THEN** `state.unreadCount` is 0 and `state.history` still contains all previous entries

### Requirement: Preferences support partial updates
`setPreferences` SHALL merge the provided partial `NotificationPreferences` into the current preferences, updating only the keys that are supplied. The default preference values are `autoDismiss: true` and `dismissDelay: 5000`.

#### Scenario: Partial preference update preserves unmodified keys
- **WHEN** `setPreferences` is dispatched with only `{ autoDismiss: false }`
- **THEN** `state.preferences.autoDismiss` is `false` and `state.preferences.dismissDelay` remains unchanged
