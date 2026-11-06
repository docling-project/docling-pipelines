## MODIFIED Requirements

### Requirement: Get job run status and node statistics
`GET /api/v1/job_runs/{job_run_id}` SHALL return a `JobRunStatusResponse` containing `job_stats` (overall run metadata and per-node `node_stats`), `node_sequence` (ordered node execution list), and `node_metadata` (per-node document counts). When `include_logs=true` the response SHALL also include per-node execution log strings keyed by node ID. An unknown `job_run_id` SHALL return 404.

`node_sequence`, the keys of `job_stats.node_stats`, and `node_metadata` SHALL use the same order. That order SHALL follow the topological order of the flow DAG recorded in the job run's flow snapshot. Nodes with stats that do not appear in the snapshot order SHALL follow the DAG-ordered nodes, sorted chronologically. When the snapshot is missing or yields no order, all nodes SHALL be sorted chronologically: nodes that have started, by start time, before nodes that have not started.

#### Scenario: Status returned with node stats
- **WHEN** `GET /api/v1/job_runs/{job_run_id}` is called for a running or completed run
- **THEN** the response is 200 with `job_stats.status`, `node_stats` per node, and `node_sequence`

#### Scenario: Nodes ordered by DAG when timestamps tie
- **WHEN** a run's nodes `Ingest -> Extract Content -> Document Quality -> Chunking` share the same start and end time and the run has a flow snapshot
- **THEN** `node_sequence`, the `node_stats` keys and `node_metadata` list the nodes as `Ingest`, `Extract Content`, `Document Quality`, `Chunking`

#### Scenario: Nodes missing from the snapshot are appended
- **WHEN** a run has stats for nodes that are not in the flow snapshot's DAG
- **THEN** those nodes appear after the DAG-ordered nodes, sorted by start time

#### Scenario: Chronological fallback without a snapshot
- **WHEN** a run has no flow snapshot, or the snapshot cannot be ordered
- **THEN** nodes are ordered by start time, with nodes that have not started listed last

#### Scenario: Logs included when requested
- **WHEN** `GET /api/v1/job_runs/{job_run_id}?include_logs=true` is called
- **THEN** the response includes per-node log strings in addition to the standard fields

#### Scenario: Logs excluded by default
- **WHEN** `GET /api/v1/job_runs/{job_run_id}` is called without `include_logs`
- **THEN** no per-node log strings are present in the response

#### Scenario: Unknown job run returns 404
- **WHEN** `GET /api/v1/job_runs/{unknown_id}` is called
- **THEN** the response is 404 with `errors[0].code = "not_found"`
