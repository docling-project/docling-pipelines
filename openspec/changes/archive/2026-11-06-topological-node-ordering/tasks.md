# Tasks

## 1. Ordering

- [x] 1.1 [backend] Derive the node order from the flow snapshot for runtime, nested runtime, Elyra and authoring formats in `src/docpipe/utils/orchestration/dag_utils.py`. Verify with `pytest tests/unit/utils/orchestration/test_dag_utils.py`.
- [x] 1.2 [backend] Add `order_node_items`, `get_node_sort_key` and `map_node_order_to_stats` to `src/docpipe/utils/orchestration/node_ordering.py`, importing only constants. Verify with `pytest tests/unit/utils/orchestration/test_node_ordering.py`.
- [x] 1.3 [backend] Make `sort_dag_topologically` order siblings by input position and reject edges to unknown nodes. Verify with `pytest tests/unit/util/orchestration/test_flow_utils.py`.

## 2. Service and API

- [x] 2.1 [backend] Add `NodeOrderResolver` with the per-job-run cache and the INFO line per sort in `src/docpipe/core/job_management/adapters/services/node_order_resolver.py`. Verify with `pytest tests/unit/core/job_management/adapters/services/test_node_order_resolver.py`.
- [x] 2.2 [backend] Use the resolved order in `JobTrackerService.get_formatted_job_stats` and `write_job_logs`, and in `JobStatsMapper.to_dto` and `to_status_response`. Verify with `pytest tests/unit/core/job_management tests/unit/api/dto`.
- [x] 2.3 [backend] Remove the unused `JobTrackerService._calculate_node_sequence`.

## 3. Validation

- [x] 3.1 [backend] Run `ruff format --check`, `ruff check` and `mypy` on touched files.
- [x] 3.2 [backend] Run `openspec validate topological-node-ordering --strict`.
- [x] 3.3 [backend] Run `openspec archive topological-node-ordering`.
