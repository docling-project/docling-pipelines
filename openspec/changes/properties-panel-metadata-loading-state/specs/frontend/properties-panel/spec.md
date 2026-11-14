# Spec Delta

## ADDED Requirements

### Requirement: Configuration tab loading state while operator metadata is pending
For an operator whose configuration panel depends on operator metadata, the Configuration tab SHALL display a loading state in place of the operator-specific form while the metadata request is in flight and that operator's metadata has not been received. The loading state SHALL be exposed as a status message and the Save button SHALL be disabled. The tab headers, the editable display name, and the Input and Output tabs SHALL remain available.

#### Scenario: Panel opened while metadata is pending
- **WHEN** the user opens the panel for an operator node whose panel depends on operator metadata while the operator metadata request is still in flight
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

#### Scenario: Canvas remount after a failed fetch shows the loading state
- **WHEN** the operator metadata is fetched again on Canvas remount after an earlier failure, and the new request is still in flight
- **THEN** the Configuration tab shows the loading state and not the error from the earlier failure

#### Scenario: Loading state is announced
- **WHEN** the Configuration tab enters the loading state
- **THEN** the loading indicator is exposed with an accessible status message

### Requirement: Configuration tab error state when operator metadata fails to load
For an operator whose configuration panel depends on operator metadata, the Configuration tab SHALL display an error state in place of the operator-specific form when the fetch failed or the metadata has no attributes for the selected node's operator. The error state SHALL state that the configuration could not be loaded, SHALL be exposed as an alert, and SHALL NOT expose technical error details. The Save button SHALL be disabled.

#### Scenario: Fetch fails before the panel is opened
- **WHEN** the operator metadata request has failed and the user opens the panel for an operator node whose panel depends on operator metadata
- **THEN** the Configuration tab shows the error state, no operator fields are rendered, and the Save button is disabled

#### Scenario: Fetch succeeds but has no metadata for the node's operator
- **WHEN** the operator metadata request succeeds but the response is empty, lacks the selected node's operator, or has no attributes for it, and the user opens the panel for that node
- **THEN** the Configuration tab shows the same error state as a failed request, no operator fields are rendered, and the Save button is disabled

#### Scenario: Fetch fails while the panel shows the loading state
- **WHEN** the operator metadata request fails while the panel is open and showing the loading state
- **THEN** the loading state is replaced by the error state and the Save button remains disabled

#### Scenario: Error details are not shown
- **WHEN** the error state is displayed
- **THEN** the message is a localized message chosen from an error code, and does not include status codes, stack traces, or backend error text

#### Scenario: Error state is announced
- **WHEN** the Configuration tab enters the error state
- **THEN** the error message is exposed as an alert

#### Scenario: Existing node configuration is preserved
- **WHEN** the user opens a node that already has saved parameters while the Configuration tab is in the loading or error state, and then closes the panel
- **THEN** the node's saved parameters are unchanged

## MODIFIED Requirements

### Requirement: Three-tab structure
The panel SHALL always render three tabs — Configuration, Input, and Output — for every selected node.

#### Scenario: Configuration tab is default
- **WHEN** the user opens the panel by selecting a node
- **THEN** the Configuration tab is active, and it shows the operator-specific form, except that for an operator whose panel depends on operator metadata, it shows the loading or error state while that operator's metadata is pending or unavailable

#### Scenario: Input tab shows upstream features
- **WHEN** the user selects the Input tab
- **THEN** the features flowing into the selected node from upstream operators are displayed

#### Scenario: Output tab shows downstream features
- **WHEN** the user selects the Output tab
- **THEN** the combined set of features the node will emit to downstream operators is displayed

### Requirement: Operator-specific configuration panel
The Configuration tab SHALL render the operator-specific form registered for the selected operator type. For an operator whose form depends on operator metadata, the form SHALL render once that operator's metadata is available, and the loading or error state SHALL be shown until then. When no panel is registered for an operator, a placeholder message SHALL be shown.

#### Scenario: Known operator shows its form
- **WHEN** the selected node is a known operator whose panel depends on operator metadata (e.g. ingest_source, chunker) and that operator's metadata is available
- **THEN** the operator's custom configuration form is rendered in the Configuration tab

#### Scenario: Operator that does not depend on metadata shows its form
- **WHEN** the selected node is an operator whose panel does not read operator metadata (e.g. branching, merge), whether the operator metadata is available, still pending, or failed to load
- **THEN** the operator's configuration form is rendered in the Configuration tab, with no loading or error state, and the Save button is not disabled by the metadata request

#### Scenario: Unknown operator shows placeholder
- **WHEN** the selected node has no registered configuration panel, whether or not the operator metadata is available
- **THEN** a placeholder message is shown in the Configuration tab

### Requirement: General operator configuration lifecycle
The properties panel SHALL execute a unified 5-step lifecycle for all operator nodes: reading operator metadata from the Redux `operators` slice and other node data from controller `appData`, loading persisted property values via `controller.getPropertyValue()`, rendering metadata-driven fields, evaluating required fields to toggle save readiness via `controller.setSaveButtonDisable()`, and writing modifications back via `controller.updatePropertyValue()`.

#### Scenario: Form loaded with initial node data
- **WHEN** an operator node is selected on the canvas
- **THEN** the panel retrieves its existing configuration from the canvas controller and populates the active inputs

#### Scenario: Value changes update canvas controller property
- **WHEN** the user updates a form field
- **THEN** the change is validated against operator schema and written to the canvas controller property cache

#### Scenario: Operator metadata is read from the Redux store
- **WHEN** the panel needs the operator metadata to render fields or evaluate required fields
- **THEN** it reads the metadata from the Redux `operators` slice and not from controller `appData`
