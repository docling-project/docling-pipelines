# frontend/read-only-canvas/run-side-panel Specification

## Purpose
The run-side-panel capability is the right-side panel in the read-only canvas that shows per-node execution details for the current job run. It provides two tabs — Log Details (accordion of node logs) and Node Summary (node statistics and metadata) — along with controls for downloading all logs and expanding individual logs in a modal.

## Requirements

### Requirement: Two-tab structure
The panel SHALL provide two tabs: Log Details and Node Summary.

#### Scenario: Log Details tab shows node logs
- **WHEN** the user selects the Log Details tab
- **THEN** an accordion of per-node log sections is shown, one entry per node in the execution sequence

#### Scenario: Node Summary tab shows selected node stats
- **WHEN** the user selects the Node Summary tab and a node is selected
- **THEN** the selected node's execution statistics and metadata are shown

#### Scenario: Node Summary empty state when no node selected
- **WHEN** the Node Summary tab is active and no node is selected
- **THEN** an empty state message is shown

### Requirement: Log Details tab disabled when no logs
The Log Details tab SHALL be disabled when the job run has no per-node execution sequence AND the run has not failed. For a failed run with no sequence, the tab is enabled (so the user can still see the panel); it is only disabled when there is no sequence and the run is not in a failed state.

#### Scenario: Tab disabled with no node sequence on non-failed run
- **WHEN** the execution logs contain no node_sequence and the run status is not "failed"
- **THEN** the Log Details tab is disabled and not interactive

#### Scenario: Tab enabled for failed run with no sequence
- **WHEN** the run status is "failed" and node_sequence is empty
- **THEN** the Log Details tab is enabled (the panel renders with whatever content is available)

### Requirement: Node Summary tab hidden for failed runs without sequence
The Node Summary tab SHALL not be shown when the run has failed and has no per-node execution sequence.

#### Scenario: Node Summary hidden for failed no-sequence run
- **WHEN** the run status is "failed" and node_sequence is empty
- **THEN** the Node Summary tab is not rendered

### Requirement: Log download
The panel SHALL provide a download button that exports all node logs as a text file.

#### Scenario: Download creates a text file
- **WHEN** the user clicks the download button
- **THEN** a .txt file containing all node logs separated by section headers is downloaded

### Requirement: Full log modal with copy
The panel SHALL allow users to expand any individual node log into a full-screen modal with a one-click copy button.

#### Scenario: Full log modal opens on expand
- **WHEN** the user clicks to expand a node's log
- **THEN** a modal opens showing the full log text with a copy-to-clipboard button

#### Scenario: Copy button copies log to clipboard
- **WHEN** the user clicks the copy button in the full log modal
- **THEN** the full log text is written to the clipboard
