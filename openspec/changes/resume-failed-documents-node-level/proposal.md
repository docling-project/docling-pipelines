# Proposal: Node-Level Failure Resumption with Deferred Execution Tracking

## Why

When a pipeline execution encounters failures at downstream nodes (such as embedding API rate limits, LLM timeouts, or vector database connection drops), re-executing the flow currently forces all failed documents to re-run from the root Ingest operator. This causes wasteful re-ingestion, heavy re-extraction, and expensive re-OCR of documents that had already succeeded through earlier nodes.

By automatically detecting previously failed documents during standard incremental execution, maintaining their upstream intermediate checkpoints, and injecting them directly into the node where they failed, the pipeline saves significant computation and time. Furthermore, introducing a `deferred_execution_docs` accounting category ensures document counts (`documents_in_scope = processed_docs + deferred_execution_docs + failed_docs + skipped_docs`) remain mathematically consistent across all nodes in the DAG.

## What Changes

- **Automatic Pre-Execution Resumption Planning**: Before flow execution, the orchestrator inspects `JobStatsStore` for failed documents from prior runs of the same `job_id`, checks retry thresholds against `max_retry_attempts` (default: 3, allowing `max_retry_attempts + 1` total attempts), and locates upstream checkpoint tables.
- **Source Modification Validation**: When documents fail, their source `modification_time` is recorded. During subsequent runs, Ingest compares the current source file's `modification_time` against the saved `modification_time`. If the file was modified in the source, the checkpoint is invalidated and the document is re-ingested fresh from the root.
- **Deferred Execution Accounting**: Documents scheduled for downstream resumption are counted in `documents_in_scope` at the Ingest node and categorized as `deferred_execution_docs`. Upstream nodes carry this count forward without performing duplicate compute.
- **Node-Level Checkpoint Injection**: When execution reaches the failed node, the orchestrator retrieves the upstream parent checkpoint rows for the deferred documents, combines them with incoming batch tables, and clears them from `deferred_execution_docs`.
- **Micro-Batching Integration**: Fresh and deferred documents are partitioned into micro-batches after Ingest so that each batch carries its respective deferred document metadata until the resumption node.
- **Persistence & Metrics Updates**: `NodeStats` and storage stores (DuckDB, PostgreSQL, JSON) persist `deferred_execution_docs`. Successfully resumed documents are finalized in `IncrementalMetadataStore` and their intermediate checkpoints purged (checkpoints are retained for retry-exhausted documents).
- **Exhausted Retry Persistence & Reporting**: Documents that exhaust `max_retry_attempts` are permanently persisted to `IncrementalMetadataStore` with non-recoverable failure metadata and explicitly reported as `Failed (Max retries exhausted)` in the post-execution job run report.

## Non-goals

- Dynamic DAG structural modification or handling schema changes between runs (deferred to a future change).
- Creating new REST endpoints or CLI subcommands to trigger retries (resumption is entirely automatic during normal incremental execution).
- Cross-job checkpoint sharing (checkpoints are strictly scoped to the same `job_id`).
- Concurrent runs of the same `job_id` (executions of a given `job_id` are assumed to be sequential; concurrent runs of the same `job_id` are out of scope).

## Capabilities

### Modified Capabilities
- `backend/flow-execution-engine`: Add node-level failure resumption, checkpoint table loading and injection at target nodes, and `deferred_execution_docs` accounting across node executions.

## Impact

- **Layer**: Backend-only.
- **Affected Packages/Modules**:
  - `src/docpipe/core/constants/constants.py` (New metric and config constants)
  - `src/docpipe/core/job_management/domain/models/node_stats.py` (`deferred_execution_docs` field)
  - `src/docpipe/core/job_management/adapters/stores/` (DuckDB, Postgres, JSON stores for `deferred_execution_docs`)
  - `src/docpipe/core/operators/ingest/ingest_source.py` (Timestamp comparison, deferred docs emission)
  - `src/docpipe/core/orchestration/abstract_operator_executor.py` (Checkpoint injection & deferred tracking)
  - `src/docpipe/core/orchestration/abstract_orchestrator.py` & `prefect_engine.py` (Resumption planning)
  - `src/docpipe/core/job_management/application/services/report_generator.py` (Job run report failure details)
