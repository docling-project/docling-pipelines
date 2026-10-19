# Spec Delta

## ADDED Requirements

### Requirement: Values are committed only on explicit action
The component SHALL hold typed or pasted text in its input until the user commits it by pressing Enter, pressing comma, or activating the Add button. Losing focus SHALL NOT commit, alter, or clear the pending text.

#### Scenario: Blur keeps pending text
- **WHEN** the user pastes a folder path into the input and moves focus to another window or control
- **THEN** no value is added and the pasted text is still in the input when focus returns, so the user can append to it

#### Scenario: Enter commits pending text
- **WHEN** the user types a value and presses Enter
- **THEN** the trimmed value is added to the list and the input is cleared

#### Scenario: Comma commits pending text
- **WHEN** the user types a value and presses the comma key
- **THEN** the value is added without the comma and the input is cleared

#### Scenario: Add button commits pending text
- **WHEN** the user types a value and activates the Add button
- **THEN** the trimmed value is added to the list and the input is cleared

### Requirement: Pending text is not part of the value
The component SHALL report only committed values to its owner. Pending uncommitted text SHALL NOT be reported, so an owner that persists the value or checks it for emptiness treats a list with only pending text as empty.

#### Scenario: Pending text is not saved
- **WHEN** the user has text in the input that was never committed and the owner saves its form
- **THEN** the pending text is not added to the list and is not persisted; only committed values in the table are saved, and the Add button remains enabled to indicate the text is still pending

#### Scenario: Pending text does not satisfy a required list
- **WHEN** a list with no committed values has pending text in its input
- **THEN** the value reported to the owner is the empty list

### Requirement: Add button availability
The component SHALL always display an Add button next to its input, and SHALL disable it while the input contains no non-whitespace text.

#### Scenario: Add disabled when input is empty
- **WHEN** the input is empty or contains only whitespace
- **THEN** the Add button is visible and disabled

#### Scenario: Add enabled when input has text
- **WHEN** the input contains non-whitespace text
- **THEN** the Add button is enabled

### Requirement: Duplicate values are rejected visibly
The component SHALL NOT add a value that is already in the list. It SHALL keep the typed text and mark the input invalid with a message naming the duplicate, until the user edits the input.

#### Scenario: Duplicate shows invalid state
- **WHEN** the user commits a value that already exists in the list
- **THEN** the list is unchanged, the typed text remains, and the input shows an invalid state with a message that the value has already been added

#### Scenario: Editing clears the invalid state
- **WHEN** the user edits the input after a duplicate was rejected
- **THEN** the invalid state and message are removed

### Requirement: Committed values listed in a paginated table
The component SHALL list committed values in a table below the input, with a title, at most 5 rows per page, pagination controls when more than one page exists, and a remove control on each row. The table SHALL be hidden when the list is empty.

#### Scenario: Value appears in the table
- **WHEN** a value is committed
- **THEN** it appears as a row in the table with a remove control

#### Scenario: Newly added value is visible
- **WHEN** the user adds a value that falls on a later page than the one shown
- **THEN** the table switches to the page containing the new value

#### Scenario: Remove deletes the value
- **WHEN** the user activates the remove control on a row
- **THEN** that value is removed from the list reported to the owner

#### Scenario: Table hidden when empty
- **WHEN** the list contains no values
- **THEN** no table is rendered

### Requirement: Accessibility
The component SHALL expose an accessible name on its input, and SHALL expose the Add button, each remove control, and the pagination controls as keyboard-operable buttons with accessible names.

#### Scenario: Input has an accessible name
- **WHEN** the component is rendered
- **THEN** its input has an accessible name matching the supplied label

#### Scenario: Controls reachable by keyboard
- **WHEN** the user tabs through a component that contains values
- **THEN** focus reaches the input, the Add button, each remove control, and the pagination controls, each operable with Enter or Space
