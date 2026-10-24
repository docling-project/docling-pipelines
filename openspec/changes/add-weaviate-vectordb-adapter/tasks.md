# Tasks

## 1. Dependency gate and constants

- [ ] 1.1 [backend] Add `"weaviate-client==4.23.1"` to `[project.dependencies]` in `pyproject.toml` and `slim/pyproject.toml` (alphabetical). Run `uv lock` in the repo root and in `slim/`, then `uv pip install -e ".[dev]"`. These four files are committed together in one commit: `pyproject.toml`, `uv.lock`, `slim/pyproject.toml`, and `slim/uv.lock`. Record the resolved `grpcio` version and check it for published advisories. **Gate (design D11):** if resolution fails or the resolved grpcio has an advisory, stop and ask the maintainers whether to add a scoped override or wait for upstream; do not continue to group 2. Verify: `uv lock --check` passes in both directories, `python -c "import weaviate; print(weaviate.__version__)"` prints `4.23.1`, and `pytest tests/unit/operators/vectordb/ tests/integration/test_ingest_extract_chunk_embed_milvus_lite.py` passes, proving the existing Milvus and OpenSearch adapters still work on the new grpcio.
- [ ] 1.2 [backend] In `src/docpipe/core/constants/operator_constants.py`, add only the new constants to `OperatorConstants.VectorDB`: `WEAVIATE`, `CONNECTION_TYPE`, `GRPC_HOST`, `GRPC_PORT`, `GRPC_SECURE`, `CLUSTER_URL`, `BEARER_TOKEN` (with `# pragma: allowlist secret`), `DISTANCE_METRIC`, `TIMEOUT_INIT`, `TIMEOUT_QUERY`, `TIMEOUT_INSERT`, and `SKIP_INIT_CHECKS`. Reuse the existing `VectorDB.HOST`, `PORT`, `USERNAME`, `PASSWORD`, `SECURE`, `AUTH_TYPE`, `COLLECTION_NAME`, `INDEX_TYPE`, `INDEX_PARAMETERS`, and `Config.API_KEY`/`Config.BATCH_SIZE` rather than redefining them (design D3). Verify `uv run ruff check src/docpipe/core/constants/` and `uv run mypy src/docpipe/core/constants/` pass, that `detect-secrets` raises no new finding, and that `grep -c '"api_key"' src/docpipe/core/constants/operator_constants.py` is unchanged.

## 2. Configuration model and client

- [ ] 2.1 [backend] Create the `adapters/outbound/weaviate/` package with an `__init__.py` that exports nothing. Implement `config.py` (`ADAPTER_NAME`, `WeaviateConfig`) per design D3: field validator messages for `collection_name`, a `model_validator` for cloud → `cluster_url` and `auth_type` → credentials, and the pattern published via `json_schema_extra`. `config.py` must not import `weaviate`. Add `tests/unit/operators/vectordb/test_weaviate_config.py` covering defaults (including `add_sparse_vector: false`), every validation message, Literal enum values, JSON-schema enums and pattern, ignored extra keys, and that `VectorDBOperator.validate`-style `model_validate` yields `collection_name is not provided` for a missing name. Verify with `pytest tests/unit/operators/vectordb/test_weaviate_config.py`.
- [ ] 2.2 [backend] Implement `client.py` (`WeaviateClient`) per design D4: custom/cloud connect, `Auth.*` selection, `AdditionalConfig(Timeout(...))`, `resolve_env_var` on every credential, an `is_ready()` check, 503 `DocpipeException` naming the target without secrets, and an idempotent `close()`. Add `test_weaviate_client.py` with `weaviate.connect_to_*` patched, covering argument mapping for both connection types and all four auth types, `$VAR` and `${VAR}` resolution, the unset-variable error, the not-ready path, secrets absent from the exception and `caplog`, and double `close`. Verify the test file passes and `ruff`/`mypy` are clean on the package.

## 3. Collection schema management

- [ ] 3.1 [backend] Implement the static rules in `index_manager.py`: the feature-type-to-`DataType` table, the `field`/`word` tokenization rule, and `validate_property_names` (regex, reserved names, `vector`/`_vector`, reserved suffixes) per design D7. Add `test_weaviate_index_manager.py` cases for every type row, each tokenization case (pk, `id`/`name` targets, `keyword`, content), content `index_searchable` with the sparse flag both on and off, the `sparse_embeddings` mapping producing no property, and each rejected name. Verify with pytest.
- [ ] 3.2 [backend] Implement `collection_exists` and `create_collection(dimension_mapping)` per design D8: one self-provided named vector per entry, the selected index type and distance metric, `index_parameters` passthrough with a `TypeError`/`ValueError` → 400 conversion, 409 if the collection already exists, and `drop_collection`. In sparse mode, pass `inverted_index_config=Configure.inverted_index(bm25_k1=1.2, bm25_b=0.75)`, and omit `vector_config` when `dimension_mapping` is empty (design D14). First confirm against the Weaviate inverted-index docs or the client source that this is the v4 API, and note in the module docstring whether 1.2/0.75 are also the server defaults. Extend the index-manager tests with assertions on the `collections.create` arguments for single vectors, multiple vectors, sparse plus dense, and sparse-only, plus the invalid-parameter and already-exists errors. Verify with pytest.
- [ ] 3.3 [backend] Implement `validate_existing_collection(dimension_mapping)` per design D8: legacy (no named vectors), missing vector, sampled dimension mismatch, empty-collection skip, property type mismatch, and adding missing properties with `config.add_property`, with all mismatches aggregated into one 400 error. Include the sparse branches: an empty `dimension_mapping` skips every vector check (legacy and no-vector collections accepted), and in sparse mode a non-searchable content property fails. Add one test per branch, including that `add_property` is called with the mapped type and that the error message contains both dimensions. Verify with pytest.

## 4. Writes, deletes, and queries

- [ ] 4.1 [backend] Implement `prepare_document`, `create_batches` (count plus 3 MB cap), and `process_batches` (`data.insert_many` with UUIDv5 from the chunk primary key, `pk` property set, the vectors dict keyed by mapped names, `ErrorObject` → `{"index": {"_id", "error": {"reason"}}}`, and a whole-batch exception marking every object in it failed) per design D5/D6/D7. Skip the `sparse_embeddings` mapping, and omit `vector` from `DataObject` when there are no vector columns (sparse-only). Add `test_weaviate_batch_processor.py` cases for mapping, JSON serialization, skipped bytes, omitted `None`, skipped `sparse_embeddings`, sparse-only objects without vectors, batch splitting by count and by size, UUID determinism, the exact failed-item shape, and a batch exception followed by a successful batch. Verify with pytest.
- [ ] 4.2 [backend] Implement `delete_documents_by_ids` (UUIDv5, chunks of 500, summed `successful`/`failed`), `get_document_count` (aggregate, 0 on error), `get_chunk_ids_for_documents` (pk `like` prefix per file, offset paging of 1000, warning at the 10,000 cap, `{}` on error), and `query_by_doc_names` (contains_any on the mapped name property) per design D9. Add tests for 1,201 keys producing 3 delete calls, count error → 0, paging across two pages, the cap warning (`caplog`), lookup error → `{}`, and the name-query filter. Verify with pytest.

## 5. Adapter, registration, operator metadata, and user docs

- [ ] 5.1 [backend] Implement `adapter.py` (`@register_vector_store WeaviateAdapter`). In `__init__`, before `WeaviateClient.connect`, run in this order (design D7):
  1. require `collection_name`;
  2. if `add_sparse_vector` is true, require a mapping for the content feature (design D14);
  3. warn once on `schema_template_path` without reading it;
  4. drop any `allowed_users` mapping with one warning, and warn once if `allowed_users` is upstream but unmapped (design D13);
  5. run `validate_property_names` on the filtered mappings.

  Pass the filtered mappings to the index manager and batch processor. Name the public methods after `VectorStorePort` and delegate as the Milvus adapter does (design D1, "Port-method delegation"):
  - `create_index` → `index_manager.create_collection`;
  - `validate_existing_schema` → `index_manager.validate_existing_collection`;
  - `index_exists` → `index_manager.collection_exists`;
  - `index_documents` → `batch_processor.create_batches` then `process_batches`;
  - `delete_documents_by_ids`, `get_document_count`, `get_chunk_ids_for_documents`, `query_by_doc_names` → the `batch_processor` method of the same name;
  - `detect_vector_dimension` and `detect_all_vector_dimensions` → the shared helpers of the same name in `docpipe/utils/operators/vectordb_utils.py`. `embeddings_column` is read from adapter config and defaults to `OperatorConstants.Columns.EMBEDDINGS_COLUMN_DEFAULT`; `detect_vector_dimension` uses it when `column_name` is `None`;
  - `generate_chunk_pk` via `generate_positional_pk`, `refresh_index` as a no-op, and `close`.

  Register `weaviate` lazily in `vectordb_operator.py`.

  Add `test_weaviate_adapter.py` covering:
  - `VectorStoreFactory.list_adapters()` includes `weaviate`, and `create("weaviate", ...)` works with the client patched;
  - each rejection asserts that connect was not called;
  - sparse mode without a content mapping fails before connecting with the spec's message, and sparse mode with content mapped initializes;
  - `schema_template_path` set to a nonexistent file raises no error, emits one warning (`caplog`), and yields `collections.create` arguments identical to a run without it;
  - a mapped `allowed_users` is absent from the created properties and from every `DataObject`, with one warning;
  - an unmapped upstream `allowed_users` emits one warning;
  - importing the adapter package in a subprocess loads no module under `docpipe.core.operators.acl` or `docpipe.api` (`sys.modules` check);
  - positional primary key format, each delegation above (patched index manager, batch processor, and shared helpers called with the expected arguments), the `embeddings_column` fallback, and `close`.

  Verify with pytest.
- [ ] 5.2 [backend] Add Weaviate to `VectorDBOperator._get_vectordb_provider_schemas()`. Update the three hardcoded provider strings in `src/docpipe/core/operators/vectordb/vectordb_operator.py`:
  - the class docstring's "It delegates to provider-specific adapters (OpenSearch, Milvus)" and "Supported Vector Databases" list;
  - the `get_metadata()` description "Supports OpenSearch and Milvus through adapters.";
  - the `provider` attribute description "Supported values: opensearch, milvus.".

  `VALID_VALUES` comes from `VectorStoreFactory.list_adapters()` and needs no edit. Extend `tests/unit/operators/vectordb/test_vectordb_operator.py` with: `get_metadata()` `provider` valid values include `weaviate`; the operator description and `provider` description both mention Weaviate; `provider_config.providers.weaviate` exposes the `index_type`/`distance_metric` enums and `collection_name`; a mocked adapter returning one failed item causes its parent document to appear in `failed_docs` with reason "One or more chunks failed to index"; and an adapter exception during transform still calls `close`. Verify `pytest tests/unit/operators/vectordb/` passes.
- [ ] 5.3 [backend] Add `sample_flows/vectordb/weaviate_integration.json` (ingest → extract → chunk → embeddings → vectordb with `provider: "weaviate"`, self-hosted `localhost:8080`/`50051`, `distance_metric: "cosine"`, and feature mappings including `content → text`, modeled on `milvus_integration.json`). Verify it parses as JSON and that `docling-pipelines --flow-file sample_flows/vectordb/weaviate_integration.json --validate` passes with the local Weaviate from task 7.1 running.
- [ ] 5.4 [backend] Update `docs/operators/vectordb/vectordb_readme.md` per the operator README template, keeping section order:
  - Overview and Key Features mention Weaviate, its named vectors, and BM25 sparse mode;
  - a "Sparse (BM25) mode" subsection explains parity with Milvus. It gives a hybrid example and a sparse-only example, `collection.query.bm25(...)`/`collection.query.hybrid(...)` snippets, the top-level-flag precedence, the content-mapping requirement, and the sparse-only limitation for memory-mapped chunks (design D14 and Risks);
  - Parameters gains a "Weaviate `provider_config` fields" table;
  - Examples cover self-hosted, Weaviate Cloud with API key via `$WEAVIATE_API_KEY`, and two embedding models;
  - Troubleshooting covers the gRPC port 50051 being unreachable, collection-name capitalization, reserved property names, dimension mismatch, `QUERY_MAXIMUM_RESULTS` for files with more than 10,000 chunks, server `DEFAULT_QUANTIZATION`, sparse mode failing because content is unmapped or not searchable, ACL not supported (a mapped `allowed_users` is dropped with a warning; ACL-enforced reads are OpenSearch-only), and `schema_template_path` being ignored as OpenSearch-only;
  - the minimum supported Weaviate server version for client 4.23.1, taken from its release notes.

  Then update the `docs/reference/OPERATORS.md` VectorDB section (provider list, config example, field list) without duplicating the README. Update the provider enumerations that list vector databases: `README.md`, `ARCHITECTURE.md`, `USER_GUIDE_PIPELINE_SETUP.md`, `docs/README.md`, and `sample_flows/README.md` (the flow table and the `// Options: opensearch, milvus` comment). Check `AGENTS.md` and `docs/guides/SLIM_VARIANT.md` too, and edit them only if they enumerate vector databases. Verify that every relative link resolves, that code fences carry language tags, and that the README's JSON examples pass `WeaviateConfig.model_validate`. Do not edit `CHANGELOG.md`.

## 6. Flow enrichment

- [ ] 6.1 [backend] Implement `resource_metadata.py` (`WeaviateResourceMetadata.fetch`) per design D10 and add the `weaviate` branch to `VectorDBMetadataFetcher.fetch_metadata`. Because Weaviate now shares the sparse rule, update the stale "Milvus only" wording so it reads "Milvus and Weaviate":
  - in `metadata_fetcher.py`, the `compute_default_feature_mappings` docstring (rule 5, "[Milvus, add_sparse_vector=True only]"), the `add_sparse_vector` argument description ("When True (Milvus only)"), and the inline "Rule 5 — Milvus sparse path" comment;
  - in `vectordb_operator.py`, the "Add sparse vector configuration if present (Milvus-specific)" comment where `add_sparse_vector` is copied into `adapter_config`.

  Verify with `grep -rn "Milvus only\|Milvus-specific\|Milvus sparse path" src/docpipe/core/operators/vectordb/` that no stale occurrence remains, and that the OpenSearch-only schema-template wording is untouched.

  Add `test_weaviate_resource_metadata.py` covering: the five-key result for an existing collection (schema entries, sampled dimension, distance); a new name → supported with default mappings (and, with `add_sparse_vector`, `content → text` and `sparse_embeddings → sparse_embeddings`); no named vectors → unsupported with a reason when sparse is off, but supported with null similarity and dimension when sparse is on and content is searchable; `index_searchable` present on property entries; mapping resolution order (saved → live schema → defaults); no host/cluster URL → empty without connecting; connection error → empty; and client closed in every path. Extend `test_metadata_fetcher.py` with the router dispatch. Verify with pytest.

## 7. Real-server integration suite

- [ ] 7.1 [backend] Add `docker/docker-compose.weaviate.yml` (image `cr.weaviate.io/semitechnologies/weaviate:1.40.1`, ports 8080/50051, environment per design D12 including `AUTOSCHEMA_ENABLED=false`). Verify `docker compose -f docker/docker-compose.weaviate.yml up -d` reaches readiness (`curl -sf http://localhost:8080/v1/.well-known/ready`), then bring it down.
- [ ] 7.2 [backend] Add `tests/integration/weaviate/test_weaviate_with_container.py` (`@pytest.mark.integration`) with Docker and `DOCPIPE_TEST_WEAVIATE_HOST` handling, readiness polling, and a unique collection per test with teardown drop. Add the session-scoped auto-schema guard from design D12: inserting an undeclared property into a scratch collection must be rejected, otherwise the suite fails with a message that `AUTOSCHEMA_ENABLED=false` is required. Implement scenarios I-1 to I-10 from design D12 through `VectorDBOperator` and the adapter, including I-9 (sparse plus dense: BM25 and hybrid queries) and I-10 (sparse-only, in-memory chunks, re-run validation). Verify the guard passes and all ten scenarios pass against the compose server, and that pointing `DOCPIPE_TEST_WEAVIATE_HOST` at a server with auto-schema enabled makes the suite fail, not skip. If Docker or a server is unavailable, report the suite as blocked rather than counting skips as passes.

## 8. Integrated verification

- [ ] 8.1 [backend] Activate the venv and run `uv run ruff check --fix .` and `uv run mypy .` (report pre-existing failures separately), then `pytest tests/unit/` and `pytest -m integration tests/integration/weaviate tests/integration/test_ingest_extract_chunk_embed_milvus_lite.py` with the Weaviate compose server up. Verify no new failures relative to `main`.
- [ ] 8.2 [backend] Run the sample flow end to end against the compose server using the feature-testing workflow: `docling-pipelines --flow-file sample_flows/vectordb/weaviate_integration.json` twice, then `curl http://localhost:8080/v1/schema` and an object count. Verify the collection has the expected named vectors and properties, the object count is unchanged after the second run, and run metadata shows `chunks_failed_to_index: 0`.
- [ ] 8.3 [backend] Run `openspec validate add-weaviate-vectordb-adapter --strict`. Inspect the full diff for unrelated changes and confirm `CHANGELOG.md` is untouched. Commit with `git commit -s`, then run `pre-commit run --from-ref origin/main --to-ref HEAD`. Verify strict validation and all hooks pass, distinguishing pre-existing failures.

## Workflow follow-up

- Open the PR per `.bob/rules/github-pr.md` (body from template, pre-commit output pasted, `--body-file`).
- After review and merge readiness, run `openspec archive add-weaviate-vectordb-adapter` and confirm `openspec/specs/backend/vectordb-operator/spec.md` and `openspec/specs/backend/vectordb-weaviate/spec.md` are created.
