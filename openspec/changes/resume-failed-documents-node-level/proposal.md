# Proposal: Node-Level Failure Resumption with Deferred Execution Tracking

## Why

When a pipeline execution encounters failures at downstream nodes (such as embedding API rate limits, LLM timeouts, or vector database connection drops), re-executing the flow currently forces all failed documents to re-run from the root Ingest operator. This causes wasteful re-ingestion, heavy re-extraction, and expensive re-OCR of documents that had already succeeded through earlier nodes.

By automatically detecting previously failed documents during standard incremental execution, reading the intermediate output that the upstream node already stored, and injecting it directly into the node where they failed, the pipeline saves significant computation and time. Furthermore, introducing a `deferred_execution_docs` accounting category ensures document counts (`documents_in_scope = processed_docs + deferred_execution_docs + failed_docs + skipped_docs`) remain mathematically consistent across all nodes in the DAG.

## What Changes

- **Automatic Pre-Execution Resumption Planning**: Before flow execution, the orchestrator inspects `JobStatsStore` for failed documents from prior runs of the same `job_id`, checks retry thresholds against `max_retry_attempts` (default: 3, allowing `max_retry_attempts + 1` total attempts), and locates the stored output of the upstream node from the `job_id`, the `job_run_id` and the micro-batch number (`batch_num`) of the failure, i.e. `<data path>/<job_id>/<job_run_id>/data/<node>_<output index>[/<batch_num>]`. Resumption needs persisted node output, so it is active only when `global_config.data_storage_type` is set and is not `memory`; with `memory` (or unset) nothing is persisted and failed documents are re-ingested as before.
- **Source Modification Validation**: When documents fail, their source `modification_time` is recorded. During subsequent runs, Ingest compares the current source file's `modification_time` against the saved `modification_time`. If the file was modified in the source, the failure record is discarded and the document is re-ingested fresh from the root.
- **Deferred Execution Accounting**: Documents scheduled for downstream resumption are counted in `documents_in_scope` at the Ingest node and categorized as `deferred_execution_docs`. Upstream nodes carry this count forward without performing duplicate compute.
- **Node-Level Injection**: When execution reaches the failed node, the executor reads the rows of the deferred documents from the stored output of the parent node, combines them with incoming batch tables, and clears them from `deferred_execution_docs`. A document that failed at several nodes (for example in different branches) is injected at each of them.
- **Failure Record**: For each failed document the failure records (kept in a `KeyValueStoragePort`) hold, per failed node, the `job_run_id` and `batch_num` of the failing run, the failure count and the original error message. `batch_num` is carried into the `DeferredRecord` so the Parquet folder can be derived even though batch numbers differ between runs. No checkpoint data or data path is stored; the path is derived from `job_id`, `job_run_id` and `batch_num`.
- **New Public Configuration**: `global_config.max_retry_attempts` (integer, default 3) is a new public key. It is documented in `docs/reference/GLOBAL_CONFIG.md` and registered in `src/docpipe/core/orchestration/global_config_metadata.py`, together with the requirement that `data_storage_type` is not `memory`.
- **Micro-Batching Integration**: Fresh and deferred documents are partitioned into micro-batches after Ingest so that each batch carries its respective deferred document metadata until the resumption node.
- **Persistence & Metrics Updates**: `NodeStats` and storage stores (DuckDB, PostgreSQL, JSON) persist `deferred_execution_docs`. Successfully resumed documents are finalized in `IncrementalMetadataStore` and their failure entry for that node is removed.
- **Exhausted Retry Persistence & Reporting**: Documents that exhaust `max_retry_attempts` are permanently persisted to `IncrementalMetadataStore` with non-recoverable failure metadata and explicitly reported as `Failed (Max retries exhausted)`, including the original error message, in the post-execution job run report.

## Non-goals

- Dynamic DAG structural modification or handling schema changes between runs (deferred to a future change).
- Creating new REST endpoints or CLI subcommands to trigger retries (resumption is entirely automatic during normal incremental execution).
- Cross-job sharing of failure state or node output (strictly scoped to the same `job_id`).
- Resuming a document at a node with several inputs (for example `merge`); such documents are re-ingested.
- Concurrent runs of the same `job_id` (executions of a given `job_id` are assumed to be sequential; concurrent runs of the same `job_id` are out of scope).

## Capabilities

### Modified Capabilities
- `backend/flow-execution-engine`: Add node-level failure resumption, loading of stored node output and injection at target nodes, and `deferred_execution_docs` accounting across node executions.

## Impact

- **Layer**: Backend-only.
- **Affected Packages/Modules**:
  - `src/docpipe/core/constants/constants.py` (New metric and config constants)
  - `src/docpipe/core/job_management/domain/models/node_stats.py` (`deferred_execution_docs` field)
  - `src/docpipe/core/job_management/adapters/stores/` (DuckDB, Postgres, JSON stores for `deferred_execution_docs`)
  - `src/docpipe/core/operators/ingest/ingest_source.py` (Timestamp comparison, deferred docs emission)
  - `src/docpipe/core/orchestration/abstract_operator_executor.py` (Injection of stored node output & deferred tracking)
  - `src/docpipe/core/orchestration/abstract_orchestrator.py` & `prefect_engine.py` (Resumption planning)
  - `src/docpipe/core/job_management/application/services/report_generator.py` (Job run report failure details)
  - `src/docpipe/core/orchestration/models/resumption_plan.py` (`batch_num` on `FailedNode` and `DeferredRecord`)
  - `src/docpipe/core/orchestration/adapters/resumption_factory.py` (batch-aware table name)
  - `src/docpipe/core/orchestration/global_config_metadata.py` (`max_retry_attempts` and `data_storage_type` descriptions)
  - `docs/reference/GLOBAL_CONFIG.md` (`max_retry_attempts` section, `data_storage_type` note)
