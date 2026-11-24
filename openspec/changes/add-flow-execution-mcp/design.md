# Design: Flow Execution & Authoring MCP Server

## Architecture

The MCP server runs as a standalone Python process over stdio, wrapping existing core docpipe components without modifying their contracts:

```
[ AI Agent (Claude, Cursor, T3, Bob) ]
                  │
             stdio transport
                  ▼
      [ docling-pipelines-mcp ]
     (src/docpipe/mcp/server.py)
                  │
  ┌───────────────┼───────────────┬────────────────┐
  ▼               ▼               ▼                ▼
[Operator   [FlowValidator] [FlowService]  [DocpipeFlowManager]
 Registry]                        │                │
                                  ▼                ▼
                            [FlowRepository] [FlowExecutor]
                             (DuckDB / PG)         │
                                                   ▼
                                          [JobStatsStore Port]
```

## Decisions

### D1: Use `DocpipeFlowManager` as the Core Execution Bridge
`DocpipeFlowManager` already implements authoring format compilation, DAG validation via `FlowValidator`, and pipeline execution via `FlowExecutor`. Reusing it avoids duplicating orchestration logic.

### D2: Stdio Transport with Process-Level File Descriptor Redirection
MCP stdio transport requires `stdout` to carry JSON-RPC protocol frames exclusively. Multiple components in the codebase and third-party libraries write to stdout (`audit.py:129`, filesystem adapter `print()` calls, Docling, PyTorch, tqdm).

To ensure complete transport purity:
1. In `src/docpipe/mcp/__main__.py`, duplicate OS file descriptor `1` (`os.dup(1)`) exclusively for the MCP JSON-RPC transport stream.
2. Redirect `sys.stdout` and OS file descriptor `1` (`os.dup2(sys.stderr.fileno(), 1)`) to `sys.stderr` *before* importing any `docpipe` or third-party modules.
3. This process-level redirection is strictly contained within the standalone MCP server process and has zero impact on the existing CLI (`docling-pipelines`) or REST API (`docling-pipelines-api`).

### D3: Support Inline Flow Definitions and File Paths
`validate_flow` and `run_flow` accept either an inline JSON dictionary (`flow_definition`) or a file path (`flow_file`). Exactly one must be supplied.

### D4: Error Normalization Across Constructor and DAG Validation
`DocpipeFlowManager.validate()` internally catches `FlowValidationException` and generic `Exception`, returning `{"valid": false, "errors": [...], "warnings": [...]}`. However, `DocpipeFlowManager.__init__` compiles the flow during object construction and can raise `FlowInvalidDataException` (e.g. missing `flow_name`, authoring-level cycles), `DocpipeException` (invalid arguments), `FileNotFoundError`, or `json.JSONDecodeError`.

The `validate_flow` tool wrapper guards manager construction, catching all constructor exceptions and normalizing them into `{ "valid": false, "errors": [str(e)], "warnings": [] }` without raising uncaught exceptions.

### D5: Filesystem Trust Boundary & Security
To prevent unauthorized filesystem reads, arbitrary file overwrites, and code injection:
1. **Workspace Root Restriction**: A configured `DOCPIPE_WORKSPACE_ROOT` (defaults to current working directory). All path inputs (`path`, `flow_file`) must resolve strictly within this root (`resolved.is_relative_to(workspace_root)`). Paths attempting directory traversal (`..`) or symlink escapes outside the root are rejected.
2. **File Extension**: Files written by `create_flow` must enforce a `.json` extension.
3. **Overwrite Protection**: `overwrite` defaults to `false`. If the target file exists and `overwrite=false`, the operation safely returns an error.
4. **Custom Operators Disabled**: The server explicitly passes `enable_custom_operators=False` by default, requiring explicit opt-in via `DOCPIPE_MCP_ENABLE_CUSTOM_OPERATORS=true`.
5. **Secret Redaction**: Error messages and tool outputs pass through credential sanitization to ensure sensitive fields (`password`, `token`, `secret`, `api_key`) are never leaked.

### D6: Asynchronous Execution & Concurrency Model for `run_flow`
Pipeline executions can take minutes. Running synchronously inside an async MCP handler would freeze the server, blocking keepalives and cancellation requests. Furthermore, `SessionInfo` is thread-local (AGENTS.md Rule 9).

Model:
1. `run_flow` spawns `DocpipeFlowManager.execute()` in a dedicated background worker thread.
2. The worker thread initializes its own thread-local `SessionInfo` via `create_session_info()`.
3. The tool immediately returns `{ "job_id": str, "job_run_id": str, "flow_id": str, "status": "SUBMITTED" }`.
4. The agent polls for progress and final metrics using `get_job_status`.
5. An optional `wait: bool = false` (with `timeout_seconds: int = 60`) allows agents desiring a synchronous wait to block up to the timeout while keeping the async event loop responsive.

### D7: Database Registration for UI and API Compatibility
`create_flow` validates the flow and persists it to the database-backed `FlowRepository` using `FlowService`. This ensures that flows created via MCP immediately appear in the Web UI Canvas and are accessible via REST API routes (`/flows`). If an optional `path` parameter is supplied, it also exports a formatted `.json` file to the workspace.

### D8: Integrated Operator Discovery (`list_operators`)
To provide a self-contained authoring workflow, the server provides a `list_operators` tool directly querying `OperatorRegistry`. It returns the operator's short name, category, one-line summary, and required input features.

## Tool Specifications

### `list_operators`
- **Arguments**:
  - `category` (string, optional): Filter by category (`Ingest`, `Extract`, `Functional`, `Quality`, `VectorDB`, `Storage`).
- **Response**: List of operator summaries:
  ```json
  [
    {
      "short_name": "chunker",
      "category": "Functional",
      "description": "Splits documents into smaller text chunks",
      "required_features": ["document"]
    }
  ]
  ```

### `validate_flow`
- **Arguments**:
  - `flow_definition` (object, optional): Flow JSON dictionary.
  - `flow_file` (string, optional): Path to flow file on disk.
  - *Contract*: Exactly one of `flow_definition` or `flow_file` must be provided.
- **Behavior**: Validates file path containment if provided. Normalizes constructor exceptions (`FlowInvalidDataException`, `DocpipeException`, `FileNotFoundError`, `json.JSONDecodeError`) and invokes `manager.validate()`.
- **Response**: `{ "valid": bool, "errors": list[str], "warnings": list[str] }`.
- **Side Effects**: Side-effect-free (writes zero rows to `job_stats` or flow databases).

### `create_flow`
- **Arguments**:
  - `flow_definition` (object, required): Flow JSON dictionary.
  - `path` (string, optional): Destination `.json` path within workspace root.
  - `overwrite` (boolean, optional, default false): Whether to overwrite an existing file if `path` is provided.
- **Behavior**: Pre-validates flow; registers flow in database asset repository via `FlowService`; if `path` is given, verifies containment and writes formatted JSON.
- **Response**:
  ```json
  {
    "registered": true,
    "flow_id": "string",
    "name": "string",
    "saved_path": "string | null"
  }
  ```

### `run_flow`
- **Arguments**:
  - `flow_definition` (object, optional): Inline flow JSON dictionary.
  - `flow_file` (string, optional): Path to flow file on disk within workspace root.
  - `enable_micro_batching` (boolean, optional, default null): Explicit override; when null, the flow's explicit `global_config` setting is respected.
  - `wait` (boolean, optional, default false): Whether to wait up to `timeout_seconds`.
  - `timeout_seconds` (integer, optional, default 60): Timeout when `wait=true`.
  - *Contract*: Exactly one of `flow_definition` or `flow_file` must be provided.
- **Behavior**: Instantiates `DocpipeFlowManager(..., configure_logging=False)`. Launches execution in a background thread with fresh `SessionInfo`.
- **Response**:
  ```json
  {
    "job_id": "string",
    "job_run_id": "string",
    "flow_id": "string",
    "status": "SUBMITTED | RUNNING | COMPLETED | FAILED",
    "execution_time_seconds": null,
    "total_documents_processed": null,
    "failed_documents_count": null,
    "failed_step": null
  }
  ```

### `get_job_status`
- **Arguments**:
  - `job_id` (string, required): Job identifier.
  - `job_run_id` (string, optional): Specific job run identifier. Defaults to latest run for the job if omitted.
- **Behavior**: Queries configured `JobStatsStore` port.
- **Response**:
  ```json
  {
    "found": true,
    "job_id": "string",
    "job_run_id": "string",
    "status": "PENDING | RUNNING | COMPLETED | FAILED",
    "node_states": {
      "node_a": {
        "status": "COMPLETED",
        "records_in": 10,
        "records_out": 10,
        "execution_time_ms": 120.5
      }
    },
    "started_at": "string | null",
    "completed_at": "string | null",
    "errors": []
  }
  ```
  If `job_id` is unknown: `{"found": false, "error": "Job '<job_id>' not found"}`.

## Concurrency Note
DuckDB is a single-writer database. In multi-process deployments where the MCP server, CLI, and REST API run concurrently against `data/duckdb/job_stats.duckdb`, PostgreSQL backend (`job_management.storage = postgres`) is recommended to avoid database lock contention.
