# Spec Delta

## Purpose
Provides an MCP server and tools for programmatic operator discovery, flow validation, database flow registration, and pipeline execution.

## ADDED Requirements

### Requirement: Discover Available Operators via MCP
The server SHALL provide a `list_operators` tool that enumerates available operators, their categories, descriptions, and required input features from the operator registry.

#### Scenario: List all operators
- **WHEN** an agent calls `list_operators` without filters
- **THEN** the tool SHALL return all registered operators with `short_name`, `category`, `description`, and `required_features`

#### Scenario: Filter operators by category
- **WHEN** an agent calls `list_operators` with `category="Quality"`
- **THEN** the tool SHALL return only operators in the Quality category

### Requirement: Validate Flow Definition via MCP
The server SHALL provide a `validate_flow` tool that validates a flow definition against DAG topology, operator schemas, and feature dependencies without executing it or writing rows to job storage.

#### Scenario: Valid flow passes validation
- **WHEN** an agent calls `validate_flow` with a valid `flow_definition` or `flow_file`
- **THEN** the tool SHALL return `{"valid": true, "errors": [], "warnings": [...]}` and SHALL NOT write rows to `job_stats`

#### Scenario: Compilation and constructor errors are normalized
- **WHEN** an agent calls `validate_flow` with a flow missing `flow_name`, containing authoring-level cycles, or referencing invalid JSON
- **THEN** the tool SHALL catch the constructor exception and return `{"valid": false, "errors": [...], "warnings": []}` without raising an uncaught exception

#### Scenario: Exactly one flow source required
- **WHEN** an agent calls `validate_flow` with both or neither of `flow_definition` and `flow_file`
- **THEN** the tool SHALL return `{"valid": false, "errors": ["Exactly one of 'flow_definition' or 'flow_file' must be provided"], "warnings": []}`

### Requirement: Create and Register Flow via MCP
The server SHALL provide a `create_flow` tool that validates and registers a flow definition in the database asset repository, making it available in the Web UI Canvas and REST API, and optionally writes a `.json` file to workspace.

#### Scenario: Successful flow registration in database
- **WHEN** an agent calls `create_flow` with a valid flow definition
- **THEN** the tool SHALL register the flow in the asset repository via `FlowService` and return `{"registered": true, "flow_id": ..., "name": ...}`

#### Scenario: Optional file export with path validation
- **WHEN** an agent calls `create_flow` with a valid definition and a destination `path` inside workspace root
- **THEN** the tool SHALL register the flow in the database, write the formatted JSON to the path, and return the saved path

### Requirement: Execute Pipeline Flow Asynchronously via MCP
The server SHALL provide a `run_flow` tool that executes a flow in a background worker thread with thread-local `SessionInfo`, returning job identifiers immediately.

#### Scenario: Submit flow execution
- **WHEN** an agent calls `run_flow` with a valid `flow_definition` or `flow_file`
- **THEN** the tool SHALL spawn the execution in a background worker thread and immediately return `{"job_id": ..., "job_run_id": ..., "flow_id": ..., "status": "SUBMITTED"}`

#### Scenario: Micro-batching override semantics
- **WHEN** an agent calls `run_flow` without specifying `enable_micro_batching`
- **THEN** the execution SHALL respect the flow's explicit `global_config.enable_micro_batching` setting

### Requirement: Query Job Status via MCP
The server SHALL provide a `get_job_status` tool to query the execution status, node completion states, and metrics of a job run from the configured job stats store.

#### Scenario: Query job status defaults to latest run
- **WHEN** an agent calls `get_job_status` with `job_id` and omits `job_run_id`
- **THEN** the tool SHALL return the execution status and node states for the latest run of that job

#### Scenario: Query unknown job returns not found
- **WHEN** an agent calls `get_job_status` with an unknown `job_id`
- **THEN** the tool SHALL return `{"found": false, "error": "Job '<job_id>' not found"}`

### Requirement: Filesystem Trust Boundary and Path Validation
The server SHALL enforce workspace root containment on all file paths and reject unsafe filesystem operations.

#### Scenario: Reject path traversal escaping workspace root
- **WHEN** a tool receives a file path containing `..` or symlinks that resolve outside `DOCPIPE_WORKSPACE_ROOT`
- **THEN** the tool SHALL reject the operation with a path containment error

#### Scenario: Reject non-json file extension
- **WHEN** `create_flow` receives a destination path that does not end in `.json`
- **THEN** the tool SHALL reject the request

#### Scenario: Overwrite protection when overwrite is false
- **WHEN** `create_flow` receives a destination path that already exists and `overwrite=false`
- **THEN** the tool SHALL NOT modify the existing file and SHALL return an error response

### Requirement: Process-Level Stdout Transport Purity
The server SHALL ensure that `stdout` is reserved exclusively for MCP JSON-RPC protocol frames by redirecting OS file descriptor 1 and `sys.stdout` to `stderr` at startup.

#### Scenario: Internal logs and print statements do not reach transport
- **WHEN** pipeline operators, audit handlers, or third-party libraries write to `stdout` or call `print()`
- **THEN** all such output SHALL be routed to `stderr`, leaving the MCP transport stream clean of raw log lines

### Requirement: Credential Redaction in Responses
The server SHALL ensure that sensitive credentials present in flow configurations are never reflected in tool outputs or error messages.

#### Scenario: Redact secrets in error output
- **WHEN** a validation or execution failure occurs on a flow containing passwords or API keys
- **THEN** sensitive fields SHALL be masked in the returned error message
