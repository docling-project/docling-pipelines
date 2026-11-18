# frontend/common/vault-input Specification

## Purpose
The vault-input-component is a credential/secret input field that supports two modes: direct plaintext entry (via a password input or multiline textarea) and Vault reference entry (via a `vault://` URI path input). A toggle switches between modes, preserving the last-known value for each mode so toggling back and forth does not lose data.

## Requirements

### Requirement: Mode toggle between direct and vault
The component SHALL provide a toggle labeled "Use Vault" that switches the input between direct entry mode and Vault reference mode.

#### Scenario: Toggle on switches to vault mode
- **WHEN** the user enables the "Use Vault" toggle
- **THEN** the input switches to show a `vault://` prefix tag and a path text input

#### Scenario: Toggle off switches to direct mode
- **WHEN** the user disables the "Use Vault" toggle
- **THEN** the input switches back to the password or textarea input

### Requirement: Mode value preservation on toggle
The component SHALL restore the last-known value for the mode being switched to, so toggling does not lose previously entered data.

#### Scenario: Direct value restored on vault-off
- **WHEN** the user toggles vault off after previously entering a direct value
- **THEN** the previously entered direct value is restored in the input

#### Scenario: Vault URI restored on vault-on
- **WHEN** the user toggles vault on after previously entering a vault path
- **THEN** the previously entered vault path is restored

### Requirement: Vault URI validation
The component SHALL mark the vault input as invalid when the vault path suffix is empty (i.e. the stored value is exactly `vault://`).

#### Scenario: Empty vault path shows invalid state
- **WHEN** vault mode is active and no path has been entered after `vault://`
- **THEN** the input shows an invalid state with a format hint message

### Requirement: Multiline direct mode
The component SHALL render a textarea instead of a password input when the multiline prop is true.

#### Scenario: Multiline renders textarea
- **WHEN** multiline is true and vault mode is off
- **THEN** a textarea is rendered instead of a password input

### Requirement: External value sync
The component SHALL update its internal mode and remembered values when the value prop changes externally.

#### Scenario: Vault reference prop switches to vault mode
- **WHEN** the parent sets the value to a vault:// URI
- **THEN** the component switches to vault mode displaying that URI's path
