# Spec Delta

## ADDED Requirements

### Requirement: Permission-gated run controls on read-only canvas
The "Stop" and "Run Again" actions on `RunStatusTopPanel` inside `ReadOnlyCanvas` (both in Canvas run mode and on the `RunDetails` page) SHALL be disabled or hidden with an explanatory tooltip when the user lacks `editor`. Viewing node execution status and logs SHALL remain available to all authenticated users.

#### Scenario: Viewer inspects a job run
- **WHEN** a viewer opens a job run in `ReadOnlyCanvas`
- **THEN** the "Stop" and "Run Again" buttons are disabled or hidden, while node status decorations and the logs panel remain usable

#### Scenario: Editor inspects a job run
- **WHEN** an editor or admin opens a job run in `ReadOnlyCanvas`
- **THEN** "Stop" (while stoppable) and "Run Again" are enabled
