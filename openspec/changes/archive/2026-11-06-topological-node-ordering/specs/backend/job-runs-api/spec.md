## ADDED Requirements

### Requirement: Order nodes in job run status by flow DAG
`node_sequence`, the keys of `job_stats.node_stats`, and `node_metadata` in a `JobRunStatusResponse` SHALL use the same order, following the topological order of the flow DAG recorded in the job run's flow snapshot. Nodes with stats that are not in the snapshot order SHALL follow the DAG-ordered nodes, sorted chronologically. Without a usable snapshot, all nodes SHALL be sorted chronologically, with nodes that have not started listed last.

#### Scenario: Nodes ordered by DAG when timestamps tie
- **WHEN** a run's nodes `Ingest -> Extract Content -> Document Quality -> Chunking` share the same start and end time and the run has a flow snapshot
- **THEN** `node_sequence`, the `node_stats` keys and `node_metadata` list the nodes as `Ingest`, `Extract Content`, `Document Quality`, `Chunking`

#### Scenario: Nodes missing from the snapshot are appended
- **WHEN** a run has stats for nodes that are not in the flow snapshot's DAG
- **THEN** those nodes appear after the DAG-ordered nodes, sorted by start time

#### Scenario: Chronological fallback without a snapshot
- **WHEN** a run has no flow snapshot, or the snapshot cannot be ordered
- **THEN** nodes are ordered by start time, with nodes that have not started listed last
