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
[get_docpipe_ [FlowValidator] [FlowService]  [DocpipeFlowManager]
 operators()]                     │                │
[OperatorFactory]                 ▼                ▼
                            [FlowRepository] [FlowExecutor]
                             (DuckDB / PG)         │
                                                   ▼
                                          [JobStatsStore Port]
```

## Decisions

### D1: Use `DocpipeFlowManager` as the Core Execution Bridge
`DocpipeFlowManager` already implements authoring format compilation, DAG validation via `FlowValidator`, and pipeline execution via `FlowExecutor`. Reusing it avoids duplicating orchestration logic.

### D2: Stdio Transport Wiring & Process-Level File Descriptor Redirection
MCP stdio transport requires `stdout` to carry JSON-RPC protocol frames exclusively. Core audit handlers (`audit.py:129`), filesystem ingest adapter `print()` calls, and third-party C/Python libraries (PyTorch, Docling, tqdm) write to stdout.

In `mcp>=1.30.0`, `stdio_server(stdin=None, stdout: AsyncFile | None = None)` defaults to `sys.stdout` unless an explicit output stream is provided. If `sys.stdout` is redirected to `sys.stderr` before `stdio_server` initializes without explicit wiring, JSON-RPC protocol frames would be misrouted to `stderr`.

To guarantee complete transport purity:
1. **OS File Descriptor Duplication**: In `src/docpipe/mcp/__main__.py`, duplicate OS file descriptor `1`:
   ```python
   orig_stdout_fd = os.dup(1)
   ```
2. **Process-Level Redirection**: Redirect both OS file descriptor `1` and `sys.stdout` to `sys.stderr`:
   ```python
   os.dup2(sys.stderr.fileno(), 1)
   sys.stdout = sys.stderr
   ```
3. **Strict Ordering**: Steps 1 and 2 MUST execute before importing any `docpipe` or third-party modules. Because `docpipe/__init__.py` is lazy, this ensures no module-level initializers or loggers bind to raw `stdout`.
4. **Transport Stream Wiring**: Wrap the duplicated file descriptor via `anyio.wrap_file(os.fdopen(orig_stdout_fd, "wb", buffering=0))` and pass it explicitly to `stdio_server(stdout=mcp_stdout)`.

### D3: Support Inline Flow Definitions and File Paths
`validate_flow` and `run_flow` accept either an inline JSON dictionary (`flow_definition`) or a file path (`flow_file`). Exactly one must be supplied; providing both or neither returns a validation error.

### D4: Error Normalization Across Constructor and DAG Validation
`DocpipeFlowManager.validate()` internally catches `FlowValidationException` and generic `Exception`, returning `{"valid": false, "errors": [...], "warnings": [...]}`. However, `DocpipeFlowManager.__init__` compiles authoring format during construction and can raise `FlowInvalidDataException` (e.g. missing `flow_name`, authoring cycles), `DocpipeException` (invalid arguments), `FileNotFoundError`, or `json.JSONDecodeError`.

The `validate_flow` tool wrapper guards manager construction, catching all constructor exceptions and normalizing them into `{ "valid": false, "errors": [str(e)], "warnings": [] }` without raising uncaught exceptions.

### D5: Filesystem Trust Boundary & Security
To prevent unauthorized filesystem access, arbitrary file overwrites, and code injection:
1. **Workspace Root Restriction**: A configured `DOCPIPE_WORKSPACE_ROOT` environment variable. If unset, it defaults to `Path.cwd().resolve()`. If the resolved root is root `/` or `$HOME` / `~`, the server refuses to start or refuses path-based tools to avoid exposing the entire host filesystem.
2. **Path Confinement**: All file paths (`path`, `flow_file`) and paths declared inside an inline `flow_definition` (e.g., `ingest_source` `connection_params.paths`, output paths) must resolve strictly within the workspace root (`resolved.is_relative_to(workspace_root)`). Directory traversal (`..`) and symlink escapes are rejected.
3. **File Extension**: Files written by `create_flow` must enforce a `.json` extension.
4. **Overwrite Protection**: `overwrite` defaults to `false`. If the target file exists and `overwrite=false`, the operation returns an error.
5. **Custom Operators Disabled by Default**: The server enforces `DOCPIPE_ENABLE_CUSTOM_OPERATORS=false` by default, rejecting custom operator references unless explicitly opted in.
6. **Secret Redaction**: Redaction is driven by declared credential fields from `src/docpipe/core/operators/secret_fields.py` (`SECRET_FIELDS`, `effective_secret_fields()`, `SECRET_FIELD_ALIASES`, and `json_schema_extra={"sensitive": True}`), with generic key-name pattern matching (`password`, `*_key`, `*_secret`, `*_token`, `credentials*`) as a fallback.

### D6: Asynchronous Execution, Concurrency, and Lifecycle for `run_flow`
Pipeline executions can take minutes. Running synchronously inside an async MCP handler would freeze the server, blocking keepalives and cancellation requests.

Lifecycle and concurrency details:
1. **Background Worker Execution**: `run_flow` spawns `DocpipeFlowManager.execute()` in a background worker thread.
2. **ContextVar Context Preservation**: `SessionInfo` uses `session_info_var: ContextVar[SessionInfo | None]`. Workers running in background threads are executed via `contextvars.copy_context().run(...)` (or invoke `create_session_info()` inside the worker) to ensure clean context initialization.
3. **Event Loop Offloading**: All synchronous tools (`validate_flow`, `create_flow`, `list_operators`, `get_job_status`) are executed off the async event loop using `anyio.to_thread.run_sync`.
4. **Polling Race Prevention**: `run_flow` synchronously registers the run with `status="Starting"` in an in-memory run registry and creates the initial job record before spawning the worker thread and returning `job_id`/`job_run_id`. `get_job_status` consults the run registry first, then the `JobStatsStore` port, ensuring agents never receive `found: false` immediately after submission.
5. **Status Vocabulary**: Strictly uses `ExecutionStatus` enum values from `src/docpipe/core/constants/constants.py` (`Queued`, `Pending`, `Starting`, `Running`, `Completed`, `CompletedWithErrors`, `CompletedWithWarnings`, `Failed`, `Canceled`). `CompletedWithErrors` and `CompletedWithWarnings` are never collapsed into `Completed`.
6. **Concurrency Cap**: Maximum concurrent runs are bounded by a semaphore (`DOCPIPE_MCP_MAX_CONCURRENT_RUNS`, default 4).
7. **Graceful Shutdown**: On server shutdown, the server waits up to `DOCPIPE_MCP_SHUTDOWN_TIMEOUT_SECONDS` (default 30s) for active workers to complete or marks them `Canceled`.
8. **Failed Step Source**: `failed_step: str | None = None` is derived from `node_stats` where a node has `node.status == ExecutionStatus.FAILED` or `failed_docs > 0` (or `None` if all nodes completed).

### D7: Database Registration & Partial Failure Semantics for `create_flow`
`create_flow` validates and registers flows in the database-backed `FlowRepository` via `FlowService`:
1. **Actor Context**: Passes `SYSTEM_ACTOR` (`ActorContext(username="<system>", roles=frozenset({"admin"}), is_system=True)`), explicitly bypassing REST authentication for local stdio agent invocations.
2. **Format**: Stored with `is_elyra=False` (authoring format).
3. **Container / Project ID**: Accepts optional `container_id: str | None = None` (UUID of project/space); defaults to `None` for global/unassigned flows.
4. **Duplicate Flow Handling**: `FlowService.create_flow` raises `FlowAlreadyExistsException` if a flow with that name already exists. When `overwrite=false`, returns an error response. When `overwrite=true`, updates the existing flow via `FlowService.update_flow(...)`.
5. **Partial Failure Rollback**:
   - The flow definition is pre-validated in memory before making changes.
   - If `path` is specified, the file is exported to the workspace.
   - The flow is then registered in the database repository.
   - If database registration fails (e.g., storage error, duplicate name), any exported workspace file is immediately unlinked (`os.unlink(path)`) so no partial state remains, and the error is returned to the agent.

### D8: Integrated Operator Discovery (`list_operators`)
To provide a self-contained authoring workflow, the server provides a `list_operators` tool querying `get_docpipe_operators()` and resolving metadata via `OperatorFactory`. It returns each operator's short name, category, description, and required input features.

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
  - `flow_file` (string, optional): Path to flow file on disk within workspace root.
  - *Contract*: Exactly one of `flow_definition` or `flow_file` must be provided.
- **Behavior**: Validates file path containment and inline path containment against `DOCPIPE_WORKSPACE_ROOT`. Normalizes constructor exceptions (`FlowInvalidDataException`, `DocpipeException`, `FileNotFoundError`, `json.JSONDecodeError`) and invokes `manager.validate()`.
- **Response**: `{ "valid": bool, "errors": list[str], "warnings": list[str] }`.
- **Side Effects**: Side-effect-free (writes zero rows to `job_stats` or `flows` repositories).

### `create_flow`
- **Arguments**:
  - `flow_definition` (object, required): Flow JSON dictionary.
  - `container_id` (string, optional): Target project/container UUID. Defaults to null.
  - `path` (string, optional): Destination `.json` path within workspace root.
  - `overwrite` (boolean, optional, default false): Whether to overwrite an existing file or database flow.
- **Behavior**: Pre-validates flow; if `path` is specified, verifies path containment and writes formatted JSON; registers flow in database via `FlowService` with `SYSTEM_ACTOR`; if DB registration fails, rolls back the exported file.
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
- **Behavior**: Validates paths; instantiates `DocpipeFlowManager(..., configure_logging=False)`; registers run synchronously with `status="Starting"`; spawns worker thread with `ContextVar` context preservation.
- **Response**:
  ```json
  {
    "job_id": "string",
    "job_run_id": "string",
    "flow_id": "string",
    "status": "Starting | Running | Completed | CompletedWithErrors | CompletedWithWarnings | Failed | Canceled",
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
- **Behavior**: Queries in-memory run registry, then configured `JobStatsStore` port.
- **Response**:
  ```json
  {
    "found": true,
    "job_id": "string",
    "job_run_id": "string",
    "status": "Starting | Running | Completed | CompletedWithErrors | CompletedWithWarnings | Failed | Canceled",
    "node_states": {
      "node_a": {
        "status": "Completed",
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
