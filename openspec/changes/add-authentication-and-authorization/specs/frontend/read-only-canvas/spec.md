# Spec Delta

## ADDED Requirements

### Requirement: Permission-gated run controls on read-only canvas
On `RunStatusTopPanel` inside `ReadOnlyCanvas`, in both Canvas run mode and the `RunDetails` page, the "Stop" action SHALL be disabled with an explanatory tooltip when the user cannot modify the job run (`!canModifyAsset(jobStats.user_id)`). Viewing node execution status and logs SHALL remain available to all authenticated users.

#### Scenario: Viewer inspects a job run
- **WHEN** a viewer opens a job run in `ReadOnlyCanvas`
- **THEN** the "Stop" and "Run Again" buttons are disabled, while node status decorations and the logs panel remain usable

#### Scenario: Non-owner editor inspects another user's running job
- **WHEN** an editor opens an in-progress job run created by another user in `ReadOnlyCanvas`
- **THEN** "Stop" is disabled, while "Run Again" remains available once the run completes

#### Scenario: Run owner or admin inspects a job run
- **WHEN** the editor who started the job run (or an admin) opens it in `ReadOnlyCanvas`
- **THEN** "Stop" (while stoppable) and "Run Again" are enabled

### Requirement: Permission-gated Run Again
The "Run Again" action SHALL be disabled with an explanatory tooltip when the user lacks `editor`. It SHALL NOT depend on who started the original run.

#### Scenario: Viewer cannot run again
- **WHEN** a viewer opens a completed job run
- **THEN** "Run Again" is disabled with a permission tooltip
