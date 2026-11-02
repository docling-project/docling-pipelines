# Spec Delta

## Purpose

The canvas-page capability is the pipeline editor that lets users visually build, configure, save, validate, and run docling-pipelines flows. It supports two mutually exclusive visual modes — an interactive edit canvas and a read-only run viewer — and hosts all operator, branching, and job-run management concerns for a single flow.

## ADDED Requirements

### Requirement: Two visual modes — edit and run
The canvas page SHALL present exactly one of two mutually exclusive visual modes at a time: edit mode (interactive `ElyraCanvas`) and run mode (`ReadOnlyCanvas`). Switching to run mode SHALL be triggered by a successful `handleRun()` call. Exiting run mode SHALL restore edit mode without losing unsaved edits.

#### Scenario: Default mode is edit
- **WHEN** the canvas page mounts
- **THEN** edit mode is active and `ElyraCanvas` is displayed

#### Scenario: Run transitions to read-only
- **WHEN** `handleRun()` succeeds and a job run ID is available
- **THEN** the page switches to run mode and `ReadOnlyCanvas` is displayed

#### Scenario: Exit run returns to edit
- **WHEN** the user exits run mode via the `onExit` action
- **THEN** edit mode is restored and the canvas definition is unchanged

#### Scenario: Re-enter run from toolbar
- **WHEN** a run is already in progress (`isRunning && currentJobRunId`) and the user clicks the Run button
- **THEN** the page switches directly back to run mode without starting a new job

---

### Requirement: Loading and error states
The page SHALL show a loading indicator while the flow is being fetched. It SHALL show an error empty-state when the flow fetch fails or when the pipeline flow cannot be derived from the response.

#### Scenario: Spinner while loading
- **WHEN** the flow fetch is in-flight
- **THEN** a loading spinner is displayed and the canvas is not rendered

#### Scenario: Error on failed fetch
- **WHEN** `fetchFlow` resolves with an error
- **THEN** an error empty-state with the message "Failed to load flow" is displayed

#### Scenario: Error when pipeline is absent
- **WHEN** `fetchFlow` succeeds but the pipeline flow cannot be derived
- **THEN** an error empty-state with the message "Failed to load pipeline" is displayed

---

### Requirement: Route and URL parameters
The page SHALL read `flow_id` from the path parameter `/flows/:flow_id/canvas` and use it for all API calls. It SHALL read `project_id` from the `?project_id=` query parameter for breadcrumb back-navigation, the project fetch guard, and the `FlowInfoPanel`.

#### Scenario: Flow loaded by route param
- **WHEN** the user navigates to `/flows/abc/canvas`
- **THEN** the flow with id `abc` is fetched and rendered

#### Scenario: Project context from query param
- **WHEN** `?project_id=xyz` is present in the URL
- **THEN** the breadcrumb back-link targets `/projects/xyz` and the project is available for `FlowInfoPanel`

---

### Requirement: One-shot data loading effects
The page SHALL fetch flow data, operator metadata, and project data each at most once per mount using one-shot guards. Re-renders or React StrictMode double-invocations SHALL NOT trigger duplicate fetches.

#### Scenario: Flow fetch is one-shot
- **WHEN** the canvas mounts (including StrictMode double-invoke)
- **THEN** `fetchFlow` is dispatched exactly once

#### Scenario: Operator metadata fetch is skipped when already populated
- **WHEN** `operatorMetadata` is already present in the store on mount
- **THEN** `fetchOperatorMetadata` is NOT dispatched

#### Scenario: Project fetch is conditional
- **WHEN** `projectId` is set and the project is not yet in the store
- **THEN** the project is fetched once; subsequent renders with the project already in the store do not re-fetch

---

### Requirement: Global config synchronised with Redux flow run properties on load
After a successful flow fetch, the page SHALL extract `global_config` from the pipeline definition and populate `flowRunProperties` in Redux, applying the following mappings and inversions: `force_ingest → !enableIncrementalProcessing`, `retain_deleted_docs → retainRecordsForDeletedDocuments`, `disable_validation → validateFlow` (inverted: `!= true`), `enable_peekIn → enableNodeOutputPreview`, `data_storage_type → intermediateDataStorage` (default `'container'`).

#### Scenario: Incremental processing flag inverted on load
- **WHEN** the fetched flow has `global_config.force_ingest = true`
- **THEN** `flowRunProperties.enableIncrementalProcessing` is `false`

#### Scenario: Validation flag inverted on load
- **WHEN** the fetched flow has `global_config.disable_validation = true`
- **THEN** `flowRunProperties.validateFlow` is `false`

---

### Requirement: Dirty state tracks undo history
`isDirty` SHALL be `true` whenever the canvas controller reports that undo is available (`controller.canUndo()`), and `false` otherwise. The Save button SHALL be enabled only when `isDirty` is `true` and a save is not already in progress.

#### Scenario: Save enabled after edit
- **WHEN** the user makes any canvas mutation
- **THEN** `isDirty` becomes `true` and the Save button is enabled

#### Scenario: Save disabled after save completes
- **WHEN** a save completes successfully
- **THEN** `isDirty` is reset to `false` and the Save button is disabled

---

### Requirement: Save flow
The page SHALL save the current flow by reading the live canvas definition from the canvas controller (not from Redux), dispatching `saveFlow`, and on success updating `isDirty`, `lastSavedAt`, and triggering post-save validation when `validateFlow` is enabled. If the save fails, an error toast SHALL be shown. While saving, the Save and Run buttons SHALL be disabled.

#### Scenario: Successful save triggers validation
- **WHEN** `handleSave()` completes successfully and `validateFlow` is `true`
- **THEN** a POST to `/api/validate` is made and `validationData` is updated

#### Scenario: Successful save without validation clears stale data
- **WHEN** `handleSave()` completes successfully and `validateFlow` is `false`
- **THEN** `validationData` is set to a synthetic `'succeeded'` result, clearing any stale notification bar content

#### Scenario: Failed save shows error toast
- **WHEN** `saveFlow` dispatch resolves as rejected
- **THEN** an error toast is shown and the save state is reset

#### Scenario: No double-save guard
- **WHEN** `handleSave()` is called while a save is already in progress
- **THEN** the call is a no-op

---

### Requirement: Run flow
`handleRun()` SHALL execute three conditional steps in order: (1) save if dirty, (2) validate if `validateFlow` is enabled and abort if validation fails, (3) create a job run via POST `/api/job_runs`, start the poll loop, and switch to run mode. The live canvas definition SHALL be captured synchronously before any async step so that the run-mode snapshot reflects exactly what was on the canvas when Run was pressed.

#### Scenario: Dirty flow is saved before run
- **WHEN** the user clicks Run with unsaved changes
- **THEN** the flow is saved first; if save fails the run is aborted

#### Scenario: Validation failure aborts run
- **WHEN** validation returns `status === 'failed'`
- **THEN** the job run is NOT created and the page stays in edit mode

#### Scenario: Successful run enters run mode
- **WHEN** all three steps complete successfully
- **THEN** run mode is active and the poller is running for the new job run ID

#### Scenario: Run snapshot is captured synchronously
- **WHEN** `handleRun()` is invoked
- **THEN** the pipeline flow snapshot is captured before any await, preserving the canvas state at click time

---

### Requirement: Node properties panel
The page SHALL open a right-flyout properties panel when a user double-clicks an execution node or selects "Edit" from the context menu. The panel SHALL load parameter definitions (cached per operator type), merge any existing node parameter values, and display them via `CommonProperties`. While features are loading asynchronously, the panel SHALL show a loading state. Auto-save SHALL occur when the panel switches to a different node.

#### Scenario: Panel opens on double-click
- **WHEN** the user double-clicks an execution node
- **THEN** the right-flyout properties panel opens for that node

#### Scenario: Non-execution nodes skip panel
- **WHEN** a node with `type !== 'execution_node'` is double-clicked
- **THEN** no properties panel opens

#### Scenario: Parameter definitions are cached
- **WHEN** the user opens a panel for an operator type already opened this session
- **THEN** the cached param definition is used without a new network request

#### Scenario: Auto-save on node switch
- **WHEN** the panel is open for node A and the user opens node B
- **THEN** `applyPropertiesEditing(false)` is called on the properties controller before opening B

#### Scenario: Required-field guard disables Save button
- **WHEN** any required parameter has an empty or missing value
- **THEN** the properties panel Save button is disabled

---

### Requirement: Node defaults applied on creation
When a node is created (via palette drag or auto-node), the page SHALL immediately apply default parameter values before the first save. Branching nodes SHALL receive `{ link_conditions: [] }`. Merging nodes SHALL receive `{ merge_type: 'rows', column_option: 'inner_join' }`. All other operators SHALL have defaults resolved from `operatorMetadata` using the following priority: (1) `attr.default`, (2) `attr.providers[activeProvider].properties[k].default`, (3) `attr.properties[k].default`.

#### Scenario: Branching node stamped with empty link conditions
- **WHEN** a Branching node is added to the canvas
- **THEN** `node.parameters.link_conditions` is set to `[]` immediately

#### Scenario: Merging node stamped with defaults
- **WHEN** a Merging node is added to the canvas
- **THEN** `node.parameters.merge_type` is `'rows'` and `node.parameters.column_option` is `'inner_join'`

---

### Requirement: Node labels are unique
When a node is created, the page SHALL ensure its label is unique within the pipeline by appending `_1`, `_2`, … to the base operator label if a collision exists.

#### Scenario: Duplicate label resolved
- **WHEN** a node is added whose default label already exists in the pipeline
- **THEN** the new node receives a suffix (e.g. `extract_operator_1`) making it unique

---

### Requirement: Branching link condition system
Link conditions SHALL be stored on the Branching node inside `node.parameters.link_conditions` as a JSON array, one entry per outgoing link, each containing `link_id`, `target_node_id`, `target_port_id`, `link_name`, and `condition.criteria_json`. Merging link names SHALL be stored on the link object itself inside `node.inputs[n].links[m].link_name`. Link decorations SHALL be repainted after every create, delete, undo, redo, and cut operation.

#### Scenario: Link created from Branching port gets auto-name
- **WHEN** a new link is drawn from a Branching node output port
- **THEN** the link is persisted with an auto-generated name (`Link_0`, `Link_1`, …) in `link_conditions`

#### Scenario: Orphaned link conditions cleaned up on delete
- **WHEN** a link is deleted, cut, or removed via undo/redo
- **THEN** `syncDeletedLinks` removes the corresponding entry from all Branching node `link_conditions` arrays

#### Scenario: Decoration click opens tearsheet
- **WHEN** the user clicks a link decoration pill
- **THEN** `LinkConditionTearsheet` opens pre-populated with the link's current name and condition

#### Scenario: Merging link tearsheet shows name only
- **WHEN** the user opens the tearsheet for a link targeting a Merging node
- **THEN** only the link name field is shown; the condition builder is not displayed

---

### Requirement: Background job run poller
The poller SHALL run in the Canvas component (not `ReadOnlyCanvas`) so polling continues uninterrupted while the user is in edit mode. It SHALL poll `GET /api/job_runs/:id?include_node_stats=true` at a regular interval, dispatch execution logs, and stop automatically when a terminal status is reached. It SHALL perform one final poll after the terminal status delay. It SHALL retry on 404 and network errors up to a configured maximum before stopping.

#### Scenario: Poll continues in edit mode
- **WHEN** a job run is active and the user exits run mode to edit mode
- **THEN** polling continues without interruption

#### Scenario: Poll stops on terminal status
- **WHEN** the job run status is a completed status
- **THEN** the poller dispatches `setRunning(false)` and schedules one final poll before stopping

#### Scenario: Retry on transient errors
- **WHEN** a poll returns a 404 or a network error within the retry limit
- **THEN** the poller retries after the standard interval

#### Scenario: Stop on exhausted retries
- **WHEN** retry count exceeds `POLL_MAX_RETRIES`
- **THEN** polling stops

---

### Requirement: Node suggestion panel
The page SHALL display a contextual node suggestion panel when the user single-clicks an output port or selects "Recommend nodes" from the context menu. The panel SHALL show only valid successor operators for the clicked node, filtering out operators already connected to that node. Selecting a suggestion SHALL add the node to the canvas. The panel SHALL close on canvas wheel or mousedown events.

#### Scenario: Suggestions filtered to valid successors
- **WHEN** the node suggestion panel opens for a node
- **THEN** only operators returned by `getSuccessorOps` that are not already connected are listed

#### Scenario: Selecting suggestion adds node
- **WHEN** the user selects a suggested operator
- **THEN** `editActionHandler({ editType: 'createAutoNode', … })` is called and the panel closes

#### Scenario: Auto-close on canvas interaction
- **WHEN** the user scrolls or clicks elsewhere on the canvas
- **THEN** the node suggestion panel closes

---

### Requirement: Flow run properties writeback
When the user saves flow run properties from `FlowRunPropertiesTearsheet`, the page SHALL write the values back into the pipeline definition's `global_config` using the inverse of the load-time mappings: `enableIncrementalProcessing → !force_ingest`, `retainRecordsForDeletedDocuments → retain_deleted_docs`, `validateFlow → !disable_validation`, `enableNodeOutputPreview → enable_peekIn`, `intermediateDataStorage → data_storage_type`. It SHALL then dispatch `saveFlow` and update `isDirty` and `lastSavedAt`. Disabling validation SHALL inject a synthetic `'succeeded'` result to clear the notification bar.

#### Scenario: Properties saved and flow persisted
- **WHEN** the user saves flow run properties
- **THEN** `global_config` is updated and `saveFlow` is dispatched

#### Scenario: Disabling validation clears notification bar
- **WHEN** the user disables `validateFlow` and saves
- **THEN** a synthetic `'succeeded'` validation result is applied, removing any active validation notifications

---

### Requirement: Notification panel system
The `NotificationPanel` SHALL operate as a side-effect-only component that wires `validationData` into top and bottom panel content slots on `ElyraCanvas` via callbacks. The terminal button in the toolbar SHALL be enabled only when `validateFlow` is `true` and there are active notifications.

#### Scenario: Top notification bar shown for validation errors
- **WHEN** `validationData` contains errors
- **THEN** `topNotificationBar` is populated and `ElyraCanvas.topPanelContent` is shown

#### Scenario: Bottom panel toggled via terminal button
- **WHEN** the terminal button is active and clicked
- **THEN** a `CustomEvent('showBottomPanel')` is dispatched on `window` and the bottom panel opens

#### Scenario: Terminal button disabled without notifications
- **WHEN** there are no active notifications or `validateFlow` is `false`
- **THEN** the terminal button is disabled

---

### Requirement: Overlay components
The page SHALL render `FlowInfoPanel`, `EditDetailsModal`, `FlowRunPropertiesTearsheet`, `FlowRunHistoryTearsheet`, `NodeSuggestion`, and `LinkConditionTearsheet` inside the canvas container in both edit and run modes. Each overlay SHALL be conditionally mounted based on its corresponding open-state flag.

#### Scenario: FlowInfoPanel shown when about is open
- **WHEN** `isAboutPanelOpen` is `true`
- **THEN** `FlowInfoPanel` is rendered and the node properties panel is hidden

#### Scenario: EditDetailsModal patches flow on save
- **WHEN** the user saves changes in `EditDetailsModal`
- **THEN** `PATCH /api/flows/:id` is called and both `currentFlow` in the store and the flows list card are updated

---

### Requirement: Breadcrumb actions
The page SHALL inject "Flow run history" and "About this flow" icon buttons into the breadcrumb bar during edit mode. These buttons SHALL be removed from the breadcrumb bar while run mode is active and cleared entirely on unmount.

#### Scenario: Breadcrumb actions hidden in run mode
- **WHEN** `isRunMode` is `true`
- **THEN** no breadcrumb actions are shown

#### Scenario: Breadcrumb actions cleared on unmount
- **WHEN** the canvas page unmounts
- **THEN** breadcrumb actions are cleared

---

### Requirement: Run mode controls
While in run mode, the page SHALL pass the snapshot captured at run time to `ReadOnlyCanvas` (not the live Redux state). It SHALL expose `onExit`, `onRunAgain`, and `onStop` handlers. `onStop` SHALL cancel the active job run and restart polling to observe the terminal status.

#### Scenario: Run mode uses snapshot not live state
- **WHEN** run mode is active
- **THEN** `ReadOnlyCanvas` receives the `runPipelineFlowRef` snapshot, not the current Redux flow definition

#### Scenario: Stop cancels and resumes polling
- **WHEN** the user stops a run
- **THEN** the poll is stopped, `cancelJobRun()` is called, and polling resumes to observe the terminal status
