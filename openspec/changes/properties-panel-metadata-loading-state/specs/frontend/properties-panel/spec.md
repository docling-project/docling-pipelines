# Spec Delta

## ADDED Requirements

### Requirement: Configuration tab loading state while operator metadata is pending
The Configuration tab SHALL display a loading state in place of the operator-specific
form whenever the operator metadata has not yet been received and the metadata fetch has
not failed. The loading state SHALL be exposed as a status message. While it is shown, the panel Save button SHALL be disabled. The tab headers, the editable display name, and the Input and Output tabs SHALL remain available.

#### Scenario: Panel opened while metadata is pending
- **WHEN** the user opens the panel for an operator node while the operator metadata request is still in flight
- **THEN** the Configuration tab shows a loading state, no operator fields are rendered, and the Save button is disabled

#### Scenario: Form replaces loading state when metadata arrives
- **WHEN** the operator metadata arrives while the panel is open and showing the loading state
- **THEN** the loading state is replaced by the operator form, including metadata-driven options such as the Ingest provider list

#### Scenario: Metadata already loaded
- **WHEN** the user opens the panel after the operator metadata has been loaded
- **THEN** the operator form renders immediately and no loading state is shown

#### Scenario: Other tabs stay usable while loading
- **WHEN** the Configuration tab is showing the loading state and the user selects the Input or Output tab
- **THEN** that specific tab renders its own content as usual

#### Scenario: Loading state is announced
- **WHEN** the Configuration tab enters the loading state
- **THEN** the loading indicator is exposed with an accessible status message

### Requirement: Configuration tab error state when operator metadata fails to load
The Configuration tab SHALL display an error state in place of the operator-specific form
when the operator metadata fetch has failed. The error state SHALL replace the loading
state, SHALL state that the operator configuration could not be loaded, SHALL be exposed
as an alert, and SHALL NOT expose technical error details to the
user. While it is shown, the panel Save button SHALL be disabled so that unrendered
fields cannot overwrite the node's existing configuration.

#### Scenario: Fetch fails before the panel is opened
- **WHEN** the operator metadata request has failed and the user opens the panel for an operator node
- **THEN** the Configuration tab shows the error state, no operator fields are rendered, and the Save button is disabled

#### Scenario: Fetch fails while the panel shows the loading state
- **WHEN** the operator metadata request fails while the panel is open and showing the loading state
- **THEN** the loading state is replaced by the error state and the Save button remains disabled

#### Scenario: Error details are not shown
- **WHEN** the error state is displayed
- **THEN** the message is generic and does not include status codes, stack traces, or backend error text

#### Scenario: Error state is announced
- **WHEN** the Configuration tab enters the error state
- **THEN** the error message is exposed as an alert

#### Scenario: Existing node configuration is preserved
- **WHEN** the user opens a node that already has saved parameters while the Configuration tab is in the loading or error state, and then closes the panel
- **THEN** the node's saved parameters are unchanged
