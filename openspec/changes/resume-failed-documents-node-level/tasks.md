# Tasks: Node-Level Failure Resumption with Deferred Execution Tracking

## 1. Constants, Models, and Storage Schema Updates

- [x] 1.1 [backend] Add `DEFERRED_EXECUTION_DOCS` and `DEFERRED_EXECUTION_DOCS_COUNT` to `Metrics.External` and `MAX_RETRY_ATTEMPTS` to `DocpipeConstants` in `src/docpipe/core/constants/constants.py`. Verify with `pytest tests/unit/core/constants/`.
- [x] 1.2 [backend] Add `deferred_execution_docs` list field to `NodeStats` domain model in `src/docpipe/core/job_management/domain/models/node_stats.py`.
- [x] 1.3 [backend] Update DuckDB, PostgreSQL, and JSON storage adapters in `src/docpipe/core/job_management/adapters/stores/` to serialize and deserialize `deferred_execution_docs`. Verify with `pytest tests/unit/core/job_management/`.

## 2. Resumption Service & Checkpoint Management

- [x] 2.1 [backend] Create `ResumptionPlan` domain model in `src/docpipe/core/orchestration/domain/models/resumption_plan.py` to hold per-node deferred document injection descriptors.
- [x] 2.2 [backend] Implement `ResumptionService` in `src/docpipe/core/orchestration/application/services/resumption_service.py` to query past failures and saved `modification_time` from `JobStatsStore`, check `max_retry_attempts` (allowing `max_retry_attempts + 1` total attempts), and locate upstream intermediate checkpoint parquet files.
- [x] 2.3 [backend] Add unit tests for `ResumptionService` in `tests/unit/core/orchestration/test_resumption_service.py` covering retry thresholds and missing checkpoint fallbacks. Verify with `pytest tests/unit/core/orchestration/test_resumption_service.py`.

## 3. Ingest Source & Unified Batching

- [x] 3.1 [backend] Update `IngestSourceOperator` in `src/docpipe/core/operators/ingest/ingest_source.py` to save `modification_time` on failure, compare source file `modified_time` against saved `modification_time`, emit `deferred_execution_docs`, and calculate total `documents_in_scope = fresh + deferred + failed + skipped`.
- [x] 3.2 [backend] Update `BatchManager` in `src/docpipe/core/orchestration/batch_manager.py` to distribute deferred document metadata alongside fresh documents across micro-batches.
- [x] 3.3 [backend] Add unit tests for `IngestSourceOperator` deferred doc emission in `tests/unit/operators/ingest/test_ingest_source_resumption.py`. Verify with `pytest tests/unit/operators/ingest/test_ingest_source_resumption.py`.

## 4. Operator Executor Checkpoint Injection & Deferred Accounting

- [x] 4.1 [backend] Update `AbstractOperatorExecutor` in `src/docpipe/core/orchestration/abstract_operator_executor.py` to load upstream checkpoint rows and concatenate them with input tables when the current node is the resumption target.
- [x] 4.2 [backend] Update `AbstractOperatorExecutor` to remove resumed documents from `deferred_execution_docs` upon injection and carry forward remaining deferred documents in node metadata.
- [x] 4.3 [backend] Update `NodeStatsAggregator` and `BatchAggregator` in `src/docpipe/core/job_management/application/` to aggregate `deferred_execution_docs` and enforce the consistency equation `total_docs = processed + deferred + failed + skipped`.

## 5. Exhausted Retries Persistence & Report Generation

- [x] 5.1 [backend] Update `ResumptionService` and `IncrementalUpdateService` to persist metadata records for retry-exhausted documents to `IncrementalMetadataStore` without purging their checkpoints, preventing automated re-execution.
- [x] 5.2 [backend] Update `JobReportGenerator` in `src/docpipe/core/job_management/application/services/report_generator.py` to format retry-exhausted documents with status `Failed` and reason indicating maximum retries were exhausted. Verify with `pytest tests/unit/core/job_management/test_report_generator.py`.

## 6. End-to-End Flow Execution & Integration Testing

- [x] 6.1 [backend] Wire `ResumptionService` into `FlowExecutor` / `AbstractOrchestrator` execution lifecycle in `src/docpipe/core/orchestration/abstract_orchestrator.py`.
- [ ] 6.2 [backend] Add integration test in `tests/integration/orchestration/test_node_level_resumption.py` verifying a multi-node flow (Ingest -> Extract -> Chunker -> Embeddings -> VectorDB) resumes failed documents at Node 4 on a second run without re-extracting, and verifies exhausted retry documents appear in the job report.
- [ ] 6.3 [backend] Run project test suite and linters (`pytest tests/unit tests/integration` and `ruff check src/`).
