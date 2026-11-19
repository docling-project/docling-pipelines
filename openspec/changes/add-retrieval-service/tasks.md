# Tasks: Add Native Retrieval Service

All tasks are `[backend]` and scoped to <= 2 hours each, ordered by dependency.

## Group 1: Dependencies & Configuration

- [ ] 1.1 `[backend]` Add pinned `cachetools` to `[project.dependencies]` and optional `retrieval-redis = ["redis==..."]` extra in `pyproject.toml`, run `uv lock`, and sync `.venv`.
- [ ] 1.2 `[backend]` Add the `retrieval:` configuration schema (including `vector_stores` connection defaults for `milvus`, `opensearch`, `weaviate`) to `docling-pipelines-config.yaml.example` and add a typed accessor helper in `src/docpipe/core/retrieval/factories/config.py` using `DocpipeConfigLoader`.

## Group 2: Domain Models, Ports & Exceptions

- [ ] 2.1 `[backend]` Create `src/docpipe/core/retrieval/domain/models/query.py` matching `retrieval-v2` wire contracts (`QueryRequest`, `QueryResponse`, `ResultItem`, `ResultMetadata`, `AdditionalInfo`, `SearchConfig`, `SearchInferenceConfig`, `AssetType`, `ContainerType`, `SourceType`).
- [ ] 2.2 `[backend]` Create `src/docpipe/core/retrieval/domain/models/derivatives.py` and `plan.py` (`LibraryDescriptor`, `DocumentSetDescriptor`, `SqlTableTarget`, `VectorStoreTarget`, `DocumentClassContext`, `SubQuestion`, `QueryPlan`, `ExecutionWave`).
- [ ] 2.3 `[backend]` Create port ABCs under `src/docpipe/core/retrieval/domain/ports/` (`DocumentLibraryCatalogPort`, `SQLEnginePort` + `CancelHandle`, `VectorStoreQueryPort`, `RerankerPort`, `RetrievalCachePort`, `RetrievalACLPort`) and retrieval exceptions extending `DocpipeException` in `domain/exceptions.py`.

## Group 3: Adapters (Catalog, DuckDB SQL, Vector Backends, LLM, Cache, ACL)

- [ ] 3.1 `[backend]` Implement `LocalDocumentLibraryCatalogAdapter` (`adapters/catalog/local_catalog_adapter.py`) reading `DocumentLibraryService`, `DocumentSetService`, `DocumentSet.data_card` (PR #639 `derivative_store`, `embeddings`, `propagate_source_acls`), and `src/docpipe/core/document_classes/*.json`, merging with `retrieval.vector_stores` config defaults and optional `DocumentSet.metadata["retrieval_derivatives"]` overrides with `$VAR`/`${VAR}` secret resolution.
- [ ] 3.2 `[backend]` Implement `SqlValidator` (`application/sql_validator.py`) using `sqlglot` (`duckdb` dialect) to enforce single-statement read-only `SELECT` and strict table-allowlist authorization.
- [ ] 3.3 `[backend]` Implement `DuckDBSqlEngine` (`adapters/sql/duckdb_sql_engine.py`) with `read_only=True`, `SET enable_external_access = false`, `DESCRIBE` schema introspection, `asyncio.to_thread` offloading, timeout enforcement, and `conn.interrupt()` cancellation via `CancelHandle`.
- [ ] 3.4 `[backend]` Implement `MilvusVectorQueryAdapter` (`adapters/vector/milvus_query_adapter.py`) supporting hybrid dense + BM25 RRF search with dense-only fallback via `pymilvus` in `asyncio.to_thread`.
- [ ] 3.5 `[backend]` Implement `OpenSearchVectorQueryAdapter` (`adapters/vector/opensearch_query_adapter.py`) supporting k-NN / hybrid search and `allowed_users` ACL filtering via `opensearch-py`.
- [ ] 3.6 `[backend]` Implement `WeaviateVectorQueryAdapter` (`adapters/vector/weaviate_query_adapter.py`) using `weaviate-client` v4 (`near_vector` on named `vector_field`, `hybrid` for BM25 mode, deterministic client cleanup).
- [ ] 3.7 `[backend]` Implement `InferenceBridge`, `EmbeddingBridge`, and optional `RerankerPort` adapters (`ollama`, `watsonx`, `cross_encoder`) under `adapters/llm/`, wrapping `docpipe`'s `LLMInferencePort` and `LLMEmbeddingPort` with `asyncio.to_thread`.
- [ ] 3.8 `[backend]` Implement `MemoryRetrievalCache` (`cachetools.TTLCache`), optional `RedisRetrievalCache`, and `DocpipeACLAdapter` under `adapters/cache/` and `adapters/acl/`.

## Group 4: Application Layer & Factory Wiring

- [ ] 4.1 `[backend]` Implement `SqlRetriever` (`application/sql_retriever.py`) with schema + document-class prompt synthesis, correlation-key instruction, `SqlValidator` gate, and bounded `max_retries` self-correction loop.
- [ ] 4.2 `[backend]` Implement `VectorRetriever` (`application/vector_retriever.py`) with concurrent per-target dispatch, expanded `max(limit, rerank_candidates)` pool when reranker is configured, and graceful reranker fallback.
- [ ] 4.3 `[backend]` Implement `Synthesizer` (`application/synthesizer.py`) for unified SQL Markdown + deduplicated vector-chunk context formatting and grounded LLM answer generation.
- [ ] 4.4 `[backend]` Implement `SearchOrchestrator` (`application/search_orchestrator.py`) and `SearchJobQueue` (`application/job_queue.py`) with cache lookup/write, concurrent SQL + vector execution, partial-status degradation, queue depth limit (100 → `503`), and result TTL (900s / max 2,048).
- [ ] 4.5 `[backend]` Implement `OuterQueryPlanner`, `DAGExecutor`, and `MultiDocSetOrchestrator` (`application/outer_planner.py`, `dag_executor.py`, `multi_docset_orchestrator.py`) with single-set fast-path and wave-parallel multi-set execution.
- [ ] 4.6 `[backend]` Implement `RetrievalServiceFactory` (`factories/retrieval_factory.py`) wiring all adapters from `DocpipeConfigLoader`.

## Group 5: `retrieval-v2`-Compatible REST API Routes & DTOs

- [ ] 5.1 `[backend]` Create `retrieval-v2`-compatible Pydantic DTOs and domain↔DTO mappers in `src/docpipe/api/dto/retrieval_dto.py` (`QueryRequest` with `searchConfig` alias, `QueryResponse`, `ResultItem`, `ResultMetadata`, `AdditionalInfo`, `ErrorResponse`).
- [ ] 5.2 `[backend]` Create `src/docpipe/api/routes/retrieval.py` exposing v1 (`/v1/retrieval/advanced/search`, `/v1/retrieval/search`), v2 (`/v2/retrieval/advanced/search`, `/v2/retrieval/search`, `/v2/retrieval/advanced/search/result/{query_id}`, `/v2/retrieval/search/result/{query_id}`, `/v2/retrieval/search_data_assets`), and unauthenticated probes (`/v2/retrieval/healthz`, `/v2/retrieval/readyz`), and wire lifespan initialization/shutdown in `src/docpipe/api/main.py`.

## Group 6: Verification, Tests & Documentation

- [ ] 6.1 `[backend]` Add unit tests in `tests/unit/core/retrieval/` covering `LocalDocumentLibraryCatalogAdapter` (with PR #639 `DataCard` fixtures + sibling-branch metadata overrides), `DuckDBSqlEngine` (real temp DuckDB: read-only, timeout/cancel, `enable_external_access=false`), `SqlValidator` (injection/DDL/table-allowlist), `Milvus`/`OpenSearch`/`Weaviate` adapters (mocked clients), `SqlRetriever` retry loop, `VectorRetriever` reranking, `Synthesizer`, `MultiDocSetOrchestrator`, and `SearchJobQueue` limits/TTL.
- [ ] 6.2 `[backend]` Add API route unit tests in `tests/unit/api/routes/test_retrieval.py` verifying every scenario in `retrieval-api/spec.md` (v1 sync + alias, v2 async submit/poll + aliases + `search_data_assets`, `202`/`200`/`404`/`422`/`500`/`503`, `searchConfig` alias, `execution_time`, `/v2/retrieval/healthz`, `/v2/retrieval/readyz`, auth/ACL propagation).
- [ ] 6.3 `[backend]` Run `uv run ruff check --fix .`, `uv run mypy .`, `uv run pytest tests/unit/core/retrieval/ tests/unit/api/routes/test_retrieval.py -v`, `openspec validate add-retrieval-service --strict`, and `pre-commit run --from-ref origin/main --to-ref HEAD`.
- [ ] 6.4 `[backend]` Add user documentation under `docs/guides/RETRIEVAL_SERVICE_GUIDE.md` covering configuration, `DataCard`-based derivative discovery, and v1/v2 API usage.
