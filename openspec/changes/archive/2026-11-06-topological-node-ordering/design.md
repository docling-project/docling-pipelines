# Design

## Context

Node stats carry start and end times in whole seconds. Nodes that are skipped or fail together get identical timestamps, so a time-based sort cannot recover pipeline order. The flow snapshot saved for every job run holds the DAG, which defines that order.

## Goals / Non-Goals

**Goals:**
- Status responses and exported job logs list nodes in DAG order.
- Runs without a usable snapshot keep working, with chronological order.
- Polling the status endpoint stays cheap.

**Non-Goals:**
- Persisting the order with the job stats.
- Changing response fields.

## DDD Layer Boundaries

- **Utilities**: `node_ordering.py` holds the helpers that depend only on node stats (`order_node_items`, `get_node_sort_key`, `map_node_order_to_stats`). `dag_utils.py` derives the order from a snapshot. `node_ordering.py` imports only constants, so `job_management` can import it at module level; `dag_utils.py` imports the Elyra converter, which leads back to `job_management`, so it is imported inside the one function that needs it.
- **Adapters**: `NodeOrderResolver` (in `core/job_management/adapters/services/`) loads the snapshot through a callable supplied by `JobTrackerService`, derives the order and caches it. `JobTrackerService` delegates to it.
- **API**: `JobStatsMapper` orders DTO fields from the resolved order. Routes are unchanged.

## Decisions

- **Order source**: the flow snapshot, not the live flow, because the flow can be edited after a run starts.
- **Cache key and contents**: the job run ID, holding the unfiltered snapshot order. The order is mapped onto the current node stats on every call, because node stats grow as nodes start.
- **No TTL**: a snapshot is written once and never changes, so a cached order cannot go stale. The cache is LRU-bounded (256 runs per resolver) only to limit memory.
- **Not cached**: a missing snapshot (it is saved after flow validation, so early polls see none) and storage errors (they may be transient). A snapshot that yields no order is cached as empty, so it is not re-read on every poll.
- **Observability**: one INFO line per sort, with job run ID, flow ID and name, node count and cache occupancy. Repeated lines for the same job run indicate the cache is too small.
- **Rejected: module-level cache in `dag_utils`**: shared across service instances and tests, and it would move snapshot loading into the utility module.

## Risks / Trade-offs

- Each API process keeps its own cache, so each process reads a run's snapshot once.
- Runs whose snapshot is missing or saved as `null` (for example, executions that do not pass the original flow to `FlowExecutor`) keep chronological order.
