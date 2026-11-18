# read-only-canvas Specification

## Purpose

The read-only-canvas capability is the pipeline viewer rendered during and after a job run. It displays the pipeline graph in a non-editable mode with live node status decorations (running spinner, checkmark, error, warning), a top status panel with run controls, and an optional right-side logs panel. It receives execution log data from Redux and reflects the current run state without initiating any polling itself.

## ADDED Requirements

### Requirement: Node status decorations
The canvas SHALL render a status decoration on each node reflecting its current execution state from the latest job stats.

#### Scenario: Running node shows spinner
- **WHEN** a node's status is "running"
- **THEN** an animated loading spinner decoration is shown on that node

#### Scenario: Completed node shows checkmark
- **WHEN** a node's status is "completed"
- **THEN** a green checkmark decoration is shown on that node

#### Scenario: Failed node shows error icon
- **WHEN** a node's status is "failed"
- **THEN** a red error icon decoration is shown on that node

#### Scenario: Warning node shows warning icon
- **WHEN** a node's status is a warning state (e.g. completed_with_issues)
- **THEN** a yellow warning icon decoration is shown on that node

### Requirement: Placeholder stats on mount
The canvas SHALL show a starting placeholder job stats object immediately on mount, before the first poll result arrives.

#### Scenario: Top panel visible immediately
- **WHEN** the read-only canvas mounts
- **THEN** the top status panel is visible showing a "Starting" status, not a blank state

### Requirement: Logs panel opens automatically when log content arrives
The canvas SHALL open the right-side logs panel automatically once the first node produces log content for the current run.

#### Scenario: Logs panel auto-opens
- **WHEN** execution logs arrive and at least one node has non-empty log content
- **THEN** the logs panel slides open without user interaction

### Requirement: Node click opens logs panel on the selected node
Clicking a node SHALL open the logs panel showing that node's data, or toggle between tabs if the panel is already open for the same node.

#### Scenario: Click on new node opens panel
- **WHEN** the user clicks a node that is not currently selected
- **THEN** the logs panel opens showing the Node Summary tab for that node

#### Scenario: Click on same node toggles tabs
- **WHEN** the user clicks the already-selected node with the panel open
- **THEN** the active tab index toggles between Log Details (index 0) and Node Summary (index 1); note that when the run has failed with no node execution sequence, the Node Summary tab is not rendered and the toggle has no visible effect

### Requirement: Run Again clears stale logs before creating new run
The canvas SHALL clear execution logs from Redux synchronously before initiating a new job run, and reset all local run state.

#### Scenario: Stale logs cleared immediately on Run Again
- **WHEN** the user clicks "Run Again"
- **THEN** execution logs are set to null before the new job run API call is made, the selected node is deselected, the logs panel is closed, all node status decorations are cleared, and the Stop button is immediately disabled

### Requirement: Stop button enabled state
The Stop button SHALL be enabled only when the run is in a stoppable state. On initial mount the Stop button is disabled by default; it is enabled once a poll result confirms the run is in a running or completed state. The set of statuses that keep the button disabled is determined by the `STOP_DISABLED_STATUSES` constant (which includes `starting`, `stopping`, `cancelled`, `failed`, `completed`, and other terminal/transitional states).

#### Scenario: Stop disabled on mount
- **WHEN** the read-only canvas first mounts
- **THEN** the Stop button is disabled until the first poll result arrives confirming a stoppable run state

#### Scenario: Stop disabled when run is in a terminal or transitional state
- **WHEN** the latest poll result status is in `STOP_DISABLED_STATUSES` (e.g. completed, failed, cancelled, starting, stopping)
- **THEN** the Stop button is disabled

#### Scenario: Stop disabled while stop is in progress
- **WHEN** the user clicks Stop
- **THEN** the Stop button is immediately disabled until the status updates
