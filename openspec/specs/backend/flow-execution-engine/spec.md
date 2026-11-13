# backend/flow-execution-engine Specification

## Purpose

The flow-execution-engine capability is the core pipeline runtime that takes a compiled flow definition (DAG format), validates it, propagates features through the operator graph, saves the flow snapshot for auditability, and drives operator-by-operator execution through an orchestrator. It is used by the API job run service, the CLI, and the `DocpipeFlowManager` library entrypoint.

## Requirements

### Requirement: Cancellation checked before execution starts
Before any validation or operator execution begins, `FlowExecutor.execute()` SHALL check whether the job run has been signalled for cancellation via the job stats service. If the run is already in `Cancelling` state, execution SHALL be aborted immediately and `None` SHALL be returned without raising an exception.

#### Scenario: Pre-execution cancel check aborts run
- **WHEN** `execute()` is called and the job run is already in `Cancelling` state
- **THEN** `cancel_job_run_if_cancelling()` returns `True`, execution is aborted, and `None` is returned

#### Scenario: Non-cancelled run proceeds past check
- **WHEN** `execute()` is called and the job run is not in `Cancelling` state
- **THEN** execution continues to validation

### Requirement: Flow validated before operator execution
After the cancellation check, `FlowExecutor.execute()` SHALL validate the flow definition via `FlowValidator`. If validation produces errors, a `FlowValidationException` SHALL be raised and execution SHALL be aborted. If validation produces only warnings (no errors), execution SHALL proceed with the warnings logged. `disable_validation` in `global_config` or the flow run params SHALL bypass the DAG structural validation.

#### Scenario: Validation errors abort execution
- **WHEN** `execute()` is called with a flow definition containing an unknown operator
- **THEN** a `FlowValidationException` is raised with non-empty `errors` before any operator runs

#### Scenario: Validation warnings do not abort execution
- **WHEN** `execute()` is called with a flow that produces only warnings (e.g. non-critical connectivity issues)
- **THEN** the warnings are logged and execution proceeds normally

#### Scenario: Validation disabled via global_config
- **WHEN** `execute()` is called with `global_config.disable_validation = true`
- **THEN** DAG structural validation is skipped and the flow proceeds directly to execution

### Requirement: Features propagated and injected into node configs before execution
After validation, `FlowExecutor.execute()` SHALL propagate features through the DAG via `FlowValidator.propagate_features_per_node()`. The resulting `available_features` dict for each node SHALL be injected directly into that node's `config` dict before the orchestrator runs, so operators can reference upstream column metadata at runtime without additional API calls.

#### Scenario: Available features injected into each node config
- **WHEN** `execute()` is called with a valid multi-node flow
- **THEN** each node's `config["available_features"]` is populated with the features available at that point in the DAG

#### Scenario: Node with no upstream features receives empty dict
- **WHEN** a node is the first in the DAG (e.g. an IngestSourceOperator with no predecessors)
- **THEN** `config["available_features"]` is an empty dict for that node

### Requirement: Flow definition snapshot saved for auditability
Before operator execution begins, `FlowExecutor.execute()` SHALL save the original (pre-compilation) flow definition to the job stats service via `save_flow_definition()`. This snapshot is used by `GET /api/v1/job_runs/{id}/flow_definition` for run replay and audit. Snapshot save failures SHALL be logged as errors but SHALL NOT abort execution.

#### Scenario: Snapshot saved before execution
- **WHEN** `execute()` is called with a valid `job_id` and `job_run_id`
- **THEN** `job_stats_service.save_flow_definition()` is called with the original flow definition before the orchestrator runs

#### Scenario: Snapshot save failure does not abort execution
- **WHEN** `save_flow_definition()` raises an exception
- **THEN** the exception is logged and execution continues normally

#### Scenario: Snapshot not saved when job IDs are absent
- **WHEN** `execute()` is called without a `job_id` or `job_run_id`
- **THEN** `save_flow_definition()` is not called

### Requirement: Orchestrator drives operator execution
`FlowExecutor.execute()` SHALL delegate operator-by-operator execution to the injected `AbstractOrchestrator` instance via `orchestrator.execute(flow_def, params)`. The executor SHALL NOT directly instantiate or call individual operators. If no orchestrator is available, a `ValueError` SHALL be raised. Exceptions raised during `orchestrator.execute()` SHALL be re-raised after logging.

#### Scenario: Orchestrator called with flow def and params
- **WHEN** `execute()` is called successfully
- **THEN** `orchestrator.execute(flow_def=self.flow_def, params=params)` is called exactly once

#### Scenario: Missing orchestrator raises ValueError
- **WHEN** `execute()` is called with no orchestrator injected and no orchestrator set on the instance
- **THEN** a `ValueError` is raised with message "No orchestrator available for flow execution"

#### Scenario: Orchestrator exception is re-raised
- **WHEN** `orchestrator.execute()` raises an exception
- **THEN** the exception is logged and re-raised from `FlowExecutor.execute()`

### Requirement: Orchestrator initialised with job context before execution
When both `job_id` and `job_run_id` are available (from params or session info), `FlowExecutor.execute()` SHALL call `orchestrator.initialize(job_id=job_id, job_run_id=job_run_id)` before validation and execution. This sets the thread-local `SessionInfo` context so operators can access the current job identifiers.

#### Scenario: Orchestrator initialised with IDs when available
- **WHEN** `execute()` is called with `job_id` and `job_run_id` present in params
- **THEN** `orchestrator.initialize(job_id=..., job_run_id=...)` is called before `orchestrator.execute()`

### Requirement: Cancel, pause, and resume delegated to orchestrator
`FlowExecutor.cancel()`, `FlowExecutor.pause()`, and `FlowExecutor.resume()` SHALL delegate directly to the same methods on the injected orchestrator. If no orchestrator is set, these calls SHALL be no-ops.

#### Scenario: Cancel delegated to orchestrator
- **WHEN** `cancel()` is called on a FlowExecutor with an active orchestrator
- **THEN** `orchestrator.cancel()` is called

#### Scenario: Cancel is no-op without orchestrator
- **WHEN** `cancel()` is called with no orchestrator set
- **THEN** no exception is raised and nothing happens

### Requirement: Ingest source requires a provider
Flow validation through CLI, Python library, and execution entry points SHALL reject an ingest source whose provider is absent, null, empty, or whitespace-only with the message "Provider not added. Select a provider for the ingest source operator." Ingestion SHALL reject the same inputs before storage or source access even when flow validation is disabled.

#### Scenario: Missing provider fails validation
- **WHEN** a flow contains an ingest source with an absent, null, empty, or whitespace-only provider
- **THEN** validation reports a provider-selection error without a NoneType error

#### Scenario: Validation disabled
- **WHEN** ingestion starts without a provider and flow validation is disabled
- **THEN** ingestion raises the provider-selection error before storage or source access

#### Scenario: Valid provider preserves ingestion contract
- **WHEN** a configured ingest source executes with a valid provider
- **THEN** its existing PyArrow table output schema and transform metadata contract are preserved

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

#### Scenario: Explicit opt-in reaches feature propagation
- **WHEN** `DocpipeFlowManager(enable_custom_operators=True)` validates a flow while `DOCPIPE_ENABLE_CUSTOM_OPERATORS` is unset
- **THEN** output features declared by custom operators propagate to downstream operators, because the validator builds its feature propagator from the same orchestrator

#### Scenario: Workers receive the setting
- **WHEN** worker environment variables are resolved for a job run and `DOCPIPE_ENABLE_CUSTOM_OPERATORS` is set in the submitting process
- **THEN** the same value is forwarded to the worker, so API validation and worker execution agree

#### Scenario: Setting not forwarded when unset
- **WHEN** `DOCPIPE_ENABLE_CUSTOM_OPERATORS` is unset in the submitting process
- **THEN** it is not set for the worker, and the worker uses the disabled default
