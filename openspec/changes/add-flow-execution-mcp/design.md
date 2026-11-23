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

## Tool Specifications

### `validate_flow`
- **Arguments**:
  - `flow_definition` (object, required): Flow JSON dictionary.
- **Behavior**: Calls `DocpipeFlowManager(flow_def=flow_definition).validate()`.
- **Response**: `{ "valid": bool, "errors": list[str], "warnings": list[str] }`.

### `create_flow`
- **Arguments**:
  - `path` (string, required): Destination `.json` path.
  - `flow_definition` (object, required): Flow JSON dictionary.
  - `overwrite` (boolean, optional, default false): Whether to overwrite an existing file.
- **Behavior**: Pre-validates flow; writes formatted JSON to path if valid.

### `run_flow`
- **Arguments**:
  - `flow_file` (string, optional): Path to flow file.
  - `flow_definition` (object, optional): Inline flow JSON dictionary.
  - `enable_micro_batching` (boolean, optional, default true): Enable micro-batching.
- **Behavior**: Calls `DocpipeFlowManager.execute()`. Returns run summary (status, doc counts, duration).

### `get_job_status`
- **Arguments**:
  - `job_id` (string, required): Job identifier.
  - `job_run_id` (string, optional): Specific job run identifier.
- **Behavior**: Reads execution stats from the DuckDB job store (`data/duckdb/job_stats.duckdb`).
