# common/shared-tearsheet Specification

## Purpose

The shared-tearsheet-component is the base tearsheet wrapper used by all multi-step forms and detail panels in the application. It renders either a full-width or narrow Carbon IBM Products Tearsheet based on the size prop, portals into the active theme element so Carbon CSS tokens are inherited correctly, and provides a standard footer with primary and secondary action buttons.

## ADDED Requirements

### Requirement: Size-based variant selection
The component SHALL render a full-width Tearsheet for size `lg` and a TearsheetNarrow for all smaller sizes (`xs`, `sm`, `md`).

#### Scenario: Large size renders full tearsheet
- **WHEN** size is `lg` (or omitted)
- **THEN** a full-width Tearsheet is rendered

#### Scenario: Small size renders narrow tearsheet
- **WHEN** size is `xs`, `sm`, or `md`
- **THEN** a TearsheetNarrow is rendered

### Requirement: Theme-aware portal target
The component SHALL portal into the active theme element so Carbon CSS custom property tokens resolve correctly inside the tearsheet.

#### Scenario: CSS tokens apply inside tearsheet
- **WHEN** the tearsheet is open inside a Carbon Theme wrapper
- **THEN** Carbon design tokens (e.g. `--cds-background`) apply correctly to tearsheet content

### Requirement: Footer action buttons
The component SHALL render primary and secondary action buttons in the footer when provided. When `hideFooter` is true, no action buttons SHALL be shown.

#### Scenario: Primary action button rendered when label and handler provided
- **WHEN** primaryActionLabel and onPrimaryAction are both provided
- **THEN** a primary action button with that label is shown in the footer

#### Scenario: Footer hidden when hideFooter is true
- **WHEN** hideFooter is true
- **THEN** no action buttons are rendered in the footer

### Requirement: Always-present close icon
The component SHALL always render a close icon in the tearsheet header.

#### Scenario: Close icon calls onClose
- **WHEN** the user clicks the close icon
- **THEN** the onClose callback is invoked

### Requirement: preventCloseOnClickOutside SHALL be accepted but not forwarded
The component accepts a `preventCloseOnClickOutside` prop for API compatibility with existing callers, but the prop is deliberately not forwarded to the Carbon IBM Products `Tearsheet` or `TearsheetNarrow` — Carbon's tearsheet components handle outside-click behaviour internally. Callers MUST NOT rely on this prop having any effect.

#### Scenario: Outside-click behaviour is Carbon-default
- **WHEN** the user clicks outside an open tearsheet
- **THEN** the tearsheet behaviour follows Carbon's default regardless of the preventCloseOnClickOutside prop value
