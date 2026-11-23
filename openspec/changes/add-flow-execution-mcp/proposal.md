# Proposal: Flow Execution & Authoring MCP Server

## Why
AI coding assistants and autonomous agents need a standardized, programmatic way to create, validate, and execute document processing flows in `docling-pipelines` without shelling out to raw terminal commands or manually formatting files. An MCP server exposing flow validation, creation, and execution capabilities enables agents to author pipelines safely and trigger job runs reliably.

## What Changes
- **New Package**: `src/docpipe/mcp/` exposing a standard Model Context Protocol (MCP) server over stdio.
- **New CLI Entrypoint**: `docpipe-mcp` (and `docling-pipelines mcp`) to start the server.
- **Core MCP Tools**:
  1. `validate_flow`: Validates flow JSON DAG connectivity, operator configs, and feature propagation in memory.
  2. `create_flow`: Validates and saves flow definitions to disk.
  3. `run_flow`: Executes a flow (by path or inline JSON) via `DocpipeFlowManager`.
  4. `get_job_status`: Retrieves execution status and metrics for a job run.

## Capabilities
### New Capabilities
- `backend/flow-execution-mcp`: Exposes flow authoring, validation, and pipeline execution as MCP tools.

## Impact
- Non-breaking addition: Uses existing `DocpipeFlowManager`, `FlowValidator`, and `FlowExecutor` under the hood.
- Optional installation: Uses the optional `mcp` dependency group (`mcp>=1.0,<2.0`).
