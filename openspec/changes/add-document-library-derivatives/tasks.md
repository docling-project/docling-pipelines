# Tasks

## 1. Domain

- [ ] 1.1 [backend] Add derivative dataclasses in `core/assets/derivatives/domain/models/derivative.py` (`DocumentSetDerivative`, `VectorStoreDerivative`, `EntityTableDerivative`, `EmbeddingSpec`, `CorrelationDetail`) with `to_dict`/`from_dict`
- [ ] 1.2 [backend] Add `DerivativeResolverPort` and `DerivativeStorePort` ABCs in `domain/ports/`
- [ ] 1.3 [backend] Add `ErrorCode.DERIVATIVE_INVALID_BOOKMARK`, `DERIVATIVE_RECORD_FAILED` and `DerivativeInvalidBookmarkException` (400)
- [ ] 1.4 [backend] Unit tests for model round-trip and `from_dict` tolerance of missing keys

## 2. Builder

- [ ] 2.1 [backend] Implement DAG ancestor computation in `DerivativeBuilder` (`@staticmethod`, keyword-only args)
- [ ] 2.2 [backend] Implement vector store extraction with config allowlist and secret-pattern filter
- [ ] 2.3 [backend] Implement nearest-`embeddings` resolution and embedding spec (provider, model, dimension)
- [ ] 2.4 [backend] Implement `id_field` / `correlatable` derivation from effective feature mappings (reuse `compute_default_feature_mappings`)
- [ ] 2.5 [backend] Implement entity table extraction; expose entity table naming helper from `EntityStoreOperator` as a `@staticmethod` without behavior change; mark `:memory:` as not retrievable
- [ ] 2.6 [backend] Unit tests: linear flow, branch scoping, default vs explicit mappings (use `sample_flows/use_cases/purchase_order_processing.json`), in-memory DuckDB, Postgres, secret fuzzing

## 3. Persistence and recorder

- [ ] 3.1 [backend] Implement `DocumentSetMetadataDerivativeStore` adapter (read-merge-write under `metadata["derivatives"]`, replace-by-store-key)
- [ ] 3.2 [backend] Implement `DerivativeRecorder` as `ExecutionLifecycleObserverPort` (capture `document_set` node metadata, record on complete, clear on fail/abort, dedupe batches)
- [ ] 3.3 [backend] Implement `CompositeExecutionObserver` with error isolation and lineage-strict behavior
- [ ] 3.4 [backend] Wire the composite in `OrchestratorFactory`; ensure recorder runs when lineage is disabled
- [ ] 3.5 [backend] Tests: failure isolation, no write on failed flow, no document_set node warning, metadata key preservation, re-run replaces entry, micro-batching records once
- [ ] 3.6 [backend] Verify the Prefect orchestrator path invokes the recorder (integration-style unit test with a fake)

## 4. Query service and REST

- [ ] 4.1 [backend] Implement `DerivativeQueryService` (resolver port impl) incl. correlation computation at read time
- [ ] 4.2 [backend] Implement bookmark encode/decode and pagination
- [ ] 4.3 [backend] Add DTOs and mapper with explicit field list (no path, no credentials)
- [ ] 4.4 [backend] Add `GET /document-libraries/{library_id}/derivatives` route, DI providers in `dependencies.py`, tolerate `container_id`/`container_type`
- [ ] 4.5 [backend] API tests: 200, empty set, 404, pagination three pages, invalid bookmark, limit bounds, redaction, 401 when auth enabled

## 5. Docs

- [ ] 5.1 [backend] Document the endpoint, the `id` mapping requirement for correlation, and the in-memory limitation in `docs/reference/` and `docs/operators/vectordb/vectordb_readme.md` (no duplication of OPERATORS.md content)

## 6. Validation

- [ ] 6.1 [backend] `uv run ruff check --fix .`
- [ ] 6.2 [backend] `uv run mypy .`
- [ ] 6.3 [backend] `uv run pytest tests/unit -m "unit and not integration"`
- [ ] 6.4 [backend] `openspec validate add-document-library-derivatives --strict`
