# Tasks

## 1. Operator fix

- [x] 1.1 In `_index_and_record_results`, collect failed chunks as `doc_id_hash` values and record each failed document under `doc_hash_to_id.get(hash, hash)` with the name from `doc_hash_to_name`; verify with `tests/unit/operators/vectordb/test_vectordb_operator.py -k TestIndexingOutcome`.
- [x] 1.2 Compute `processed_docs` as documents in scope minus failed and skipped, and set `node_status` with `OperatorUtils.determine_execution_status()`; verify the all-failed, partial and all-indexed scenarios.

## 2. Tests

- [x] 2.1 Add `TestIndexingOutcomeStatusAndCounters` covering all-indexed, all-failed, partial document failure, several failed chunks of one document, `id` differing from `doc_id_hash` (chunked and non-chunked), counter consistency, skipped rows and node-to-job status aggregation; verify the new tests fail on the previous implementation.

## 3. Validation

- [x] 3.1 Run `pytest tests/unit/operators/vectordb` and `ruff check` / `ruff format --check` on the changed files; verify no new failures or findings.
