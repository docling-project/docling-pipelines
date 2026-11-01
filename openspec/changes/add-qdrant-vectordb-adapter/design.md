# Design

## Context

**Current shape of the VectorDB operator.** `VectorDBOperator` builds one adapter through `VectorStoreFactory.create(provider, **provider_config)` and drives it through `VectorStorePort`:

1. `index_exists()`, then `create_index(dimension_mapping=...)` or `validate_existing_schema(dimension_mapping=...)`.
2. `get_chunk_ids_for_documents(file_ids)` and `delete_documents_by_ids(stale)` for stale-chunk cleanup.
3. `index_documents([(pk, document), ...])` and `refresh_index()`.
4. `close()`, in the `finally` block of `transform`.

Feature mappings (`[{"feature_name", "mapped_column_name"}]`) are applied by the adapter. Each chunk document is a shallow copy of the row with every vector column replaced by that chunk's `list[float]`, and the chunk text under the key `content`. The operator generates each chunk key with `adapter.generate_chunk_pk(file_id=..., chunk_index=..., chunk_content=...)`, where `file_id` is the row's `id` value, and maps keys back to documents to attribute failures.

**Constraints observed in the current code:**

- **Failure shape.** The operator parses only `{"index": {"_id": <chunk pk>, "error": {"reason": str}}}` (`vectordb_operator.py`). The Milvus and OpenSearch adapters return other shapes, so their chunk failures are recorded as one document named `unknown`. The Weaviate design (D6) emits the parsed shape; Qdrant does the same.
- **Stale-chunk lookup.** Milvus finds a file's chunks with a primary-key prefix filter (`pk like "<sha3_512(id)>_%"`). The operator passes `id` values to `get_chunk_ids_for_documents` and expects `dict[str, set[str]]` keyed by those values.
- **Sparse mode.** `add_sparse_vector` is read from the operator's top level. It allows zero dense columns, changes the default mappings (`sparse_embeddings`, and `content` to `text`), and is forwarded to the adapter. No upstream operator produces sparse vectors; `sparse_embeddings` is declared by the vectordb operator itself and nothing fills it.
- **Provider lists.** `provider` valid values come from the factory registry, but the operator descriptions hard-code "opensearch, milvus", `_get_vectordb_provider_schemas()` is a hand-written map, `VectorDBMetadataFetcher` routes with a hard-coded `if`, and the panel falls back to OpenSearch for an unknown provider.
- **Secrets.** `OperatorUtils._to_docpipe` marks a field sensitive when its key is in `SENSITIVE_FIELD_NAMES` (which includes `api_key`) or its schema carries `sensitive: True`. `resolve_env_var` resolves `$VAR`, `${VAR}`, and `${VAR:default}`. `vault://` references are resolved by `PythonOperatorExecutor._resolve_operator_params` before the operator is built; during flow validation `FlowValidator` replaces them with `__vault_placeholder__`.

**Upstream facts that shape the approach.** All observed against real `qdrant/qdrant` containers with `qdrant-client` 1.20.0 (released 2026-10-22, Apache-2.0). Server 1.20.0 is the reference; older servers were checked where the behavior differs.

- **Point IDs** must be unsigned integers or UUIDs. A string such as `abc_chunk_1` is rejected (`value abc_chunk_1 is not a valid point ID, valid values are either an unsigned integer or a UUID`). UUID spellings are normalized. Upserting an existing ID replaces the whole point, including payload fields and vectors that the new point omits.
- **Collection names** are case-sensitive, 1 to 255 characters, and must not contain `/`, `\`, `:`, `*`, or `?`. The client also rejects `.` and `..`. Spaces, dots, hyphens, and non-ASCII letters are accepted. Creating an existing collection returns 409.
- **Named vectors** are read back from `config.params.vectors` as `dict[str, VectorParams]`; a single unnamed vector reads back as one `VectorParams`, and a sparse-only collection as `{}`. A point may carry a subset of the named vectors. Cosine vectors are stored normalized.
- **Batches are not atomic.** On 1.20.0 a wrong dimension rejects the whole batch, but an unknown vector name, an unknown sparse name, or a sparse value sent to a dense field returns 400 after writing an unpredictable subset (1,000 good points and 1 bad one left 749 points over REST and 444 over gRPC). On 1.16.0 and older, a wrong dimension also leaves partial writes. gRPC stores `NaN` vectors that REST rejects.
- **Prefix matching** (`MatchPrefix`, keyword index with `prefix: true`) exists from server 1.19.0 and client 1.19. On 1.16.0 and 1.18.3 the server accepts `prefix: true` but builds the index without it. `MatchText` is not a whole-value or prefix match, and its meaning changed between 1.16 and 1.19. An exact `MatchValue` or `MatchAny` on a keyword field works on every version from 1.12.6.
- **Scroll paging** with `next_page_offset` returns every matching point with no result window (12,000 of 30,000 points at page sizes 1,000 to 50,000).
- **Strict mode** (`unindexed_filtering_retrieve`, `unindexed_filtering_update`) exists from 1.12.6 and is off by default on self-hosted servers. When on, filters need a matching payload index; deletes by ID are always allowed.
- **Payloads are schemaless.** One field can hold an integer in one point and a string in another; an integer payload index skips the values that are not integers.
- **Server-side BM25.** A `models.Document(text=..., model="qdrant/bm25")` sent for a sparse vector is turned into BM25 term weights by the server, in upsert and query, over REST and gRPC, with no FastEmbed and no Cloud. It works on 1.15.3, 1.16.0, and 1.20.0. On 1.15.1 and 1.13.6 it fails with 500 `InferenceService is not initialized`. The IDF modifier must be set on the sparse vector explicitly; without it the server accepts the documents silently. Unknown BM25 options are accepted silently.
- **Authentication.** Without a key, protected endpoints return 401 `Must provide an API key or an Authorization bearer token`. `/`, `/healthz`, `/readyz`, and `/livez` need no key, so a health probe does not prove the key works; `get_collections` does. The client warns `Api key is used with an insecure connection.` when a key is used over HTTP. An `http://` URL stays HTTP even with `https=True`. The key never appeared in any exception text, REST or gRPC.
- **Version check.** By default the client checks the server version in a background thread and only warns, asynchronously, when the major versions differ or the minor versions differ by more than one.
- **Errors.** REST raises `qdrant_client.http.exceptions.UnexpectedResponse` (with `status_code` and the server message); gRPC raises `grpc.RpcError`. A local-mode client raises `ValueError` instead.
- **Dependency.** `qdrant-client` 1.20.0 requires `grpcio>=1.41.0`, `httpx[http2]>=0.20.0`, `protobuf>=3.20.0`, `pydantic>=1.10.8` (excluding early 2.x), `urllib3<3,>=1.26.14`, `portalocker<5.0,>=2.7.0`, and `numpy>=1.26` on Python 3.12. Everything except `portalocker` is already in the lockfiles at compatible versions.

## Goals / Non-Goals

**Goals:**

- `provider: "qdrant"` works end to end: configuration, connection, collection lifecycle, idempotent writes, stale-chunk cleanup, flow enrichment, and the panel.
- Behavior that depends on a server version is either portable across supported versions or checked at initialization.
- A failed write never hides which chunks failed, and never leaves a collection the operator cannot write to again.
- Reuse the Weaviate change's provider-agnostic decisions instead of inventing parallel ones.

**Non-Goals (design level, in addition to the proposal's):**

- Supporting servers older than 1.15.3 in sparse mode, or prefix-based lookups on servers older than 1.19.
- Making the existing adapters' failure shapes match the operator.
- A shared client or redaction module across providers. Shared helpers come only from `utils/operators/vectordb_utils.py`.

## Decisions

### D1. Package layout and DDD boundaries

A new package `adapters/outbound/qdrant/` whose `__init__.py` exports nothing, as for Weaviate:

| File | Responsibility |
|---|---|
| `config.py` | `QdrantConfig` Pydantic model and every check that runs before connecting. Does not import `qdrant_client`. |
| `client.py` | Builds `QdrantClient`, resolves credentials, checks the HTTPS rule again, runs the readiness and version check, redacts errors, and closes. |
| `index_manager.py` | Collection creation and validation, payload indexes. |
| `batch_processor.py` | Point preparation and pre-validation, batched upserts with per-point retry, stale-key lookup, deletes, count, and queries. |
| `adapter.py` | `QdrantAdapter(VectorStorePort)`: wires the parts and enforces the initialization order. |
| `resource_metadata.py` | `QdrantResourceMetadata` for flow enrichment. |

Port delegation follows the same shape as `MilvusAdapter`: `index_exists`, `create_index`, and `validate_existing_schema` go to the index manager; `index_documents`, `get_chunk_ids_for_documents`, `delete_documents_by_ids`, `get_document_count`, and `query_by_doc_names` go to the batch processor; `detect_vector_dimension` and `detect_all_vector_dimensions` use the shared helpers in `vectordb_utils.py`; `generate_chunk_pk` uses `generate_positional_pk`; `refresh_index` is a no-op, because a write with `wait=True` is visible when it returns; `close` goes to the client. `metadata_fetcher.py` imports `resource_metadata` lazily. Nothing in `domain/` or `ports/` imports from the adapter.

### D2. Lazy registration

`VectorStoreFactory.register_lazy("qdrant", "<package>.adapter", "QdrantAdapter")` sits next to the Milvus entry, so a metadata request does not import `qdrant_client`, `grpc`, or `httpx`. `_get_vectordb_provider_schemas()` gets a `qdrant` entry built from `QdrantConfig`. `config.py` must not import `qdrant_client`; a test imports `config.py` with `qdrant_client` blocked in `sys.modules`.

### D3. Configuration fields

`QdrantConfig(BaseModel, extra="ignore")`, so keys the operator injects (`available_features`, `feature_mappings`, `add_sparse_vector`, `schema_template_path`) are ignored by the model and read where needed. The operator does not pass `validating_flow` to adapters today; Weaviate design D18 adds that, and task 5.1 checks for it.

| Field | Type | Default | Notes |
|---|---|---|---|
| `collection_name` | str | required | Server naming rule, checked before connecting (below). |
| `url` | str \| None | None | Full URL, for example a Qdrant Cloud cluster. Its scheme decides HTTP or HTTPS. |
| `host` | str | `"localhost"` | Used when `url` is not set. |
| `port` | int | 6333 | REST port; 1-65535. |
| `grpc_port` | int | 6334 | 1-65535. |
| `prefer_grpc` | bool | False | REST by default; gRPC is opt-in. |
| `https` | bool | False | Used with `host`. Ignored with `url`, whose scheme decides. |
| `api_key` | str \| None | None | Sensitive. Literal, `$VAR`, or `${VAR}`. |
| `timeout` | int | 30 | Seconds, at least 1. The client's REST default (5 seconds) is too short for large upserts. |
| `batch_size` | int | 100 | Points per upsert request, 1-1000. |
| `distance_metric` | Literal[`cosine`, `dot`, `euclid`, `manhattan`] | `cosine` | Mapped to Qdrant's `Cosine`, `Dot`, `Euclid`, `Manhattan`. |
| `index_parameters` | dict | `{}` | HNSW settings for new dense vectors (D8). |

- **`url` and a non-default `host` are mutually exclusive.** The client raises `Only one of <location>, <url>, <host> or <path> should be specified.` when both reach it; the config reports the conflict by field name before that.
- **Collection name rule.** 1 to 255 characters; none of `/`, `\`, `:`, `*`, `?`; no control characters; not `.` or `..`. This is the server's own rule plus one addition: the server also accepts control characters such as a tab, but such a name cannot be typed or shown reliably, so the provider rejects it. Any other existing collection can be used. The rule is enforced by the backend; it is not published in metadata.
- **Credentials.** `api_key` is checked with `resolve_env_var` in a model validator and the result is discarded; the client resolves it again at connect time, so resolved values are never stored on the model. An unset `$VAR` fails with a message that names the variable and no value. As in the Weaviate design, a literal made only of upper-case letters and underscores is substituted when an environment variable of that name exists, because that is the shared resolver's behavior; the docs recommend the explicit `$VAR` form.
- **The API key requires HTTPS** (D4). There is no opt-in override.
- **Error messages** are built from each Pydantic error's location and message only, never its input value, and re-raised `from None`. If the Weaviate change's configuration-error formatter exists by then, it is reused.
- **Constants.** Add `OperatorConstants.VectorDB.QDRANT = "qdrant"` and the new config keys; reuse existing constants for shared keys.

*Alternative:* a `connection_type` field with `custom` and `cloud`, as for Weaviate. Rejected because Qdrant Cloud needs no separate SDK entry point: a cluster is an `https://` URL plus an API key, so a URL field covers it.

### D4. Connection, authentication, and error hygiene

- **HTTPS rule.** When `api_key` is set, the connection must be HTTPS: with `url`, its scheme must be `https`; with `host`, `https` must be true. Otherwise initialization fails before connecting, with a message stating that an API key requires an HTTPS connection. The client repeats the check, because flow enrichment builds a client without the adapter.
- **Client construction.** `QdrantClient(url=... | host=..., port, grpc_port, prefer_grpc, https, api_key, timeout, check_compatibility=False)`. The background version check is disabled because its warning is asynchronous and arrives after construction, attributed to whichever client happens to be logging; D5 replaces it with an explicit check.
- **Readiness.** The first network call is `get_collections()`, an authenticated call, so a wrong key fails at initialization rather than on the first write. A failure raises an error naming Qdrant, the target address (URL or host and port), and the redacted cause. The client is closed before raising.
- **Redaction.** A redaction helper in `client.py` replaces the resolved API key, and any `api-key` or `Authorization` header text, with `***` in every raised message, log record, failed-item reason, and enrichment `error`. The client never echoed the key in the tests, so this is defense in depth. It is done in the client because the factory and the operator copy the original error text into their own messages.
- **Error types.** Errors are recognized as `UnexpectedResponse` (REST) or `grpc.RpcError` (gRPC); both are handled wherever the provider inspects a status.
- **Logs** use `%s` formatting and carry the target address and whether a key is set, never the key.
- **Close.** `close()` is idempotent. As in the Weaviate design, the connection is closed in three places: the `finally` block of `transform`, the `finally` block of the enrichment fetch, and `validate` under flow validation (D16).

### D5. Server version check

Right after readiness, the client reads the server version from `info()` (`GET /`).

- **Sparse mode** requires server 1.15.3 or later, the first version observed to run `qdrant/bm25` inference; 1.15.1 fails every BM25 write with 500, and 1.15.2 was not tested. On an older server, initialization fails with a message naming the server version and the minimum.
- **Dense mode** has no minimum beyond what the pinned client supports. The provider's own checks (D10, D14) are written to be correct on servers that write partial batches and have no prefix filter.
- **Client window.** When the server's major version differs from the client's, or the minor versions differ by more than one, the provider logs one warning naming both versions, synchronously, instead of the client's asynchronous one.

### D6. Point identity

- **Chunk key.** `generate_chunk_pk` returns `generate_positional_pk(file_id=..., chunk_index=...)`: `{sha3_512(file_id)}_chunk_{index}`, the OpenSearch format that the Weaviate design also adopts. The Milvus content-hash key is not used, because it changes a chunk's ID whenever its text changes.
- **Point ID.** `uuid.uuid5(uuid.NAMESPACE_URL, "docpipe:qdrant:" + chunk_key)`, because Qdrant rejects arbitrary string IDs. The namespace and prefix never change once released. A unit test pins one example: the key `example_chunk_0` gives `79a2b24e-4ff8-5ec4-b8f1-77ac5d83102b`. The same key always maps to the same point, so re-ingest replaces chunks in place and retries are idempotent.
- **Identity payload fields.** Each point stores the chunk key verbatim in `pk` and the file part of the key (the text before `_chunk_`) in `pk_file`. `pk_file` exists because prefix filters are not portable (D14).
- **Mapping rules, before connecting.** The primary feature must be mapped to `pk`. Initialization fails when it is mapped elsewhere, when another feature is mapped to `pk`, or when any feature is mapped to `pk_file`.
- **Document identity** when `id` is missing follows the operator requirement "Document identity" (Weaviate design D5); see task 1.3.

### D7. Payload mapping and names

- **Values.** Only mapped features are written, as the other adapters do. The feature types of `OPERATOR_TYPE_PATTERN` map as follows:

  | Feature type | Payload value |
  |---|---|
  | `string`, `enum`, `crn`, `date`, `time`, `timestamp`, and the `text` and `keyword` aliases | string |
  | `int8`, `int16`, `int32`, `int64` | integer |
  | `float`, `double`, `sfloat` | float |
  | `bool`, `boolean` | boolean |
  | `json` | native JSON value; unlike Weaviate, not serialized to text, because Qdrant payloads support nested objects |
  | `list` | JSON array |

  Arrays are converted with `tolist()`; `None` values are omitted. A type outside the table is stored as a string, with one warning naming the feature.
- **Content.** The chunk text is stored under the mapped content name (default `text`).
- **Names.** A mapped payload name must be non-empty and must not contain `.`, `[`, or `]`, because Qdrant filter keys use them for nested paths and array elements; such a name could be written but not filtered reliably. The names `pk` and `pk_file` are reserved (D6). These checks run before connecting.
- **Vector names.** A dense vector is named by its column's mapped name. Two vector columns mapped to the same name, or a vector name equal to a payload name, fail before connecting.

### D8. Collection creation

- **Creation.** `create_collection` with an explicit `vectors_config` dict: one `VectorParams(size=<detected dimension>, distance=<distance_metric>, hnsw_config=<index_parameters>)` per detected dense column. In sparse mode it adds `sparse_vectors_config={<sparse name>: SparseVectorParams(modifier=Modifier.IDF)}` (D13). A sparse-only run creates the sparse vector only.
- **`index_parameters`.** Accepted keys are the HNSW settings `m`, `ef_construct`, `full_scan_threshold`, `max_indexing_threads`, `payload_m` (non-negative integers), and `on_disk` (boolean). Any other key, or a value of the wrong type, fails before connecting with a message naming the key. The keys are listed in `config.py`, which must not import `qdrant_client` (D2).
- **Payload indexes.** Right after creation, the provider creates keyword payload indexes on `pk`, `pk_file`, the payload names mapped from `id` and `name`, and every mapped `keyword` feature. The provider filters on `pk_file` and the name field (D14); the other indexed fields are the ones users are most likely to filter on. Every field the provider filters on is indexed, so it works with strict mode turned on. It reads `payload_schema` back and fails if an index is missing, because the server can accept an index request and build something else (observed for `prefix: true` on old servers).
- **Concurrent creation.** Micro-batching can run several workers at once, and `index_exists()` followed by `create_index()` is not atomic. When creation returns 409, the provider validates the existing collection (D9) instead of failing.

*Alternative:* let the first upsert create nothing and rely on schemaless payloads. Rejected because vectors need an explicit configuration and the identity fields need indexes before the first filter.

### D9. Existing collection validation

Every mismatch is collected into one error (400), so the user sees all problems at once. Nothing is changed when a check fails.

- **Dense vectors.** The collection must use named vectors; a collection with a single unnamed vector is rejected with a message stating that only named vectors are supported. Each run vector must exist by name with the run's dimension and the configured distance; a missing vector, a different dimension, or a different distance is reported with both values. Qdrant stores the dimension in the collection configuration, so the check does not depend on the collection holding points.
- **Dense run on a sparse-only collection** fails with a message stating that the collection has no dense vector.
- **Sparse mode.** The mapped sparse vector must exist with the IDF modifier; a missing vector or a missing modifier is reported. When sparse mode is off, a sparse vector in the collection is ignored.
- **Identity indexes.** An existing index on `pk`, `pk_file`, the `id` or `name` field, or a mapped `keyword` field must be of type keyword. An index of another type is reported, and the message tells the user to recreate the collection or use a new name, because changing an index type in place silently replaces it.
- **Additions.** Only when every check passed, missing identity payload indexes are created, then read back as in D8.

### D10. Write path

- **Preparation.** Each document becomes a `PointStruct(id=<uuid5>, vector={...}, payload={...})` with the identity fields, mapped payload, and named vectors.
- **Pre-validation, before sending.** Every dense vector must have the collection's dimension for its name and contain only finite numbers, and every vector name must exist in the collection. A point that fails is reported as failed with a reason naming the vector and the problem, and is not sent. This matters because a rejected batch can be partly written, and gRPC stores `NaN`.
- **Batches.** Points are sent with `upsert(..., wait=True)` in batches of at most `batch_size` points and about 3 MB, measured with `calculate_batch_size_bytes` on the plain payload and vector dicts (it serializes with `json.dumps`, so it is not given `PointStruct` or `Document` objects), well under the server's 32 MiB REST body limit.
- **Rejected batch.** When the server rejects a batch as invalid (HTTP 400 or 422, or gRPC `INVALID_ARGUMENT`), the provider resends that batch one point at a time and reports only the points that fail. The extra requests happen only on failure and are bounded by `batch_size`; deterministic IDs make the resend idempotent.
- **Request failure.** When a batch fails for any other reason (connection, timeout, 401, 403, 404, 429, or 5xx), every point in it is reported as failed with the redacted error, and later batches are still attempted. Some of those points may have been written; their documents are recorded as failed, and the next run replaces them in place.
- **Failed items** use `{"index": {"_id": <chunk pk>, "error": {"reason": <redacted message>}}}`, the shape the operator parses.

*Alternative:* `upload_points` with its built-in batching and retries. Rejected because it defaults to `wait=False`, retries whole batches, and raises without per-point attribution.

### D11. Dependency and lockfiles

- **Pin.** Exact `"qdrant-client==1.20.0"` in `[project.dependencies]` of both `pyproject.toml` and `slim/pyproject.toml`, in alphabetical order, matching the existing exact-pin style.
- **Evidence.** Trial resolution with `uv lock` in the root and in `slim/` (on main at 63e71e39) gave the same result in both projects:

  | Project | Packages resolved | Added | Changed |
  |---|---|---|---|
  | root | 500 | `qdrant-client` 1.20.0, `portalocker` 4.4.2 | none |
  | `slim/` | 483 | `qdrant-client` 1.20.0, `portalocker` 4.4.2 | none |

  `grpcio` 1.84.0, `protobuf` 6.33.6, `httpx` 0.28.1 with `h2` 4.4.1, `numpy`, `pydantic`, and `urllib3` already satisfy the client's constraints.
- **Gate (task 1.1).** Before touching a real file, re-run the trial in scratch copies against the then-current main and the then-latest client release, and check OSV for every added or changed package. If resolution changes an existing package, a package has a published advisory, or the existing Milvus, OpenSearch, or telemetry tests fail, stop and ask the maintainers. Do not add an `override-dependencies` entry on your own.
- **Lockfiles.** Run `uv lock` in both directories, commit both `pyproject.toml` files and both `uv.lock` files together, and verify with `uv lock --check` in each.

### D12. Testing strategy

| Level | Location | Scope |
|---|---|---|
| Unit (client mocked) | `tests/unit/operators/vectordb/test_qdrant_{config,client,index_manager,batch_processor,adapter,resource_metadata}.py` | Every requirement scenario that does not need a server. Runs in CI through `pytest tests/unit -m "unit and not integration"`. |
| Operator (adapter mocked) | `tests/unit/operators/vectordb/test_vectordb_operator.py`, `test_metadata_fetcher.py` | Registration, metadata, routing. |
| Real server | `tests/integration/qdrant/test_qdrant_with_container.py` | Against `docker/docker-compose.qdrant.yml`. |

- **Real-server suite.** `docker/docker-compose.qdrant.yml` pins `qdrant/qdrant:v1.20.0`, binds ports to `127.0.0.1` only, and carries a test-only header. A second service with an API key and TLS covers authentication. The suite starts and stops the compose services itself, like the OpenSearch container test: a session fixture first generates a self-signed certificate into a temporary directory (never committed), passes that directory to compose through an environment variable used in the volume mount, and makes the test client trust it through `SSL_CERT_FILE`, which the client's HTTP library honors (to be confirmed in task 6.2). `DOCPIPE_TEST_QDRANT_URL` overrides the target, mirroring the other `DOCPIPE_TEST_*` variables. Each test uses a unique collection and deletes it in teardown. The suite is marked `integration` by `tests/conftest.py`'s path rule, so the unit job excludes it.
- **Scenarios that need a real server**, because local mode and mocks behave differently: partial batch writes and the per-point resend, the payload-index read-back, strict mode, the 409 race, server-side BM25, paging over 10,000 points, and authentication.
- **CI.** Proposed: a `qdrant-integration-test` job that runs the suite on a GitHub runner, which has Docker, so the suite starts both compose services itself as it does locally. The image is small and starts in seconds. The Weaviate change keeps its suite manual-only and lists one CI job for all vector databases as an open question; the decision should be the same for both providers (Open Questions). Until then the suite stays manual-only. Either way, a skipped suite is reported as blocked, never as passed.
- **Local mode is not used** as a stand-in for the server: its errors are `ValueError`, it accepts IDs the server rejects, its batches never write partially, its payload indexes do nothing, and its BM25 needs `fastembed`.
- **Secrets in tests** come from `monkeypatch.setenv` and `$VAR` references; where a literal is unavoidable it carries the detect-secrets allowlist marker.

### D13. Sparse (BM25) mode

- **Meaning.** With `add_sparse_vector: true` (the operator's top-level flag, which takes precedence over `provider_config`), the collection gets a named sparse vector with the IDF modifier, and each point sends `models.Document(text=<chunk text>, model="qdrant/bm25")` for it. The server tokenizes the text and stores BM25 term weights; IDF is computed by the server at query time.
- **Names.** The sparse vector is named by the `sparse_embeddings` mapping (default `sparse_embeddings`). Any upstream values for that feature are not read: no upstream operator produces them, and the BM25 vector is computed from the chunk text.
- **Content.** The content feature must be mapped; otherwise initialization fails before connecting with a message stating that sparse mode needs the content feature mapped to a payload field.
- **Options.** No BM25 options are sent. The server accepts unknown options silently, so passing user options would hide typos.
- **Server version.** 1.15.3 or later (D5).
- **Sparse-only runs** are allowed when the chunks are provided in memory; memory-mapped chunks without dense vectors are an existing operator limitation.

*Alternatives:*
- Client-side BM25 with `fastembed`. Rejected because it adds a heavy dependency (an ONNX runtime and tokenizers) for a result the server computes itself.
- Rejecting `add_sparse_vector` for Qdrant. Rejected because sparse retrieval is a main reason to choose Qdrant, and the server feature has been stable since 1.15.3.

### D14. Stale-chunk lookup, deletes, count, and query

- **Lookup.** `get_chunk_ids_for_documents(ids)` maps each `id` to `sha3_512(id)` and scrolls with `MatchAny` on `pk_file` (at most 100 values per filter), `with_payload=["pk", "pk_file"]`, `with_vectors=False`, following `next_page_offset` until it is empty. There is no result window, so every key is returned. Results are keyed by the input `id`; ids with no chunks are omitted. On error it logs a warning and returns `{}`, so the write still runs.
  - *Alternative:* `MatchPrefix` on `pk`. Rejected because it needs server 1.19 and client 1.19, and older servers accept a prefix index silently without building it.
- **Delete.** `delete_documents_by_ids(keys)` converts keys to point IDs (D6) and deletes in requests of 500 IDs with `wait=True`. The server ignores missing IDs and does not report how many points it deleted, so the success count is the number of keys in requests that succeeded, and the failure count the number in requests that failed.
- **Count.** `count(exact=True)`; 0 on error, logged.
- **Query by name.** `query_by_doc_names(names, fields)` scrolls with `MatchAny` on the payload field mapped from `name`, returning payloads limited to `fields`.

### D15. Flow enrichment

- **Shape.** The five keys of the other providers: `available_resources` (collection names), `selected_resource_schema`, `feature_mappings`, `is_docpipe_supported_resource`, and `stored_resource_metadata` (`vector_similarity`, `dimension_size`). As defined by the Weaviate change, `is_docpipe_supported_resource` may also carry `sparse_eligible` and `error`.
- **Schema.** `selected_resource_schema` lists dense vectors as `{"type": "VECTOR", "distance": <Qdrant name>, "dimension": <size>}`, sparse vectors as `{"type": "SPARSE_VECTOR", "modifier": <name or null>}`, and payload indexes as `{"type": <index type in upper case>}`.
- **Similarity.** `vector_similarity` uses the config vocabulary of `distance_metric` (`cosine`, `dot`, `euclid`, `manhattan`), mapped from Qdrant's names (`Cosine`, `Dot`, `Euclid`, `Manhattan`), and is taken from the first dense vector. The panel copies this value into `distance_metric` when an existing collection is selected, so it must be a value the config accepts. `selected_resource_schema` uses the same names.
- **Support rules** mirror D9 for the node's current mode: an unnamed-vector collection, wrong-typed identity indexes, no dense vector in a dense run, or (with `add_sparse_vector` true) no IDF sparse vector make it unsupported.
- **`sparse_eligible`** is set for every existing collection: true when the collection would pass every D9 check with `add_sparse_vector` true. A collection with only an IDF sparse vector is therefore unsupported with sparse mode off, but sparse-eligible. A dense collection without an IDF sparse vector is never sparse-eligible, so the panel does not offer BM25 for it.
- **Mappings.** Saved mappings, then mappings derived from the live collection, then the defaults from `compute_default_feature_mappings`, with `pk` for the primary feature.
- **Failures.** No URL and no host give the plain empty result with no `error`. An unreachable server or a rejected key gives `{"supported": false, "error": "<redacted reason>"}` without raising, and other nodes are still enriched. The client is closed in `finally`. The HTTPS rule (D4) is checked before connecting.

### D16. Shared operator changes and flow validation

- **Release after flow validation** (Weaviate D17) and the **Vault placeholder** (Weaviate D18) are provider-agnostic. They are implemented once, by whichever change is implemented first.
- **Placeholder.** The Qdrant client makes no network call in its constructor once the version check is disabled (D4), so the first call is the readiness check. Under flow validation, when `api_key` equals the shared placeholder constant, the provider runs every configuration check, including the HTTPS rule, and skips connecting. Outside flow validation, a key equal to the placeholder text is used like any other.
- **Construction failure.** When a step after connecting fails during construction, the provider closes the client before raising.

### D17. Frontend

- **Scope.** The VectorDB panel and tearsheet only. A colocated `QdrantConnectionFields.tsx` holds no state; pure rules (collection name, HTTPS with an API key, port ranges) live in `vectordb-qdrant.ts`; strings live in `VectorDB.messages.ts`, as in the Weaviate design.
- **Map entry.** `PROVIDER_CONFIG_MAP.qdrant`: resource key `collection_name`, label "Collection", similarity key `distance_metric` with labels Cosine, Dot, Euclid, and Manhattan, no engine selector, sparse capability on with the label "BM25", resource-specific keys stripped before enrichment, and a default config. Its `advancedOnlyKeys` contain `index_parameters`, so that key stays editable in Advanced JSON, survives save and reopen, and is not sent to enrichment. It uses the data-driven `supportsSparse`, `sparseLabel`, and `advancedOnlyKeys` fields and the `error` and `sparse_eligible` enrichment types (Weaviate D16); if those do not exist yet, they are added first (task 7.1).
- **Connection fields.** A choice between "URL" and "Host and port"; switching removes the inactive keys in one write. HTTPS toggle (host mode), gRPC port and preference, and timeout. The API key reuses `VaultInput` unchanged.
- **Validation.** An API key over HTTP (an `http://` URL, or host mode with HTTPS off), an empty URL, or an invalid port shows an inline error, blocks opening the tearsheet and enrichment, and moves focus to the first invalid field. The collection name is entered inside the tearsheet, so an invalid name is shown there and does not block opening it.
- **Tearsheet.** The collection-name rule and placeholder, the distance metric without an engine control, and the BM25 checkbox: shown for a new collection, shown for an existing one only when `sparse_eligible` is true, and preserved on reopen. The enrichment `error` is shown. `index_parameters` stays in Advanced JSON.

## Risks / Trade-offs

- **[New dependency]** → `qdrant-client` and `portalocker` join both lockfiles. Mitigation: the trial changed no other package; the task 1.1 gate re-checks before any real change.
- **[Partial batch writes]** → a rejected batch may leave some points written. Mitigation: pre-validation removes the known causes, the per-point resend attributes the rest, deterministic IDs make reruns replace whatever was written, and the owning documents are always recorded as failed.
- **[Extra payload field]** → `pk_file` is stored on every point. Mitigation: it is the only portable way to look up a file's chunks, it is reserved and documented, and its index keeps lookups fast.
- **[Server version drift]** → BM25 and filter semantics changed across releases. Mitigation: sparse mode is version-checked at initialization; the provider uses only `MatchValue` and `MatchAny`, which behave the same on every tested version; the real-server suite pins its image.
- **[Two providers in flight]** → the Weaviate and Qdrant changes touch the same operator and panel code. Mitigation: shared work is done once (proposal, "Relationship to the Weaviate change"), and the frontend requirement is added separately so the archives do not overwrite each other.

## Migration Plan

No migration: the provider is new and opt-in, and existing flows are unaffected. A flow switches to Qdrant by setting `provider: "qdrant"` and a `provider_config`. Rollback is removing the registration and the dependency; existing Qdrant collections stay untouched.

## Open Questions

- **CI job for the real-server suite** (D12): add the proposed `qdrant-integration-test` job, or keep the suite manual-only like the OpenSearch, Milvus, and Weaviate container tests? This is the same question as the Weaviate change's open question on one CI job for all vector databases.
- **Private certificate authorities:** self-hosted servers with a private CA are trusted through the system trust store or `SSL_CERT_FILE`. Should `provider_config` also accept a CA bundle path?
- **Minimum server version for dense mode:** is "no minimum, version-independent behavior" acceptable, or should the provider require a tested release window (for example 1.16 and later)?
