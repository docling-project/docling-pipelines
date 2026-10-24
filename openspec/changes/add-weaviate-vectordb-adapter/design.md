# Design

## Context

See [proposal.md](proposal.md) for motivation and scope. The requirements are in [specs/backend/vectordb-operator/spec.md](specs/backend/vectordb-operator/spec.md) (provider-agnostic contract) and [specs/backend/vectordb-weaviate/spec.md](specs/backend/vectordb-weaviate/spec.md) (Weaviate provider).

**Current shape of the VectorDB operator.** It is hexagonal:

- **Application:** `VectorDBOperator` (`core/operators/vectordb/vectordb_operator.py`) drives the transform phases: build doc-ID maps, detect vector dimensions, create or validate the resource, prepare chunk documents, clean up stale primary keys, write, and refresh. It depends only on the port.
- **Port:** `VectorStorePort` (`ports/outbound/vector_store.py`) has twelve methods, including `generate_chunk_pk` and `get_chunk_ids_for_documents`, which every adapter must implement. `close()` is optional.
- **Domain:** `domain/models.py` holds dataclasses only and is unchanged by this design.
- **Adapters:** `adapters/outbound/{opensearch,milvus}/` each follow `adapter.py` (port implementation), `client.py` (connection and auth), `config.py` (Pydantic `provider_config` model plus `ADAPTER_NAME`), `index_manager.py` (resource schema), `batch_processor.py` (writes, deletes, queries), and `resource_metadata.py` (read-only flow enrichment).
- **Registration:** `VectorStoreFactory` registers OpenSearch eagerly and Milvus lazily (`register_lazy`) from `vectordb_operator.py`. `_get_vectordb_provider_schemas()` publishes each adapter's JSON schema in operator metadata. `VectorDBMetadataFetcher` routes enrichment by `if adapter_name == ...`.

**Constraints observed in the current code:**

- `VectorDBOperator._index_and_record_results` parses failed items as `{"index": {"_id": ..., "error": {"reason": ...}}}` (OpenSearch bulk shape). Milvus returns `{"document": ..., "error": ...}`, so its per-chunk failures cannot be attributed to a document today. Weaviate must emit the parsed shape.
- `_cleanup_stale_pks` calls `get_chunk_ids_for_documents(file_ids)` and expects results keyed by file ID, with chunk primary keys produced by `generate_chunk_pk`.
- Adapters connect in `__init__` (OpenSearch and Milvus both call `get_client()`), and `VectorDBOperator.transform` calls `adapter.close()` in `finally`.
- `VectorDBOperator.validate` runs `adapter.get_config_schema().model_validate(provider_config)`. A missing field is reported as `"<field> is not provided"`; any other error is reported as the Pydantic message.
- `compute_default_feature_mappings` maps the primary feature to `pk`, `id` to `document_id`, `name` to `document_name`, and the first vector to `vector_embeddings`. All of these are legal Weaviate property names. With `add_sparse_vector=True` it also maps the sparse feature to `sparse_embeddings` and `content` to `text`.
- **Milvus sparse mode today is server-computed BM25, not stored sparse vectors.**
  - `MilvusIndexManager` declares a `SPARSE_FLOAT_VECTOR` field, which a Milvus `Function(BM25)` fills from the content field. The content field is non-nullable with an analyzer, and BM25 uses k1 = 1.2 and b = 0.75.
  - `MilvusBatchProcessor.prepare_document` skips the `sparse_embeddings` feature.
  - `VectorDBOperator._resolve_vector_dimensions` allows sparse-only runs: with no dense columns it returns an empty dimension mapping.
- `slim/pyproject.toml` also pins `pymilvus` and `opensearch-py`, so the slim variant needs the new dependency too.

**Upstream facts that shape the approach** (official docs and PyPI, verified 2026-10-15):

- `weaviate-client` latest is **4.23.1** (2026-09-07), BSD-3-Clause, Python ≥3.10. It requires `httpx<0.29`, `pydantic>=2.12`, `authlib>=1.6.7`, `protobuf<7`, `validators`, and **`grpcio<1.80.0`**. The main branch still caps grpcio there.
- Server latest is 1.40.1 (image `cr.weaviate.io/semitechnologies/weaviate:1.40.1`). The v4 client requires the gRPC port (default 50051) in addition to HTTP (8080).
- Collections must match `^[A-Z][_0-9A-Za-z]*$`. Properties must match `[_A-Za-z][_0-9A-Za-z]*`, with `id`, `_id`, and `_additional` reserved and `vector`/`_vector` discouraged.
- Default text tokenization is `word`, which splits on non-alphanumerics, so `abc_chunk_3` becomes `[abc, chunk, 3]`. `field` tokenization keeps the whole value as one token.
- Self-provided named vectors use `Configure.Vectors.self_provided(name=..., vector_index_config=Configure.VectorIndex.hnsw|flat|dynamic(distance_metric=...))` (client ≥4.16). No dimension is declared; it is fixed by the first insert.
- `data.delete_many` deletes at most `QUERY_MAXIMUM_RESULTS` (default 10,000) objects per call.
- `data.insert_many` returns `BatchObjectReturn.errors: dict[int, ErrorObject(message, object_)]`.
- Embedded Weaviate is experimental, Linux/macOS only, and downloads a binary at runtime. Auto-schema is on by default (`AUTOSCHEMA_ENABLED`). No quantization is applied by default unless the server sets `DEFAULT_QUANTIZATION`.
- Hybrid search fuses vector search with BM25 keyword search over the inverted index (default fusion `relativeScoreFusion`, alpha 0.75). The docs describe no native sparse-vector type for user-supplied sparse embeddings. BM25 runs over text properties with `index_searchable=True`, and BM25 parameters are set per collection through the inverted-index config. The defaults are believed to be k1 = 1.2 and b = 0.75; task 3.2 confirms them, since that docs page could not be fetched during planning.

## Goals / Non-Goals

**Goals:**

- A `weaviate` adapter that is structurally a sibling of the Milvus adapter (same file split, same lazy registration, same enrichment contract). A reviewer who knows one adapter should be able to read the other.
- Idempotent re-ingest with no duplicate chunks, using a deterministic object identity rather than delete-then-insert.
- Per-chunk failure attribution to documents, which Milvus lacks today.
- An explicit, typed schema: the adapter never relies on server auto-schema.
- Test coverage at three levels: unit (client mocked), operator (adapter mocked), and integration (real server, Docker-gated).

**Non-Goals (design level, in addition to the proposal's):**

- No change to `VectorStorePort`, `domain/models.py`, `VectorStoreFactory`, or the failed-item parsing in `VectorDBOperator`.
- No lazy connection. Weaviate connects in `__init__` like its siblings. Moving all adapters to lazy connections is a separate change.
- No reuse of Milvus code via inheritance. Shared helpers come only from `utils/operators/vectordb_utils.py`.
- No frontend changes.

## Decisions

### D1. Package layout and DDD boundaries

New package `core/operators/vectordb/adapters/outbound/weaviate/`. Its `__init__.py` deliberately exports nothing, as Milvus does.

| File | Layer | Responsibility |
|---|---|---|
| `config.py` | adapter (config contract) | `ADAPTER_NAME = "weaviate"`, `WeaviateConfig(BaseModel, extra="ignore")`. Field validators carry the spec's messages. A `model_validator(mode="after")` enforces cross-field rules (cloud → `cluster_url`; `auth_type` → its credentials). |
| `client.py` | adapter (infrastructure) | `WeaviateClient`: build credentials, connect (`connect_to_custom` / `connect_to_weaviate_cloud`), `is_ready()` check, `get_client()`, `close()`. Errors become `DocpipeException(status_code=503, OPERATOR_EXECUTION_FAILED)` naming the target, never the secrets. |
| `index_manager.py` | adapter | Static name and type rules (`validate_property_names`, `map_feature_type`, `tokenization_for`), `collection_exists`, `create_collection`, `validate_existing_collection`, `drop_collection` (used by tests). These are internal; the adapter exposes them through port methods (see below). |
| `batch_processor.py` | adapter | `prepare_document`, `create_batches`, `process_batches`, `delete_documents_by_ids`, `get_document_count`, `get_chunk_ids_for_documents`, `query_by_doc_names`. |
| `adapter.py` | adapter (port implementation) | `@register_vector_store class WeaviateAdapter(VectorStorePort)` wiring the three components. Fail-fast checks run before connecting. Public methods use the `VectorStorePort` names and delegate as the Milvus adapter does (table below). |
| `resource_metadata.py` | adapter (read-only) | `WeaviateResourceMetadata.fetch(...)`, with the same injected-callable signature as `MilvusResourceMetadata`. |

**Port-method delegation** (same shape as `MilvusAdapter`):

| `VectorStorePort` method on `WeaviateAdapter` | Delegates to |
|---|---|
| `create_index(*, dimension_mapping)` | `index_manager.create_collection(dimension_mapping=...)` |
| `validate_existing_schema(*, dimension_mapping)` | `index_manager.validate_existing_collection(dimension_mapping=...)` |
| `index_exists()` | `index_manager.collection_exists()` |
| `index_documents(documents)` | `batch_processor.create_batches(...)` then `batch_processor.process_batches(...)` |
| `delete_documents_by_ids`, `get_document_count`, `get_chunk_ids_for_documents`, `query_by_doc_names` | the `batch_processor` method of the same name |
| `detect_vector_dimension(*, table, column_name)` | shared `detect_vector_dimension` in `docpipe/utils/operators/vectordb_utils.py`; `column_name=None` falls back to `self.embeddings_column`, read from the adapter config key `OperatorConstants.Columns.EMBEDDINGS_COLUMN` and defaulting to `EMBEDDINGS_COLUMN_DEFAULT` |
| `detect_all_vector_dimensions(table, *, vector_columns)` | shared `detect_all_vector_dimensions` in `docpipe/utils/operators/vectordb_utils.py` |
| `generate_chunk_pk`, `refresh_index`, `close` | `generate_positional_pk` (D5), a no-op, and `WeaviateClient.close` |

Later sections that name `create_collection` or `validate_existing_collection` refer to the index-manager methods behind `create_index` and `validate_existing_schema`.

The application layer (`VectorDBOperator`) touches only `VectorStorePort` and `VectorStoreFactory`. `metadata_fetcher.py` imports `resource_metadata` lazily inside the `weaviate` branch, so the `weaviate` package is never imported unless that provider is used. Nothing under `domain/` or `ports/` imports from `adapters/`.

### D2. Registration: lazy, like Milvus

`VectorStoreFactory.register_lazy("weaviate", "...weaviate.adapter", "WeaviateAdapter")` goes in `vectordb_operator.py` next to Milvus. `_get_vectordb_provider_schemas()` gains a `WEAVIATE_ADAPTER_NAME: model_schema_to_docpipe(WeaviateConfig.model_json_schema())` entry. Importing `config.py` must not import `weaviate`, which preserves the lazy-import guarantee for metadata.

*Alternative:* eager registration like OpenSearch. Rejected because it would import `weaviate`/`grpc` on every operator-metadata request even though the package is installed.

### D3. `WeaviateConfig` fields

`collection_name` (required; validator enforces `^[A-Z][_0-9A-Za-z]*$` with the spec message; `json_schema_extra` publishes the pattern in operator metadata).

`connection_type: Literal["custom","cloud"] = "custom"`; `host = "localhost"`; `port = 8080`; `secure = False`; `grpc_host: str | None` (defaults to `host`); `grpc_port = 50051`; `grpc_secure: bool | None` (defaults to `secure`); `cluster_url: str | None`.

`auth_type: Literal["none","api_key","bearer_token","client_password"] = "none"`; `api_key`, `bearer_token`, `username`, `password` (`str | None`, all accept `$VAR` / `${VAR}`).

`timeout_init = 30`, `timeout_query = 60`, `timeout_insert = 120` (seconds), `skip_init_checks = False`, `batch_size = 100` (≥1).

`index_type: Literal["hnsw","flat","dynamic"] = "hnsw"`; `distance_metric: Literal["cosine","dot","l2-squared","manhattan","hamming"] = "cosine"`; `index_parameters: dict = {}`; `add_sparse_vector: bool = False` (schema parity with `MilvusConfig`; see D14 for precedence).

- **Defaults** follow Weaviate's own: cosine distance and HNSW. Milvus and OpenSearch default to L2, but L2 is not a Weaviate default and `l2-squared` is not identical to L2. `hfresh` is excluded because it is new and not yet documented as stable for self-provided vectors.
- **Validation errors** use plain `ValueError` messages so `VectorDBOperator.validate` surfaces them unchanged ("Value error, ...").
- **Operator-injected keys.** `VectorDBOperator.__init__` adds `available_features`, `feature_mappings`, `add_sparse_vector` (when set), and `schema_template_path` (when set) to `adapter_config`. None of them are `WeaviateConfig` fields, so `extra="ignore"` keeps validation unaffected. The adapter reads `available_features` and `feature_mappings` and applies `add_sparse_vector` (D14). It handles `schema_template_path` by logging one warning that the option is OpenSearch-only and never reading it.
- **Constants reused** (no new definitions): `OperatorConstants.VectorDB.HOST`, `PORT`, `USERNAME`, `PASSWORD`, `SECURE`, `AUTH_TYPE`, `COLLECTION_NAME`, `INDEX_TYPE`, `INDEX_PARAMETERS`, plus `OperatorConstants.Config.API_KEY` and `Config.BATCH_SIZE`. `api_key` is already defined in `Config`, so it is not duplicated under `VectorDB`.
- **Constants added** to `OperatorConstants.VectorDB`: `WEAVIATE`, `CONNECTION_TYPE`, `GRPC_HOST`, `GRPC_PORT`, `GRPC_SECURE`, `CLUSTER_URL`, `BEARER_TOKEN` (with `# pragma: allowlist secret`, as `Config.API_KEY` has, for detect-secrets), `DISTANCE_METRIC`, `TIMEOUT_INIT`, `TIMEOUT_QUERY`, `TIMEOUT_INSERT`, `SKIP_INIT_CHECKS`. `DISTANCE_METRIC` (`"distance_metric"`) is deliberately distinct from Milvus's `METRIC_TYPE` (`"metric_type"`).

*Alternative:* infer cloud vs self-hosted from whether `cluster_url` is set. Rejected because an explicit `connection_type` keeps configuration unambiguous and gives deterministic validation messages.

### D4. Connection and authentication

- **`custom`** calls `weaviate.connect_to_custom(http_host, http_port, http_secure, grpc_host, grpc_port, grpc_secure, auth_credentials, additional_config=AdditionalConfig(timeout=Timeout(init, query, insert)), skip_init_checks)`.
- **`cloud`** calls `weaviate.connect_to_weaviate_cloud(cluster_url, auth_credentials, additional_config, skip_init_checks)`.
- **Credentials:** `Auth.api_key(key)`, `Auth.bearer_token(access_token=...)`, or `Auth.client_password(username, password)`; `None` for `none`. Values pass through `resolve_env_var` (as in the OpenSearch adapter). An unset variable raises before any network call.  # pragma: allowlist secret
- **Readiness:** after connecting, `client.is_ready()` must be true, or a 503 `DocpipeException` is raised.
- **Logging:** log lines use `%s` formatting and contain the host or cluster URL, `connection_type`, and `auth_type` only.

### D5. Object identity: positional primary key → UUIDv5

`generate_chunk_pk` returns `generate_positional_pk(file_id, chunk_index)` (`{sha3_512(file_id)}_chunk_{i}`), the OpenSearch strategy. The object UUID is `weaviate.util.generate_uuid5(chunk_pk)`, and the primary key is also stored verbatim in property `pk`, so stale-chunk lookup and debugging never need to reverse a UUID. Weaviate batch writes replace an existing object with the same UUID, which makes re-ingest an in-place upsert. Integration test I-3 asserts this, since the replace semantics are the one upstream behavior this design depends on.

*Alternative:* Milvus's content-hash key (`{file_hash}_{content_hash}`). Rejected because it turns every content edit into a delete plus insert and churns UUIDs. Positional keys keep UUIDs stable across edits and limit deletes to genuinely removed tail chunks.

### D6. Write path: `data.insert_many` per adapter-built batch

`create_batches` mirrors Milvus: a batch holds up to `batch_size` objects and about 3 MB of estimated payload (`calculate_batch_size_bytes`). Each batch is sent with `collection.data.insert_many([DataObject(properties, uuid, vector={name: list[float]})])`.

- For each `(index, ErrorObject)` in `result.errors`, emit `{"index": {"_id": chunk_pk_of(index), "error": {"reason": err.message}}}`.
- A raised exception marks every object in that batch failed with the exception text. Later batches still run.
- Success count = batch size minus errors.

*Alternatives:* `collection.batch.fixed_size()/dynamic()` context managers, which run background threads with their own retry and re-batching. That duplicates our size-aware batching, makes index-to-chunk attribution indirect (`failed_objects` after exit), and is harder to unit test deterministically. `batch.stream()` (server-side batching, ≥1.36) gives better throughput but would raise the minimum server version. It is listed as a follow-up.

### D7. Schema mapping and tokenization

| Feature `type` | Weaviate `DataType` | Value handling |
|---|---|---|
| `text`, `string`, `keyword`, `date` | `TEXT` | Non-`str` values are JSON-serialized |
| `int8`/`int16`/`int32`/`int64`/`integer`/`long`/`short`/`byte` | `INT` | as-is |
| `float`/`double` | `NUMBER` | as-is |
| `bool`/`boolean` | `BOOL` | as-is |
| `json`/`object`/`nested`, unknown | `TEXT` | `json.dumps(value, default=str)`; JSON strings are kept verbatim |

- **Tokenization:** `field` for `pk`, the target names mapped from `id` and `name`, and `keyword`-typed features. `word` for everything else. All text properties keep `index_filterable` and `index_searchable` at their defaults (true).
- **Always declared:** the content property (mapped name of `content`, else `text`) is always declared, as in Milvus. It is `word`-tokenized and `index_searchable` in every mode, so BM25 is available even with `add_sparse_vector` false. `bytes` values are skipped and `None` values are omitted (Weaviate stores the property as null).
- **Rejected types:** `DATE` is avoided because pipeline dates are not guaranteed RFC 3339. `OBJECT` is avoided because Weaviate requires nested properties to be declared up front.
- **Property-name checks:** `validate_property_names` runs in `WeaviateAdapter.__init__` before `WeaviateClient.connect`, so bad mappings fail fast without a live server. It applies the regex, the reserved names, the `vector`/`_vector` names, and the reserved suffixes (`_searchable`, `_rangeable`, `_temp`, `__meta_count`, `_propertyLength`, `_nullState`).
- **Sparse mode (D14):** the `sparse_embeddings` mapping is skipped when building properties and documents, as Milvus skips it on insert.
- **`__init__` order, all before connecting:**
  1. Require `collection_name`.
  2. If `add_sparse_vector` is true, require a mapping for the content feature (D14).
  3. Warn once on `schema_template_path` (D3).
  4. Drop and warn on an ACL mapping (D13).
  5. Run `validate_property_names` on the remaining mappings.

  The filtered mapping list is the one passed to the index manager and batch processor, so a dropped ACL mapping can reach neither the schema nor the objects.

### D8. Collection creation and existing-collection validation

- **`create_collection`:** raises 409 if the collection exists (parity with Milvus). It calls `client.collections.create(name, properties=[...], vector_config=[Configure.Vectors.self_provided(name=mapped(col), vector_index_config=<index>(distance_metric=..., **index_parameters))])`. A `TypeError`/`ValueError` from `index_parameters` becomes a 400 `DocpipeException` naming the parameter. Multi-tenancy, replication, and quantization are left at server defaults.
  - In sparse mode it also passes `inverted_index_config=Configure.inverted_index(bm25_k1=1.2, bm25_b=0.75)`.
  - When `dimension_mapping` is empty (a sparse-only run), it omits `vector_config`. The adapter does not depend on how the server represents a collection with no declared vectors, because sparse-only runs skip vector validation (below) and write no vectors.
- **`validate_existing_collection(dimension_mapping)`** reads `collection.config.get()`:
  1. If `dimension_mapping` is empty (sparse-only run), skip steps 2-4 entirely. Otherwise, if `vector_config` is empty, fail as a legacy single-vector collection.
  2. Every mapped vector name must be present.
  3. If `aggregate.over_all(total_count=True)` > 0, fetch one object with `include_vector=[names]` and compare each vector's length to the runtime dimension.
  4. For mapped properties that exist, the data type must equal the D7 mapping.
  5. Missing mapped properties are added with `collection.config.add_property(Property(...))` and logged.
  6. In sparse mode, the content property must have `index_searchable=True`. A newly added content property satisfies this. An existing non-searchable one fails, because searchability cannot be enabled after creation.

  All mismatches are collected into one `DocpipeException` (400), which the operator turns into per-document failures.

*Alternative:* let auto-schema add missing properties. Rejected because it infers types from the first value (for example `"42"` becomes text), which would silently diverge from the declared mapping, and it may be disabled on the server. Integration tests run with `AUTOSCHEMA_ENABLED=false` to prove the adapter never depends on it.

### D9. Stale-chunk lookup, deletes, queries, count

- **`get_chunk_ids_for_documents(file_ids)`:** for each file, `query.fetch_objects(filters=Filter.by_property("pk").like(f"{sha3_512(file_id)}_chunk_*"), return_properties=["pk"], limit=1000, offset=k*1000)` until a short page, keyed by file ID. Matching on the primary-key prefix (Milvus's approach) works regardless of whether the user mapped `id`. Cursor iteration (`after=`) does not accept filters, so offset paging is bounded by `QUERY_MAXIMUM_RESULTS`. On reaching 10,000 the method logs a warning naming the file and returns what it has. Any exception logs and returns `{}`, matching siblings.

  This filter depends on D7's `field` tokenization of `pk`. Under the default `word` tokenization, `<hash>_chunk_3` would be stored as separate tokens (`<hash>`, `chunk`, `3`), so a whole-value prefix pattern would not match as intended and could miss stale chunks. The index-manager tests (task 3.1) pin `pk` to `field`, and integration scenario I-4 exercises the lookup on a real server.
- **`delete_documents_by_ids(chunk_pks)`:** converts primary keys to UUIDv5 in chunks of 500 (`BULK_DELETE_BATCH_SIZE`, siblings' value) and calls `data.delete_many(where=Filter.by_id().contains_any(uuids))`, summing `successful` and `failed`. Chunking keeps each call under the 10,000 cap.
- **`get_document_count()`:** `aggregate.over_all(total_count=True).total_count`, or 0 on error.
- **`query_by_doc_names(names)`:** `fetch_objects(filters=Filter.by_property(<mapped name field>).contains_any(names), return_properties=fields)` returning `properties` dicts. The name property is `field`-tokenized (D7), so matching is exact.
- **`refresh_index()`:** a no-op with a debug log. Writes are visible once `insert_many` returns; async indexing, if enabled server-side, affects only vector-index freshness.

### D10. Flow enrichment (`WeaviateResourceMetadata`)

- **Skip condition:** if neither `host` (custom) nor `cluster_url` (cloud) is present, return `empty_result()`.
- **Fetch:** connect with `WeaviateClient`, then read:
  - `available_resources = sorted(client.collections.list_all(simple=True))`;
  - for an existing selected collection, `selected_resource_schema` with properties as `{type: DATA_TYPE.upper(), is_primary: name == "pk", description}` and named vectors as `{type: "VECTOR", dimension: <sampled or None>, index_info: {index_type, metric_type: distance}, index_created: True}`;
  - `stored_resource_metadata` from the first named vector;
  - `is_supported`: true for an empty or new name, false with a reason when there are no named vectors, unless `add_sparse_vector` is true and the mapped content property is `index_searchable`. In that sparse-only case `stored_resource_metadata` is `{vector_similarity: None, dimension_size: None}`. Property entries carry `index_searchable` so enrichment consumers and tests can see BM25 eligibility. (Milvus's `_is_supported` marks sparse-only collections unsupported; Weaviate deliberately does not, and Milvus is not changed here.)
- **`feature_mappings`:** saved mappings, then live-schema derivation (`pk` → primary feature, first `VECTOR` → first vector feature, identity names; when `add_sparse_vector` is true and the content property is searchable, also the sparse feature → `sparse_embeddings`), then `default_feature_mappings_from_features` (which already adds the sparse and content defaults in sparse mode).
- **Errors and cleanup:** any exception logs a warning and returns `empty_result()`. The client is closed in `finally`. `MilvusResourceMetadata.fetch` does not close its client; that is a known Milvus gap, deliberately left alone here because this change does not modify the Milvus adapter. The difference is intentional: Weaviate does the right thing, and fixing Milvus belongs in a separate change.

`VectorDBMetadataFetcher.fetch_metadata` gains an `OperatorConstants.VectorDB.WEAVIATE` branch.

### D11. Dependency and lockfiles

- **Pins:** add `"weaviate-client==4.23.1"` to `[project.dependencies]` in both `pyproject.toml` and `slim/pyproject.toml`, keeping alphabetical order.
- **Locks:** run `uv lock` in the repo root and in `slim/`, then `uv pip install -e ".[dev]"`. Commit both `pyproject.toml` files and both `uv.lock` files together, per `AGENTS.md`.
- **Expected effect:** `grpcio` resolves to **1.78.0**, down from 1.84.0. PyPI has no 1.79.x release, and 1.78.1 is yanked, so 1.78.0 is the newest installable version below the `<1.80.0` cap. pymilvus (`>=1.66.2`), milvus-lite (`>=1.50`), and the telemetry exporter accept it. A trial `uv lock` on a copy of the root `pyproject.toml` resolved 499 packages, adding only `weaviate-client 4.23.1` and `validators 0.36.0` and changing only `grpcio`. OSV lists no advisories for 1.78.0. Task 1.1 repeats both checks on the real files, and also runs them for `slim/`.
- **Decision gate (task 1.1):**
  - If resolution fails, or the downgraded grpcio has a published advisory, stop and ask the maintainers whether to add a scoped `override-dependencies` entry or wait for upstream.
  - A scoped override such as `grpcio>=1.84` runs weaviate-client outside its declared range and would need integration-test evidence.
  - The other path is to wait for upstream to lift `<1.80`.

### D12. Testing strategy

| Level | Location | Scope |
|---|---|---|
| Unit: config | `tests/unit/operators/vectordb/test_weaviate_config.py` | defaults, every validator message, Literal enums equal index-manager constants, JSON schema enums and pattern, `extra` ignored |
| Unit: client | `test_weaviate_client.py` | custom/cloud call arguments, each auth helper, `$VAR`/`${VAR}` resolution, unset variable error, not-ready → 503, secrets absent from exception text and logs (`caplog`), idempotent `close` |
| Unit: index manager | `test_weaviate_index_manager.py` | type table, tokenization rule, property-name rejection cases, one named vector per dimension entry, invalid `index_parameters` → 400, each existing-collection branch (legacy, missing vector, dimension mismatch, empty skip, type mismatch, missing property added); sparse mode: BM25 `inverted_index_config` passed, no `vector_config` for empty `dimension_mapping`, sparse-only validation skips vector checks, non-searchable content property fails, `sparse_embeddings` mapping produces no property |
| Unit: batch processor | `test_weaviate_batch_processor.py` | `prepare_document` mapping, JSON, bytes, and None handling; `sparse_embeddings` skipped; sparse-only objects carry no `vector`; count and size batching; `insert_many` error → failed-item shape; whole-batch exception; UUIDv5 determinism; delete chunking at 500; count; stale lookup paging and 10k cap warning; `query_by_doc_names` |
| Unit: adapter | `test_weaviate_adapter.py` | lazy factory registration and `create`, `get_config_schema`, sparse mode without a content mapping rejected before `connect`, sparse mode with content mapped accepted, reserved-name rejection before `connect` (assert connect not called), `schema_template_path` (missing file) → no error, one warning, identical `collections.create` arguments; mapped `allowed_users` dropped from schema and objects with one warning; unmapped upstream `allowed_users` → one warning; import isolation (no module under `core/operators/acl` or `docpipe.api` loaded); positional primary key, delegation, `close` |
| Unit: enrichment | `test_weaviate_resource_metadata.py` + `test_metadata_fetcher.py` | five keys, supported rules (including sparse-only supported and non-sparse no-vector unsupported), `index_searchable` on property entries, mapping resolution order including sparse defaults, unreachable/no host → empty, client closed; router dispatches `weaviate` |
| Operator | `test_vectordb_operator.py` | `provider` valid values and `providers.weaviate` schema; mocked adapter returning one failed item → parent document in `failed_docs`; adapter closed on exception |
| Integration | `tests/integration/weaviate/test_weaviate_with_container.py` (`@pytest.mark.integration`) | I-1 create + write via `VectorDBOperator`; I-2 two named vectors; I-3 re-ingest leaves count unchanged and UUID stable with new text; I-4 shrink deletes tail; I-5 dimension mismatch → FAILED; I-6 pre-created INT property + string value → exactly one failed chunk attributed; I-7 enrichment against live server; I-8 delete >500 primary keys; I-9 sparse plus dense: `collection.query.bm25` and `collection.query.hybrid` both return the target chunk, and the collection config shows k1 = 1.2 and b = 0.75; I-10 sparse-only (no embeddings column): collection has no named vectors, chunks written, BM25 returns them, and a second run passes existing-collection validation |

The integration server comes from `docker/docker-compose.weaviate.yml`: image `cr.weaviate.io/semitechnologies/weaviate:1.40.1`, ports 8080/50051, and environment `AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=true`, `PERSISTENCE_DATA_PATH=/var/lib/weaviate`, `DEFAULT_VECTORIZER_MODULE=none`, `AUTOSCHEMA_ENABLED=false`, `CLUSTER_HOSTNAME=node1`.

The suite follows the OpenSearch container test's skip-if-no-Docker helpers and supports both `docker compose` and `docker-compose`. If `DOCPIPE_TEST_WEAVIATE_HOST` is set, it uses that server instead of starting a container (the CI-friendly path, mirroring `DOCPIPE_TEST_POSTGRES_DSN`). Readiness is polled with `client.is_ready()`. Each test uses a unique collection name and drops it in teardown.

**Auto-schema guard.** A session-scoped fixture creates a scratch collection with one declared property and inserts an object carrying an undeclared property. If the server accepts it, auto-schema is on, and the whole suite **fails** (not skips) with a message that `AUTOSCHEMA_ENABLED=false` is required. This matters most for externally supplied `DOCPIPE_TEST_WEAVIATE_HOST` servers. Without the guard, any scenario could pass on a server that silently added properties the adapter failed to declare itself. (A value of the wrong type for an already-declared property is rejected regardless of auto-schema; the guard protects the "never relies on auto-schema" claim, not the type check.)

### D13. ACL: dropped with a warning, never enforced

**How ACL works today.** `ACLOperator` emits an `allowed_users` column (a JSON-array string flagged `available_for_opensearch`). Nothing in `core/operators/vectordb/` handles it; it reaches OpenSearch only when a user maps it. Enforcement lives entirely in the API layer: `api/services/acl_query_builder.py` adds an `allowed_users` term filter to OpenSearch reads in `api/routes/documents.py`. Weaviate has no read path in docpipe, so there is nothing that could enforce an ACL stored there.

**Decision.**

- In `__init__`, the adapter removes every mapping whose `feature_name` equals `OperatorConstants.ACL.ALLOWED_USERS_COLUMN`, and logs one warning naming the dropped target property.
- If `allowed_users` appears in `available_features` but is unmapped, it logs one warning that ACLs are not enforced for Weaviate.
- The run never fails because of ACL.
- The only ACL-related import is that constant, from `docpipe.core.constants`. The adapter must not import `ACLOperator`, anything under `core/operators/acl/`, or anything under `docpipe.api`. A unit test asserts this by importing the adapter package in a clean interpreter and inspecting `sys.modules`.
- Weaviate RBAC and multi-tenancy stay out of scope (proposal Non-goals).

**Alternatives.**

- Reject a mapped `allowed_users` at startup. This is stricter, but was not chosen in review: a flow that maps `allowed_users` keeps running on Weaviate, with the warning as the signal.
- Store it as a plain TEXT property. Rejected because the data would look access-controlled when nothing enforces it, and any Weaviate client could read it.

### D14. Sparse (BM25) mode at parity with Milvus

| Concern | Milvus provider (today) | Weaviate provider |
|---|---|---|
| Where sparse scores come from | `SPARSE_FLOAT_VECTOR` field filled by a server-side `Function(BM25)` over `text` | BM25 over the inverted (keyword) index of the mapped content property, scored at query time |
| `sparse_embeddings` feature | skipped on insert; its mapping names the sparse field | skipped on insert; the mapping is accepted and produces no property |
| BM25 parameters | hardcoded k1 = 1.2, b = 0.75 | `Configure.inverted_index(bm25_k1=1.2, bm25_b=0.75)` when the flag is on |
| Content field | non-nullable with analyzer; must be mapped or inserts fail | must be mapped; checked in `__init__` before connecting, with an actionable error |
| Sparse-only runs (no dense columns) | supported via the operator's empty `dimension_mapping` | same path; collection created without `vector_config`; vector validation skipped |
| Flag off | no analyzer, so no BM25 | content stays `index_searchable` (Weaviate default), so BM25 is still available |
| Enrichment `is_supported` for sparse-only collections | unsupported (no `FLOAT_VECTOR`) | supported when the content property is searchable |

- **Precedence:** as for Milvus, `VectorDBOperator.__init__` copies the top-level `add_sparse_vector` into `adapter_config`, overriding any `provider_config.add_sparse_vector`. The operator's own dimension resolution reads only the top-level flag. The top-level flag is therefore the supported switch. Setting it only inside `provider_config` enables the adapter's BM25 configuration but not sparse-only runs, and the README says so.
- **Querying** stays a non-goal (proposal). Consumers run `collection.query.bm25(...)` or `collection.query.hybrid(...)` themselves; the README shows both.

**Alternatives.**

- Store externally computed sparse vectors (for example SPLADE) as a property. Rejected: Weaviate offers no native sparse-vector index, so the data would not be searchable, and docpipe's Milvus mode does not do this either.
- Keep rejecting `add_sparse_vector`. Superseded by the request for Milvus parity.
- Make BM25 indexing conditional on the flag (strict Milvus parity). Not chosen: it would remove keyword search by default, and `index_searchable` cannot be enabled on an existing property later.

## Risks / Trade-offs

- **[grpcio cap forces a downgrade from 1.84.0 to 1.78.0]** → Gated in task 1.1 (D11). Run the Milvus, OpenSearch, and telemetry unit suites plus the Milvus Lite integration test after relocking, and check advisories for the resolved version. If either check fails, escalate instead of forcing an override.
- **[Offset paging capped at `QUERY_MAXIMUM_RESULTS` for stale lookup]** → A single file with more than 10,000 chunks would leave older tail chunks undeleted. A warning is logged with the file ID, and the README documents raising `QUERY_MAXIMUM_RESULTS`. Chunk counts per file are far below this in practice.
- **[Dimension is only checkable by sampling]** → An empty collection skips the check, so the first insert fixes the dimension. A later wrong dimension then fails per object, which is still reported per chunk (D6).
- **[UUIDv5 upsert relies on replace-on-existing-UUID batch semantics]** → Integration test I-3 asserts it against the pinned server version. If the semantics differed, the stale-cleanup path would still prevent duplicates, but in-place updates would surface as per-object errors.
- **[`word` vs `field` tokenization chosen by rule, not configurable]** → The rule covers identity fields. A per-property override can be added later without changing the specs.
- **[Connecting in `__init__` makes flow validation require a reachable server]** → This matches existing adapters. Config-only errors (name pattern, reserved names, sparse flag) are raised before connecting, so most mistakes surface without a server.
- **[Users expect ACL enforcement with Weaviate]** → The dropped mapping and the unenforced-ACL warning both appear in the run log, the README's Troubleshooting section states that ACL is OpenSearch-only, and the proposal lists ACL as a non-goal. Because a mapped `allowed_users` is dropped rather than rejected, the warning is the main signal; task 5.4 makes it prominent in the docs.
- **[Sparse-only runs with memory-mapped chunks]** → `VectorDBOperator._extract_chunks_for_row` takes the file-streaming path only when both chunk and vector file references exist. With no vector columns, memmap-backed `chunked_content` falls into the in-memory path and the document fails. This is an existing operator limitation shared by Milvus sparse-only runs; this change does not modify the operator. It is documented in the README, and I-10 uses in-memory chunks.
- **[BM25 parameters are fixed]** → They match Milvus's hardcoded values. Exposing them would be an additive change later.
- **[`add_sparse_vector` set only in `provider_config`]** → The README states that the top-level flag is authoritative (D14 precedence).
- **[`schema_template_path` silently has no effect]** → One warning names the ignored option, and the README documents it as OpenSearch-only.
- **[Server-default quantization may be lossy (`DEFAULT_QUANTIZATION`)]** → Documented in the README. Configuring quantization is a non-goal.
- **[Two lockfiles (root and slim)]** → Both are regenerated in the same commit, and task 1.1 verifies `uv lock --check` in each.

## Migration Plan

Additive only. Existing flows are unaffected. Deploying requires the regenerated environment (`uv pip install -e ".[dev]"`). Rollback is reverting the change; no stored data or schema migrations are involved, and Weaviate collections created by the adapter remain usable by any Weaviate client.

## Open Questions

- Minimum Weaviate server version to document. The design uses self-provided named vectors and `insert_many`, both long supported. Task 5.4 records the client 4.23.1 compatibility floor from its release notes in the README, without changing behavior.
- Whether to move to server-side batching (`batch.stream()`, server ≥1.36) in a follow-up once throughput data from the integration environment is available.
