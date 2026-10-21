# Spec Delta

## ADDED Requirements

### Requirement: Canvas page keyboard accessibility and focus management
The canvas page SHALL support standard keyboard shortcuts (Escape to close side panels/modals, Delete/Backspace to remove selected nodes, Ctrl/Cmd+S to trigger save) and restore focus to the originating canvas trigger element upon closing modals or side panels.

#### Scenario: Escape key closes properties flyout and restores focus
- **WHEN** the user presses the Escape key while the properties panel is open
- **THEN** the properties panel closes and focus is restored to the selected canvas node

#### Scenario: Keyboard shortcut triggers flow save
- **WHEN** the user presses Ctrl+S (or Cmd+S on macOS) with valid canvas state
- **THEN** the canvas page initiates the flow save workflow
