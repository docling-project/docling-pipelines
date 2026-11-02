# Spec Delta

## Purpose

Load the exact custom operator discovered from an installed package or other operator source.

## ADDED Requirements

### Requirement: Module-inspected package operators remain loadable
For every locally defined operator class discovered by inspecting an installed package's operator module, the package
adapter SHALL provide a loadable `module:Class` path and SHALL import the module portion when loading it.

#### Scenario: Package without entry points
- **WHEN** an installed package defines one valid operator in its operator module and has no `docpipe.operators` entry point
- **THEN** the discovered operator loads and registers under its own `short_name`

### Requirement: Named operator identity is preserved
When `OperatorInfo.name` identifies a class, validation and extraction SHALL use that exact locally defined, concrete
`AbstractOperator` subclass. They MUST NOT substitute another class from the same module. A named class SHALL pass the
existing operator contract before registration.

#### Scenario: Two operators in one installed package module
- **WHEN** a real installed package module defines two valid operators and discovery names each class separately
- **THEN** each discovered operator resolves to its named class and retains its own `short_name`

#### Scenario: Existing local entry point names one of several classes
- **WHEN** an installed distribution exposes a `docpipe.operators` entry point in `module:Class` form for a locally
  defined valid operator in a module with several operators
- **THEN** that entry point resolves to its named class without changing entry-point discovery priority

#### Scenario: Local class exported through an alias
- **WHEN** a locally defined operator class is available in an installed module only through an alias used by an
  entry point or module inspection
- **THEN** the alias resolves to that class while `OperatorInfo.name` retains its actual class name

#### Scenario: Named module-only or filesystem operator
- **WHEN** an operator source supplies a plain module or filesystem path and a valid class name
- **THEN** validation and extraction resolve that named class without requiring a `module:Class` path

#### Scenario: Named target is missing or invalid
- **WHEN** the named attribute is missing, is not an operator class, is abstract, or is imported from another module
- **THEN** loading reports a validation error and does not register a different class

### Requirement: Legacy unnamed metadata remains supported
For `OperatorInfo` without a class name, validation and extraction SHALL preserve the existing selection
of the first locally defined operator class and SHALL warn when several eligible classes are present.

#### Scenario: Unnamed module with several operators
- **WHEN** third-party adapter metadata has an empty `name` and its module defines multiple eligible operators
- **THEN** the first class in existing sorted member order is selected with a multiple-class warning

### Requirement: Failed operator loading remains isolated
An import or validation failure for one discovered operator SHALL be reported and SHALL NOT prevent other valid
operators from that source from loading.

#### Scenario: One invalid target beside a valid operator
- **WHEN** one discovered operator has stale class metadata and another has valid metadata
- **THEN** the stale target is reported and skipped while the valid operator loads
