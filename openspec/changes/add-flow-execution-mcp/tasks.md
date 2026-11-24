# Tasks: Flow Execution & Authoring MCP Server

- [ ] 1. Package setup
  - [ ] 1.1 Create directory `src/docpipe/mcp/`
  - [ ] 1.2 Add entrypoint `docpipe-mcp = "docpipe.mcp.__main__:main"` to `[project.scripts]` in `pyproject.toml`
- [ ] 2. Core tool implementations
  - [ ] 2.1 Implement `validate_flow` tool with error normalization across manager construction (`FlowInvalidDataException`) and DAG validation (`FlowValidationException`), covering missing `flow_name` and cyclic flows
  - [ ] 2.2 Implement `create_flow` tool with pre-validation and file output
  - [ ] 2.3 Implement `run_flow` tool using `DocpipeFlowManager.execute()` with `configure_logging=False`
  - [ ] 2.4 Implement `get_job_status` tool querying the configured job stats store via domain port/service
- [ ] 3. Server assembly & transport
  - [ ] 3.1 Implement `create_server()` in `src/docpipe/mcp/server.py` with stdio transport
  - [ ] 3.2 Configure server-owned logging to `stderr` only, preventing non-protocol output on `stdout`
  - [ ] 3.3 Implement CLI entrypoint in `src/docpipe/mcp/__main__.py`
- [ ] 4. Tests & Verification
  - [ ] 4.1 Unit tests for tool argument parsing, error normalization (cyclic flow, missing `flow_name`), and validation handling
  - [ ] 4.2 Transport test asserting `stdout` contains only valid MCP JSON-RPC protocol frames with zero raw log lines
  - [ ] 4.3 Integration smoke test running a minimal flow through the MCP server
