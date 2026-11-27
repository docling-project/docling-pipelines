# Tasks: Fix Milvus collection loading and query error handling

## 1. Implementation

- [x] 1.1 [backend] Add `LoadState`, `DocpipeException`, and `ErrorCode` imports to `batch_processor.py`
- [x] 1.2 [backend] Add the per-processor `_collection_loaded` flag in `MilvusBatchProcessor.__init__`
- [x] 1.3 [backend] Add `_ensure_collection_loaded` that loads on `NotLoad`, skips on `Loaded`, and returns `False` on `NotExist`
- [x] 1.4 [backend] Route `query_by_doc_names` through the load guard and raise `DocpipeException` on query failure
- [x] 1.5 [backend] Route `get_chunk_ids_for_documents` through the load guard and raise on any per-document query failure
- [x] 1.6 [backend] Verify `delete_documents_by_ids`, `get_document_count`, and `VectorDBOperator` are unchanged

## 2. Unit tests

- [x] 2.1 [backend] Update the two swallow-on-exception tests in `test_milvus_batch_processor.py` to assert the raised `DocpipeException`
- [x] 2.2 [backend] Add `test_milvus_collection_loading.py` covering load ordering, `Loaded`/`NotLoad`/`NotExist` states, load failure, load-state failure, caching, query results, query failures, partial-result rejection, and delete behavior
- [x] 2.3 [backend] Confirm the new unit tests fail against the original `batch_processor.py` (19 of 27 fail; the 8 that pass are guards for behavior that was already correct)

## 3. Milvus Lite integration tests

- [x] 3.1 [backend] Add `tests/integration/test_milvus_lite_collection_loading.py` with writer and reader in separate processes, using `tmp_path` databases only
- [x] 3.2 [backend] Confirm the reopen and stale-chunk tests fail against the original code (`assert [] == ...`) and pass with the fix

## 4. Stale loaded flag and server-mode tests

- [x] 4.1 [backend] Add `_query_loaded` and `_load_state_changed`: when a query fails on a cached loaded flag and the collection is no longer `Loaded`, clear the flag and repeat the load check and query once
- [x] 4.2 [backend] Add `TestStaleLoadedFlag` unit tests for release, drop, recreate, genuine failure without retry, unreadable state, retry limit, and chunk PK lookups
- [x] 4.3 [backend] Add `tests/integration/test_milvus_server_collection_loading.py` against a Milvus server using only temporary `docpipe_it_*` collections; skipped when no server is reachable
- [x] 4.4 [backend] Confirm the server tests fail against the original code (10 of 12) and that 4 of 12 fail with the fix but without stale-flag recovery

## 5. Validation

- [x] 5.1 [backend] Run the full `tests/unit/operators/vectordb` suite (1050 passed)
- [x] 5.2 [backend] Run `ruff check` and `ruff format --check` on the changed files
- [x] 5.3 [backend] Run `mypy` on the changed source file
- [x] 5.4 [backend] Run `interrogate` on the changed source file (100%)
- [x] 5.5 [backend] Run `bandit==1.8.6` on the changed source file
- [x] 5.6 [backend] Run `openspec validate fix-milvus-collection-loading-and-query-errors --strict` (pinned `@fission-ai/openspec@1.15.0` via npx; `validate --all --strict --no-interactive` also passes, 58 of 58)
- [x] 5.7 [backend] Confirm `employee_policy` collection is unchanged (no test writes to it). Server tests only create and drop `docpipe_it_*` collections and refuse to drop any other name. The Milvus server log shows no create, drop, insert, delete, load, release or flush event on `employee_policy` after the test session began; the collection is still present and `NotLoad`
