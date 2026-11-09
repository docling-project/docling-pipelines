# Spec Delta

## ADDED Requirements

### Requirement: Custom operators are disabled unless explicitly enabled
The engine SHALL NOT load custom operators (uploaded scripts, `DOCPIPE_CUSTOM_OPERATORS` packages or other external sources) unless enabling is requested. The setting SHALL be resolved in this order: the explicit `enable_custom_operators` argument, then the `DOCPIPE_ENABLE_CUSTOM_OPERATORS` environment variable (`true`, `1` or `yes`, case-insensitive, enables; any other value disables), then the built-in default, which SHALL be disabled. Built-in `docpipe` operators SHALL always be available.

#### Scenario: Nothing configured
- **WHEN** a factory, orchestrator, `DocpipeFlowManager`, CLI run or API job run is created with no explicit setting and `DOCPIPE_ENABLE_CUSTOM_OPERATORS` is unset
- **THEN** only built-in operators are loaded and the custom operator loader is not invoked

#### Scenario: Enabled by environment
- **WHEN** `DOCPIPE_ENABLE_CUSTOM_OPERATORS` is `true` and no explicit setting is passed
- **THEN** custom operators are loaded from the configured sources

#### Scenario: Explicit argument wins
- **WHEN** `enable_custom_operators=False` is passed and `DOCPIPE_ENABLE_CUSTOM_OPERATORS` is `true`
- **THEN** custom operators are not loaded

#### Scenario: Unrecognised environment value
- **WHEN** `DOCPIPE_ENABLE_CUSTOM_OPERATORS` is set to a value other than `true`, `1` or `yes` and no explicit setting is passed
- **THEN** custom operators are not loaded

#### Scenario: Orchestrator reports a resolved boolean
- **WHEN** an orchestrator is created without an explicit setting
- **THEN** `orchestrator.enable_custom_operators` is a `bool` equal to the resolved value

#### Scenario: Workers receive the setting
- **WHEN** worker environment variables are resolved for a job run and `DOCPIPE_ENABLE_CUSTOM_OPERATORS` is set in the submitting process
- **THEN** the same value is forwarded to the worker, so API validation and worker execution agree

#### Scenario: Setting not forwarded when unset
- **WHEN** `DOCPIPE_ENABLE_CUSTOM_OPERATORS` is unset in the submitting process
- **THEN** it is not set for the worker, and the worker uses the disabled default
