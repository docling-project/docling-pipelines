# Spec Delta

## ADDED Requirements

### Requirement: Properties panel accessibility and keyboard tab navigation
The properties panel SHALL support full keyboard navigation across the three tabs (Configuration, Input, Output) via Left/Right Arrow keys, ensure all input controls have associated accessible labels, and trap focus within modal tearsheets when open.

#### Scenario: Arrow keys switch active tab
- **WHEN** focus is on a properties tab header and the user presses the Right Arrow key
- **THEN** focus and active selection move to the adjacent tab header

#### Scenario: Form controls contain accessible labels
- **WHEN** operator fields are rendered
- **THEN** every input, select, and toggle element possesses an accessible name linked via `htmlFor` or `aria-label`
