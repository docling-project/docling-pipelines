# Proposal

## Why

`GET /api/v1/job_runs/{job_run_id}` returns `node_sequence`, `job_stats.node_stats` and `node_metadata` ordered by node start time, with node name as the tie-breaker. When a run fails early or downstream nodes are skipped, those nodes share a timestamp, so they come back in alphabetical order instead of pipeline order (for example `Chunking`, `Document Quality`, `Embeddings`, `Extract Content`). Exported job logs have the same problem. See issue #527.

The current spec only says `node_sequence` is an "ordered node execution list" and does not say what the order is.

## What Changes

- `node_sequence`, `job_stats.node_stats` and `node_metadata` follow the topological order of the flow DAG recorded in the job run's flow snapshot.
- When the snapshot is missing or yields no order, they fall back to chronological order: completed and running nodes by start time, then pending nodes.
- Nodes that have stats but are not in the snapshot order are sorted chronologically and appended after the DAG-ordered nodes.
- Exported job logs (`job_stats.json`) use the same ordering.
- Supported snapshot formats: runtime DAG (`{"dag": [...]}`, also nested as `{"flow": {"dag": [...]}}`), Elyra pipeline, and authoring flow (operator names mapped to node IDs).
- The snapshot order is cached per job run, so polling the status endpoint does not re-read and re-sort the snapshot on every request.
- **BREAKING (Python API)**: `JobStatsMapper.to_dto` and `JobStatsMapper.to_status_response` take keyword-only arguments.

## Non-goals

- Changing the response schema. Only the order of existing fields changes.
- Storing the computed order with the job stats at run start (a possible follow-up that would remove the need for a cache).

## Capabilities

### New Capabilities
- None

### Modified Capabilities
- `backend/job-runs-api`: adds a requirement that defines the order of `node_sequence`, `node_stats` and `node_metadata` in the job run status response.

## Impact

- **Affected Layer**: Backend-only.
- **Affected code**: `JobTrackerService` (`get_formatted_job_stats`, `write_job_logs`), new `NodeOrderResolver`, `JobStatsMapper`, `utils/orchestration/dag_utils.py`, new `utils/orchestration/node_ordering.py`, `sort_dag_topologically` in `flow_utils.py`.
- **API consumers**: the order of nodes in status responses changes for runs whose nodes share timestamps or ran in parallel branches. The frontend auto-selects the last node in `node_sequence` that has stats, which is now the deepest node in DAG order.
