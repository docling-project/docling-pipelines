# Design: Flow Execution & Authoring MCP Server

## Architecture

The MCP server runs as a standalone Python process over stdio, wrapping existing core docpipe components without modifying their contracts:

```
[ AI Agent (Claude, Cursor, T3, Bob) ]
                  │
             stdio transport
                  ▼
         [ docpipe-mcp server ]
        (src/docpipe/mcp/server.py)
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
 [ FlowValidator ]   [ DocpipeFlowManager ]
                            │
                            ▼
                    [ FlowExecutor ]
                            │
                            ▼
                 [ PythonOrchestrator ]
```

## Decisions

### D1: Use `DocpipeFlowManager` as the Core Engine Bridge
`DocpipeFlowManager` already implements authoring format compilation, DAG validation via `FlowValidator`, and pipeline execution via `FlowExecutor`. Reusing it avoids duplicating orchestration logic.

### D2: Stdio Transport
Stdio is the standard for local agent integrations. It requires zero network ports, no authentication complexity, and runs cleanly within agent environments.

### D3: Support Inline Flow Definitions and File Paths
`validate_flow` and `run_flow` accept inline JSON dictionaries so agents can test flow DAGs without touching the filesystem. `create_flow` writes validated definitions to disk when persistence is desired.

### D4: Stdout Transport Purity & Server-Owned Stderr Logging
MCP stdio transport requires `stdout` to carry JSON-RPC protocol frames exclusively. Core `DocpipeFlowManager` configures logging on `stdout` by default; therefore, all manager instantiations in the MCP server must pass `configure_logging=False`. The MCP server manages its own logging explicitly to `stderr`.

### D5: Validation Error Normalization Across Construction and DAG Validation
`DocpipeFlowManager` parses and compiles authoring format definitions in `__init__`, raising `FlowInvalidDataException` on compilation failures (such as missing `flow_name` or cycles in authoring format) before `.validate()` can run. The `validate_flow` tool wrapper must normalize both `FlowInvalidDataException` (from construction) and `FlowValidationException` (from `.validate()`) into `{ "valid": false, "errors": [...], "warnings": [...] }` without raising uncaught exceptions.

## Tool Specifications

### `validate_flow`
- **Arguments**:
  - `flow_definition` (object, required): Flow JSON dictionary.
- **Behavior**: Normalizes exceptions across `DocpipeFlowManager(flow_def=flow_definition, configure_logging=False)` instantiation and `.validate()`. Catches both `FlowInvalidDataException` and `FlowValidationException`.
- **Response**: `{ "valid": bool, "errors": list[str], "warnings": list[str] }`.

### `create_flow`
- **Arguments**:
  - `path` (string, required): Destination `.json` path.
  - `flow_definition` (object, required): Flow JSON dictionary.
  - `overwrite` (boolean, optional, default false): Whether to overwrite an existing file.
- **Behavior**: Pre-validates flow using the normalized validation logic; writes formatted JSON to path if valid.

### `run_flow`
- **Arguments**:
  - `flow_file` (string, optional): Path to flow file.
  - `flow_definition` (object, optional): Inline flow JSON dictionary.
  - `enable_micro_batching` (boolean, optional, default true): Enable micro-batching.
- **Behavior**: Calls `DocpipeFlowManager(..., configure_logging=False).execute()`. Returns run summary (status, doc counts, duration).

### `get_job_status`
- **Arguments**:
  - `job_id` (string, required): Job identifier.
  - `job_run_id` (string, optional): Specific job run identifier.
- **Behavior**: Reads execution stats via the configured job stats store/service (supporting both DuckDB and PostgreSQL backends).
