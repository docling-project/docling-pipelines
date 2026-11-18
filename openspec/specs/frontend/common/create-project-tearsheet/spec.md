# frontend/common/create-project-tearsheet Specification

## Purpose
The create-project-tearsheet-component is the two-step modal for creating a new project and optionally a first flow within it. Despite the "tearsheet" name, it is implemented as a Carbon `ComposedModal` (not `SharedTearsheet`). Step 1 collects project name (required), description, and tags. Step 2 collects an optional flow name, description, and tags. A `ProgressIndicator` shows the current step and all form state is reset on close or cancel.

## Requirements

### Requirement: Two-step flow with progress indicator
The tearsheet SHALL present two steps in sequence — project details then flow details — and show a progress indicator reflecting the current step.

#### Scenario: Opens on step 1
- **WHEN** the tearsheet opens
- **THEN** the project details step (step 1) is active and the progress indicator shows step 1 as in-progress

#### Scenario: Next advances to step 2
- **WHEN** the user completes step 1 and clicks Next
- **THEN** step 2 (flow details) becomes active and the progress indicator updates

### Requirement: Project name is required and must be unique
The tearsheet SHALL validate that the project name is non-empty and not already used by an existing project before advancing.

#### Scenario: Empty name blocks Next
- **WHEN** the user clicks Next with an empty project name
- **THEN** the name field shows an invalid state and step 2 is not shown

#### Scenario: Duplicate name blocks Next
- **WHEN** the user enters a project name that already exists
- **THEN** the name field shows a duplicate error and step 2 is not shown

### Requirement: Loading state on submit
The modal SHALL show a loading indicator on the Create button while the submit operation is in progress and disable all footer buttons. This applies on step 2 only. On step 1, the Next button is statically disabled whenever the project name field is empty or a duplicate name error is present — it is not driven by a loading state.

#### Scenario: Buttons disabled during create (step 2)
- **WHEN** the user clicks Create on step 2
- **THEN** the Cancel, Back, and Create buttons are all disabled and the Create button shows an inline loading indicator

#### Scenario: Next disabled on step 1 when name is invalid
- **WHEN** on step 1 and the project name is empty or matches an existing project name
- **THEN** the Next button is disabled without any loading indicator

### Requirement: Form state resets on close
The tearsheet SHALL reset all form fields to empty values when closed or cancelled.

#### Scenario: Re-opening shows empty form
- **WHEN** the user closes and re-opens the tearsheet
- **THEN** all form fields are empty and the tearsheet starts on step 1
