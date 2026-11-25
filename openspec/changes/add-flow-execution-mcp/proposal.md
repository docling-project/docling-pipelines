# Proposal: Flow Execution & Authoring MCP Server

## Why
AI coding assistants and autonomous agents need a standardized, programmatic way to discover operators, author, validate, register, and execute document processing flows in `docling-pipelines` without shelling out to raw terminal commands or manually formatting files. An MCP server exposing flow validation, registration, and execution capabilities enables agents to author pipelines safely and trigger job runs reliably.

## What Changes
- **New Package**: `src/docpipe/mcp/` exposing a standard Model Context Protocol (MCP) server over stdio.
- **New CLI Entrypoint**: `docling-pipelines-mcp = "docpipe.mcp.__main__:main"` in `[project.scripts]`.
- **Core MCP Tools**:
  1. `list_operators`: Discovers available operators, categories, and required input features from `get_docpipe_operators()` / `DOCPIPE_OPERATORS` and `OperatorFactory`.
  2. `validate_flow`: Validates flow JSON DAG connectivity, operator configs, and feature propagation in memory or from a file.
  3. `create_flow`: Validates and registers the flow definition in the database asset repository via `FlowService` (making it immediately visible in the Web UI Canvas and REST API), and optionally exports a `.json` copy to the workspace.
  4. `run_flow`: Launches flow execution asynchronously via `DocpipeFlowManager` in a worker thread, returning job identifiers immediately.
  5. `get_job_status`: Retrieves execution status, per-node metrics, and errors for a job run via `JobStatsStore`.

## Scope & Dependencies
- **UI and API Integration**: `create_flow` registers flows in the database-backed `FlowRepository`, ensuring created flows appear in the UI canvas and are accessible via REST API.
- **Operator Discovery**: `list_operators` is integrated directly into this server so agents have a self-contained authoring workflow without requiring a second server.
- **Dependencies**: The `mcp` package is in `[project.dependencies]` (`pyproject.toml`). The implementation will ensure a minimum version of `mcp>=1.30.0,<2.0` matching the stdio server APIs used, with `uv lock` updated per project rules when the dependency specification is touched.

## Capabilities
### New Capabilities
- `backend/flow-execution-mcp`: Exposes operator discovery, flow authoring, validation, database registration, and pipeline execution as MCP tools.

## Impact
- Non-breaking addition: Uses existing `DocpipeFlowManager`, `FlowValidator`, `FlowService`, `get_docpipe_operators()`, `OperatorFactory`, and `JobStatsStore` port under the hood.
- Fully compatible with both DuckDB and PostgreSQL job stats and asset backends.
