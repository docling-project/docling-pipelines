# Spec Delta

## Purpose
Provides an MCP server and tools for programmatic flow validation, flow authoring/saving, and pipeline execution.

## ADDED Requirements

### Requirement: Validate Flow Definition via MCP
The server SHALL provide a `validate_flow` tool that validates a flow definition against DAG topology, operator schemas, and feature dependencies without executing it.

#### Scenario: Valid flow definition passes validation
- **WHEN** an agent calls `validate_flow` with a structurally valid flow definition
- **THEN** the tool SHALL return `{"valid": true, "errors": [], "warnings": [...]}`

#### Scenario: Invalid flow definition returns actionable errors
- **WHEN** an agent calls `validate_flow` with missing required features, cyclic dependencies, or missing ingest root
- **THEN** the tool SHALL return `{"valid": false, "errors": [...], "warnings": [...]}` detailing the exact validation failure

#### Scenario: Compilation errors during construction are normalized
- **WHEN** an agent calls `validate_flow` with a flow missing `flow_name` or containing authoring-level cycles that fail compilation during manager construction
- **THEN** the tool SHALL catch the compilation exception and return `{"valid": false, "errors": [...], "warnings": []}` rather than terminating or raising an uncaught exception

### Requirement: Create and Save Flow to Workspace via MCP
The server SHALL provide a `create_flow` tool that validates and saves a flow JSON file to disk.

#### Scenario: Successful flow creation
- **WHEN** an agent calls `create_flow` with a target path and valid flow definition
- **THEN** the tool SHALL validate the flow, save it to the specified path, and return a success message

#### Scenario: Failed flow creation on invalid definition
- **WHEN** an agent calls `create_flow` with an invalid flow definition
- **THEN** the tool SHALL NOT create the file and SHALL return an error response with validation failures

### Requirement: Execute Pipeline Flow via MCP
The server SHALL provide a `run_flow` tool that executes a flow from a file path or an in-memory flow definition using `DocpipeFlowManager`.

#### Scenario: Execute flow successfully
- **WHEN** an agent calls `run_flow` with a valid `flow_file` or `flow_definition`
- **THEN** the tool SHALL execute the pipeline and return execution status, documents processed, and execution duration

#### Scenario: Execution error is cleanly reported
- **WHEN** a pipeline execution encounters a runtime error
- **THEN** the tool SHALL return a failure response containing the error message and failed step without terminating the MCP server process

### Requirement: Query Job Status via MCP
The server SHALL provide a `get_job_status` tool to query the execution status and metrics of a job run.

#### Scenario: Read status of completed or running job
- **WHEN** an agent calls `get_job_status` with a valid `job_id`
- **THEN** the tool SHALL return the execution status, node completion states, and timestamps from the job store

### Requirement: Pure Stdio Transport Channel
The server SHALL ensure that `stdout` is reserved exclusively for MCP JSON-RPC protocol frames.

#### Scenario: Suppress core logging on stdout
- **WHEN** the server invokes `DocpipeFlowManager` for validation or execution
- **THEN** `configure_logging=False` SHALL be passed and all server logging SHALL be emitted to `stderr`, leaving `stdout` free of raw log messages
